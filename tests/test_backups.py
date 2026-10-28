"""Backup inspection stays read-only and never evaluates configuration."""

import hashlib
import json
import os
import subprocess
import threading
from dataclasses import FrozenInstanceError, replace

import pytest

from hyprmod.core import backups, config, health, persistence


@pytest.fixture
def store(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    return directory


@pytest.fixture
def output(tmp_path):
    return tmp_path / "attune.lua"


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Inspection must not invoke Lua, validators, IPC or load_any")

    monkeypatch.setattr(persistence, "validate_lua", forbidden)
    monkeypatch.setattr(health, "collect_snapshot", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


def canonical(values=None):
    return persistence.build_text(values or {}, config.ConfigSections())


def put(directory, text):
    raw = text.encode() if isinstance(text, str) else text
    name = hashlib.sha256(raw).hexdigest() + ".lua"
    (directory / name).write_bytes(raw)
    return name


class TestListing:
    def test_canonical_hash_summary_and_roundtrip(self, store, output):
        text = persistence.build_text(
            {"general:border_size": "2"},
            config.ConfigSections(
                monitors=["monitor = DP-1, disable"],
                animations=["animation = windows, 0"],
                beziers=["bezier = test, 0, 0, 1, 1"],
            ),
        )
        name = put(store, text)
        listing = backups.collect_list(output, backup_dir=store)
        row = listing.backups[0]
        assert listing.status == "available"
        assert row.name == name and row.sha256 == name[:-4]
        assert row.status == "valid"
        assert row.summary == backups.BackupSummary(1, 1, 1, 1)
        assert row.size_bytes == len(text.encode())
        assert row.modified_ns == (store / name).stat().st_mtime_ns
        assert "not save history" in listing.notes[0]
        assert backups.BackupListing.from_json(listing.to_json()) == listing
        with pytest.raises(FrozenInstanceError):
            setattr(row, "name", "changed")

    def test_bad_hash_foreign_malformed_empty_binary_oversize(self, store, output):
        names = [
            put(store, text)
            for text in (
                "os.execute('never')",
                persistence.MARKER + persistence.RECORD + "bad\n",
                b"",
                b"\x00\xff",
                b"a" * (backups.MAX_FILE_BYTES + 1),
            )
        ]
        tampered = "f" * 64 + ".lua"
        (store / tampered).write_text(canonical())
        result = backups.collect_list(output, backup_dir=store)
        assert {r.name for r in result.backups} == set(names + [tampered])
        assert all(r.status == "invalid" for r in result.backups)
        assert "SHA256" in next(r.detail for r in result.backups if r.name == tampered)
        assert result.status == "partial"

    def test_entry_links_and_special_files_are_rows(self, store, output, tmp_path):
        target = tmp_path / "source"
        target.write_text(canonical())
        for number in range(4):
            path = store / (f"{number:064x}.lua")
            if number == 0:
                path.symlink_to(target)
            elif number == 1:
                os.link(target, path)
            elif number == 2:
                os.mkfifo(path)
            else:
                path.mkdir()
        rows = backups.collect_list(output, backup_dir=store).backups
        assert len(rows) == 4
        assert all(row.status == "invalid" for row in rows)

    def test_parent_symlink_and_entry_name_filter(self, store, output, tmp_path):
        name = put(store, canonical())
        for bad in (name.upper(), "a.lua", "a" * 63 + ".lua", name + ".bak"):
            (store / bad).write_text("ignored")
        link = tmp_path / "linked"
        link.symlink_to(store, target_is_directory=True)
        result = backups.collect_list(output, backup_dir=link)
        assert [r.name for r in result.backups] == [name]
        assert result.backups[0].status == "valid"

    def test_absent_directory_creates_nothing(self, output, tmp_path):
        missing = tmp_path / "absent" / "backups"
        before = set(tmp_path.iterdir())
        result = backups.collect_list(output, backup_dir=missing)
        assert result.status == "unavailable" and not result.backups
        assert "unavailable" in result.notes[-1]
        assert set(tmp_path.iterdir()) == before

    def test_deterministic_candidate_cap(self, store, output):
        for number in reversed(range(70)):
            (store / f"{number:064x}.lua").write_text("foreign")
        result = backups.collect_list(output, backup_dir=store)
        assert [r.name for r in result.backups] == [f"{n:064x}.lua" for n in range(64)]
        assert "6 hash-named candidates omitted" in " ".join(result.notes)

    def test_directory_scan_cap(self, store, output):
        for number in range(1001):
            (store / str(number)).touch()
        listing = backups.collect_list(output, backup_dir=store)
        assert listing.status == "partial"
        assert "1000 entries" in " ".join(listing.notes)

    def test_total_read_budget(self, store, output):
        for number in range(20):
            put(store, (str(number) + "a" * (backups.MAX_FILE_BYTES - 2)).encode())
        listing = backups.collect_list(output, backup_dir=store)
        assert sum(row.size_bytes or 0 for row in listing.backups) <= backups.MAX_TOTAL_BYTES
        assert any(row.status == "unavailable" for row in listing.backups)
        assert "budget" in " ".join(listing.notes)

    def test_unreadable_file_is_explicit(self, store, output, monkeypatch):
        name = put(store, canonical())
        original = backups._read

        def denied(root, candidate):
            if candidate == name:
                raise PermissionError("denied")
            return original(root, candidate)

        monkeypatch.setattr(backups, "_read", denied)
        row = backups.collect_list(output, backup_dir=store).backups[0]
        assert row.status == "unavailable" and "denied" in row.detail


class TestStableReads:
    def test_current_disappearing_during_read_is_not_missing(self, store, output, monkeypatch):
        name = put(store, canonical())
        output.write_text("foreign")
        original = os.fstat

        def removed(fd):
            info = original(fd)
            if output.exists() and info.st_ino == output.stat().st_ino:
                output.unlink()
            return info

        monkeypatch.setattr(backups.os, "fstat", removed)
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.current.status == "unavailable"
        assert result.status == "error" and result.removed_lines is None

    def test_replacement_during_read(self, store, output, monkeypatch):
        name = put(store, canonical())
        original = os.fstat
        calls = 0

        def changed(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                (store / name).unlink()
                (store / name).write_text(canonical())
            return original(fd)

        monkeypatch.setattr(backups.os, "fstat", changed)
        row = backups.collect_list(output, backup_dir=store).backups[0]
        assert row.status != "valid"
        assert "changed" in row.detail

    def test_root_symlink_retarget_is_bound(self, store, output, tmp_path, monkeypatch):
        name = put(store, canonical())
        other = tmp_path / "other"
        other.mkdir()
        (other / name).write_text("foreign")
        link = tmp_path / "root"
        link.symlink_to(store)
        original = backups._inspect_backup

        def retarget(root, candidate):
            link.unlink()
            link.symlink_to(other)
            return original(root, candidate)

        monkeypatch.setattr(backups, "_inspect_backup", retarget)
        result = backups.collect_compare(output, name, backup_dir=link)
        assert result.backup.status == "valid"
        assert result.backup.sha256 == name[:-4]

    def test_current_symlink_retarget_detected(self, store, output, tmp_path, monkeypatch):
        name = put(store, canonical())
        first = tmp_path / "one"
        second = tmp_path / "two"
        first.mkdir()
        second.mkdir()
        (first / "attune.lua").write_text(canonical())
        (second / "attune.lua").write_text("foreign")
        output.symlink_to(first / "attune.lua")
        original = backups._read

        def retarget(root, candidate):
            result = original(root, candidate)
            if candidate == "attune.lua":
                output.unlink()
                output.symlink_to(second / "attune.lua")
            return result

        monkeypatch.setattr(backups, "_read", retarget)
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.status == "error"
        assert result.current.status == "unavailable"


class TestComparison:
    def test_equal_and_direction(self, store, output):
        text = canonical({"general:border_size": "2"})
        name = put(store, text)
        output.write_text(text)
        equal = backups.collect_compare(output, name, backup_dir=store)
        assert equal.status == "compared" and equal.diff == ""
        assert equal.added_lines == equal.removed_lines == 0
        output.write_text("foreign\n")
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.current.status == "foreign"
        assert result.added_lines == 1
        assert result.removed_lines == len(text.splitlines())
        assert result.diff.startswith("--- " + name + "\n+++ current/attune.lua\n")
        assert "+foreign\n" in result.diff
        assert result.current.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
        assert backups.BackupComparison.from_json(result.to_json()) == result

    def test_missing_is_empty_not_failed(self, store, output):
        name = put(store, canonical())
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.status == "compared" and result.current.status == "missing"
        assert result.added_lines == 0 and result.removed_lines
        assert not output.exists()

    @pytest.mark.parametrize("kind", ["dangling", "directory", "fifo", "hardlink", "binary"])
    def test_unreadable_current_never_empty(self, store, output, tmp_path, kind):
        name = put(store, canonical())
        if kind == "dangling":
            output.symlink_to(tmp_path / "absent")
        elif kind == "directory":
            output.mkdir()
        elif kind == "fifo":
            os.mkfifo(output)
        elif kind == "hardlink":
            other = tmp_path / "other"
            other.write_text("foreign")
            os.link(other, output)
        else:
            output.write_bytes(b"hello\x00world")
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.status == "error" and result.current.status == "unavailable"
        assert result.removed_lines is None and result.diff == ""

    def test_invalid_current_still_readable(self, store, output):
        name = put(store, canonical())
        output.write_text(persistence.MARKER + "os.execute('never')\n")
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.status == "compared" and result.current.status == "invalid"
        assert "os.execute" in result.diff

    def test_current_symlink_preserved_and_main_alias_rejected(
        self, store, output, tmp_path, monkeypatch
    ):
        name = put(store, canonical())
        directory = tmp_path / "target"
        directory.mkdir()
        target = directory / "attune.lua"
        target.write_text("foreign")
        output.symlink_to(target)
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.current.lexical_path == str(output)
        assert result.current.resolved_path == str(target)
        assert output.is_symlink() and target.read_text() == "foreign"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        main = tmp_path / "hypr"
        main.mkdir()
        (main / "hyprland.lua").symlink_to(target)
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.status == "error" and "main config" in result.current.detail

    def test_rereads_backup_after_listing(self, store, output):
        name = put(store, canonical())
        assert backups.collect_list(output, backup_dir=store).backups[0].status == "valid"
        (store / name).write_text("changed")
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.status == "error" and "SHA256" in result.backup.detail
        (store / name).unlink()
        assert (
            backups.collect_compare(output, name, backup_dir=store).backup.status == "unavailable"
        )

    @pytest.mark.parametrize(
        "name", ["../" + "a" * 64 + ".lua", "A" * 64 + ".lua", "/tmp/a.lua", "a.lua"]
    )
    def test_bad_names_rejected(self, store, output, name):
        with pytest.raises(ValueError, match="basename"):
            backups.collect_compare(output, name, backup_dir=store)
        with pytest.raises(ValueError, match="basename"):
            backups.run_compare(output, name)

    def test_large_input_refused_with_evidence(self, store, output):
        name = put(store, canonical())
        output.write_text("x" * (backups.MAX_COMPARE_BYTES + 1))
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.status == "too_large" and result.current.sha256
        assert result.added_lines is None and not result.diff
        output.write_text("x\n" * 10001)
        assert backups.collect_compare(output, name, backup_dir=store).status == "too_large"

    def test_diff_caps_and_full_counts(self, store, output):
        name = put(store, canonical())
        output.write_text("x\n" * 5000)
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.truncated and result.added_lines == 5000
        assert len(result.diff.splitlines()) <= backups.MAX_DIFF_LINES
        assert "truncated" in result.notes[-1]
        output.write_text("x" * 5000)
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.truncated
        assert max(map(len, result.diff.splitlines())) <= backups.MAX_LINE_BYTES
        output.write_text(("x" * 86 + "\n") * 3000)
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.status == "compared" and result.added_lines == 3000
        assert result.truncated and len(result.diff.encode()) <= backups.MAX_DIFF_BYTES

    def test_oversized_metadata_row_is_not_returned_to_ui(self, store, output):
        text = canonical({"general:border_size": "x" * 5000})
        name = put(store, text)
        output.write_text(canonical())
        result = backups.collect_compare(output, name, backup_dir=store)
        assert result.status == "compared" and result.truncated
        assert result.backup.status == "valid"
        assert max(map(len, result.diff.splitlines())) <= backups.MAX_LINE_BYTES

    def test_crlf_and_no_final_newline(self, store, output):
        name = put(store, canonical())
        output.write_bytes(b"one\r\ntwo")
        result = backups.collect_compare(output, name, backup_dir=store)
        assert "+one\r\n+two\n\\ No newline at end of file\n" in result.diff


class TestProtocolAndWorker:
    def test_real_worker_missing_directory_no_writes(self, output, tmp_path, monkeypatch):
        state = tmp_path / "absent-state"
        monkeypatch.setenv("XDG_STATE_HOME", str(state))
        assert backups.run_list(output).status == "unavailable"
        assert not state.exists() and not output.exists()

    def test_real_workers_configured_folder_only(self, output, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        directory = tmp_path / "attune" / "backups"
        directory.mkdir(parents=True)
        name = put(directory, canonical())
        output.write_text("foreign\n")
        listing = backups.run_list(output)
        assert listing.backups[0].name == name
        # If this were computed in the parent, this patch would fail the operation.
        monkeypatch.setattr(
            backups.difflib, "SequenceMatcher", lambda *a, **kw: pytest.fail("parent diff")
        )
        result = backups.run_compare(output, name)
        assert result.status == "compared" and "+foreign" in result.diff

    def test_supervision_contract(self, output, store, monkeypatch):
        name = put(store, canonical())
        response = backups.collect_compare(output, name, backup_dir=store)
        cancel = threading.Event()

        def run(command, **kwargs):
            assert command[1:5] == ["-I", "-B", "-m", "hyprmod.core.backups"]
            assert command[-2:] == ["compare", name]
            assert "--output" in command
            assert kwargs["process_group"] is True
            assert kwargs["cancel_event"] is cancel
            assert kwargs["timeout"] == 3
            assert kwargs["max_bytes"] == backups.MAX_JSON_BYTES
            return subprocess.CompletedProcess(command, 0, response.to_json(), "")

        monkeypatch.setattr(health, "run_bounded", run)
        assert backups.run_compare(output, name, timeout=3, cancel_event=cancel) == response

    @pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
    def test_invalid_timeout(self, output, timeout):
        with pytest.raises(ValueError, match="timeout"):
            backups.run_list(output, timeout=timeout)

    def test_cancelled_before_spawn(self, output):
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(InterruptedError):
            backups.run_list(output, cancel_event=cancel)

    def test_strict_decoding(self, output, store):
        name = put(store, canonical())
        listing = backups.collect_list(output, backup_dir=store)
        data = json.loads(listing.to_json())
        mutations = [
            {**data, "extra": 1},
            {**data, "notes": "not list"},
            {**data, "status": []},
            {**data, "observed_at": "yesterday"},
            {**data, "backups": data["backups"] * 65},
        ]
        for key, value in [
            ("name", "../bad"),
            ("size_bytes", True),
            ("sha256", "x"),
            ("summary", {"scalars": -1, "monitors": 0, "animations": 0, "beziers": 0}),
        ]:
            row = {**data["backups"][0], key: value}
            mutations.append({**data, "backups": [row]})
        for record in mutations:
            with pytest.raises(ValueError):
                backups.BackupListing.from_json(json.dumps(record))
        for raw in ("[" * 2000, " " * (backups.MAX_JSON_BYTES + 1), '{"x": 1, "x": 2}', "null"):
            with pytest.raises(ValueError):
                backups.BackupListing.from_json(raw)
        comparison = backups.collect_compare(output, name, backup_dir=store)
        bad = replace(comparison, added_lines=True)
        with pytest.raises(ValueError):
            bad.to_json()
        with pytest.raises(ValueError):
            replace(comparison, diff="x" * (backups.MAX_DIFF_BYTES + 1)).to_json()
        with pytest.raises(ValueError):
            replace(comparison, current=replace(comparison.current, status="unavailable")).to_json()
