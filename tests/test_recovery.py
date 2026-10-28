"""Recovery tests use temporary HOME/XDG paths and never launch the application."""

import hashlib
import json
import os
import stat
import subprocess
import threading
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from hyprmod.core import config, health, persistence, recovery, restoration


@pytest.fixture
def files(tmp_path):
    output = tmp_path / "attune.lua"
    output.write_bytes(b"-- authored\r\nnot even valid Lua!\r\n")
    state = Path(os.environ["XDG_STATE_HOME"]) / "attune"
    state.mkdir(parents=True, mode=0o700)
    root = state / "backups"
    root.mkdir(mode=0o700)
    proposed = persistence.build_text({"general:gaps_in": "5"}, config.ConfigSections())
    candidate = root / (hashlib.sha256(proposed.encode()).hexdigest() + ".lua")
    candidate.write_text(proposed)
    return output, candidate


def stage(files):
    return recovery.prepare_recovery(files[0], files[1].name)


class TestPreparation:
    def test_read_only_exact_immutable_draft(self, files):
        draft = stage(files)
        assert draft.current_status == "foreign"
        assert draft.previous_text.encode() == files[0].read_bytes()
        assert draft.diff.startswith("--- current/attune.lua\n+++ " + files[1].name)
        assert recovery.RecoveryDraft.from_json(draft.to_json()) == draft
        assert not Path(draft.preservation_root).exists()
        assert not (files[1].parent.parent / "persistence.lock").exists()
        with pytest.raises(FrozenInstanceError):
            setattr(draft, "diff", "forged")

    @pytest.mark.parametrize("bad", ["{broken JSON", "not base64", "W10="])
    def test_invalid_marker_never_compiled_or_executed(self, files, tmp_path, monkeypatch, bad):
        sentinel = tmp_path / "executed"
        original = persistence.MARKER + persistence.RECORD + bad + "\n"
        original += f'io.open("{sentinel}", "w"):close()\ninvalid Lua!!!'
        files[0].write_text(original)
        validator = persistence.validate_lua
        calls = []

        def compile_candidate(text):
            calls.append(text)
            assert text == files[1].read_text()
            validator(text)

        monkeypatch.setattr(persistence, "validate_lua", compile_candidate)
        draft = stage(files)
        assert draft.current_status == "invalid"
        result = recovery.commit_recovery(draft)
        assert result.preservation_path.read_bytes() == original.encode()
        assert len(calls) >= 2
        assert not sentinel.exists()

    @pytest.mark.parametrize("bad", [b"", b"\xff", b"\0", b"\x7f", b"x" * 262145, b"x\n" * 10001])
    def test_unsupported_text(self, files, bad):
        files[0].write_bytes(bad)
        with pytest.raises((ValueError, OSError)):
            stage(files)
        assert files[0].read_bytes() == bad

    @pytest.mark.parametrize("kind", ["missing", "directory", "fifo", "hardlink", "owned"])
    def test_unsupported_current(self, files, tmp_path, kind):
        files[0].unlink()
        if kind == "directory":
            files[0].mkdir()
        elif kind == "fifo":
            os.mkfifo(files[0])
        elif kind == "hardlink":
            other = tmp_path / "other"
            other.write_text("foreign")
            os.link(other, files[0])
        elif kind == "owned":
            files[0].write_bytes(files[1].read_bytes())
        with pytest.raises((ValueError, OSError)):
            stage(files)

    @pytest.mark.parametrize("name", ["../a.lua", "/tmp/a.lua", "A" * 64 + ".lua", "x"])
    def test_bad_name(self, files, name):
        with pytest.raises(ValueError, match="basename"):
            recovery.run_prepare(files[0], name)

    @pytest.mark.parametrize("bad", ["foreign", "", persistence.MARKER + "invalid"])
    def test_noncanonical_source(self, files, bad):
        files[1].write_text(bad)
        with pytest.raises(ValueError):
            stage(files)

    def test_hash_mismatch(self, files):
        files[1].write_text(persistence.build_text({}, config.ConfigSections()))
        with pytest.raises(ValueError, match="identity"):
            stage(files)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("diff", ""),
            ("added_lines", True),
            ("previous_sha256", "bad"),
            ("current_status", "owned"),
            ("preservation_path", "/tmp/foreign"),
            ("observed_at", "2026-01-01T01:00:00+01:00"),
            ("extra", "x"),
        ],
    )
    def test_protocol_forgery(self, files, field, value):
        data = json.loads(stage(files).to_json())
        data[field] = value
        with pytest.raises(ValueError):
            recovery.RecoveryDraft.from_json(json.dumps(data))

    def test_protocol_limits_duplicates_and_full_diff(self, files, monkeypatch):
        text = stage(files).to_json()
        for bad in ('{"diff":"",' + text[1:], "[" * 2000, " " * (recovery.MAX_JSON_BYTES + 1)):
            with pytest.raises(ValueError):
                recovery.RecoveryDraft.from_json(bad)
        monkeypatch.setattr(restoration, "MAX_DIFF_LINES", 1)
        with pytest.raises(ValueError, match="Complete"):
            stage(files)

    def test_supervised_prepare_only(self, files, monkeypatch):
        draft = recovery.run_prepare(files[0], files[1].name)
        assert not Path(draft.preservation_root).exists()
        seen = []

        def bounded(command, **kwargs):
            seen.extend(command)
            assert kwargs["max_bytes"] == recovery.MAX_JSON_BYTES
            assert kwargs["process_group"]
            return subprocess.CompletedProcess(command, 0, stdout=draft.to_json())

        monkeypatch.setattr(health, "run_bounded", bounded)
        assert recovery.run_prepare(files[0], files[1].name) == draft
        assert "prepare" in seen and "commit" not in seen

    @pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
    def test_finite_supervisor(self, files, timeout):
        with pytest.raises(ValueError, match="finite"):
            recovery.run_prepare(files[0], files[1].name, timeout=timeout)


class TestCommit:
    @pytest.mark.parametrize("link", ["none", "file", "parent"])
    def test_preserve_then_replace_private_exact_bytes(self, files, tmp_path, monkeypatch, link):
        path = files[0]
        directory = tmp_path / "linked"
        if link == "file":
            directory.mkdir()
            path = directory / "attune.lua"
            path.symlink_to(files[0])
        elif link == "parent":
            directory.symlink_to(files[0].parent)
            path = directory / "attune.lua"
        draft = recovery.prepare_recovery(path, files[1].name)
        real = os.replace
        real_fsync = os.fsync
        synced = []

        def fsync(fd):
            synced.append(os.readlink(f"/proc/self/fd/{fd}"))
            real_fsync(fd)

        def replace_output(source, target):
            assert Path(draft.preservation_path).read_bytes() == draft.previous_text.encode()
            assert draft.preservation_path in synced
            assert draft.preservation_root in synced
            real(source, target)

        monkeypatch.setattr(persistence.os, "fsync", fsync)
        monkeypatch.setattr(persistence.os, "replace", replace_output)
        invalidate = Mock()
        monkeypatch.setattr(config, "invalidate_cache", invalidate)
        result = recovery.commit_recovery(draft)
        assert result.status == "recovered"
        assert result.resolved_path == files[0]
        assert result.preservation_path.read_bytes() == draft.previous_text.encode()
        assert stat.S_IMODE(result.preservation_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(result.preservation_path.parent.stat().st_mode) == 0o700
        assert files[0].read_bytes() == files[1].read_bytes()
        assert list(files[1].parent.iterdir()) == [files[1]]
        invalidate.assert_called_once()
        if link != "none":
            assert (path if link == "file" else directory).is_symlink()
        with pytest.raises(ValueError):
            restoration.prepare_restore(path, result.preservation_path.name)
        with pytest.raises(ValueError, match="ordinary restoration"):
            recovery.prepare_recovery(path, files[1].name)

    @pytest.mark.parametrize("kind", ["foreign", "symlink", "hardlink", "directory", "public"])
    def test_preserved_collision_refused_even_identical_unsafe(self, files, tmp_path, kind):
        draft = stage(files)
        path = Path(draft.preservation_path)
        path.parent.mkdir(mode=0o700)
        other = tmp_path / "other"
        other.write_bytes(draft.previous_text.encode())
        other.chmod(0o600)
        if kind == "foreign":
            path.write_bytes(b"collision")
            path.chmod(0o600)
        elif kind == "symlink":
            path.symlink_to(other)
        elif kind == "hardlink":
            os.link(other, path)
        elif kind == "directory":
            path.mkdir(mode=0o600)
        else:
            path.write_bytes(draft.previous_text.encode())
            path.chmod(0o644)
        with pytest.raises(recovery.RecoveryFailure) as error:
            recovery.commit_recovery(draft)
        assert not error.value.may_have_written
        assert files[0].read_bytes() == draft.previous_text.encode()

    def test_safe_existing_evidence_reused(self, files):
        draft = stage(files)
        path = Path(draft.preservation_path)
        path.parent.mkdir(mode=0o700)
        path.write_bytes(draft.previous_text.encode())
        path.chmod(0o600)
        inode = path.stat().st_ino
        recovery.commit_recovery(draft)
        assert path.stat().st_ino == inode

    def test_exclusive_collision_never_clobbered(self, files, monkeypatch):
        draft = stage(files)
        real_open = os.open

        def collide(path, flags, *args, **kwargs):
            if str(path) == draft.preservation_path and flags & os.O_EXCL:
                Path(path).write_bytes(b"foreign collision")
                Path(path).chmod(0o600)
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(persistence.os, "open", collide)
        with pytest.raises(recovery.RecoveryFailure) as error:
            recovery.commit_recovery(draft)
        assert not error.value.may_have_written
        assert Path(draft.preservation_path).read_bytes() == b"foreign collision"
        assert files[0].read_bytes() == draft.previous_text.encode()

    def test_public_app_directory_refused_without_chmod(self, files):
        state = files[1].parent.parent
        state.chmod(0o755)
        with pytest.raises(ValueError, match="private"):
            stage(files)
        assert stat.S_IMODE(state.stat().st_mode) == 0o755

    def test_preservation_permissions_changed_during_read_refused(self, files, monkeypatch):
        draft = stage(files)
        real_read = persistence.read_stable

        def read(path, **kwargs):
            raw = real_read(path, **kwargs)
            if str(path) == draft.preservation_path:
                path.chmod(0o644)
            return raw

        monkeypatch.setattr(persistence, "read_stable", read)
        with pytest.raises(recovery.RecoveryFailure) as error:
            recovery.commit_recovery(draft)
        assert not error.value.may_have_written
        assert files[0].read_bytes() == draft.previous_text.encode()

    @pytest.mark.parametrize("kind", ["public", "symlink", "git"])
    def test_insecure_storage_refused_no_chmod(self, files, tmp_path, kind):
        draft = stage(files)
        root = Path(draft.preservation_root)
        if kind == "public":
            root.mkdir(mode=0o755)
        elif kind == "symlink":
            other = tmp_path / "other"
            other.mkdir(mode=0o700)
            root.symlink_to(other)
        else:
            (tmp_path / ".git").mkdir()
        with pytest.raises(recovery.RecoveryFailure):
            recovery.commit_recovery(draft)
        assert files[0].read_bytes() == draft.previous_text.encode()
        if kind == "public":
            assert stat.S_IMODE(root.stat().st_mode) == 0o755

    @pytest.mark.parametrize("change", ["current", "source", "target", "backup_root", "state_root"])
    @pytest.mark.parametrize("when", ["before", "lock", "preserved", "staged"])
    def test_bindings_rechecked(self, files, tmp_path, monkeypatch, change, when):
        draft = stage(files)

        def mutate():
            if change == "current":
                files[0].write_text("changed")
            elif change == "source":
                files[1].write_text("changed")
            elif change == "target":
                other = tmp_path / "other/attune.lua"
                other.parent.mkdir()
                other.write_bytes(draft.previous_text.encode())
                files[0].unlink()
                files[0].symlink_to(other)
            elif change == "backup_root":
                root = files[1].parent
                moved = root.with_name("moved")
                root.rename(moved)
                root.symlink_to(moved)
            else:
                monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "new-state"))

        if when == "before":
            mutate()
        elif when == "lock":
            real = persistence.fcntl.flock

            def lock(fd, operation):
                real(fd, operation)
                mutate()

            monkeypatch.setattr(persistence.fcntl, "flock", lock)
        else:
            real_fsync = os.fsync
            changed = False

            def fsync(fd):
                nonlocal changed
                real_fsync(fd)
                name = os.readlink(f"/proc/self/fd/{fd}")
                trigger = (
                    name == draft.preservation_path
                    if when == "preserved"
                    else (Path(name).name.startswith(".attune-"))
                )
                if trigger and not changed:
                    changed = True
                    mutate()

            monkeypatch.setattr(persistence.os, "fsync", fsync)
        with pytest.raises(recovery.RecoveryFailure) as error:
            recovery.commit_recovery(draft)
        assert not error.value.may_have_written
        assert files[0].read_bytes() != draft.proposed_text.encode()

    @pytest.mark.parametrize("failure", ["file_fsync", "dir_fsync", "read"])
    def test_preservation_failure_prevents_replace(self, files, monkeypatch, failure):
        draft = stage(files)
        real_fsync = os.fsync
        real_read = persistence.read_stable

        def fsync(fd):
            name = os.readlink(f"/proc/self/fd/{fd}")
            if name == (
                draft.preservation_path if failure == "file_fsync" else draft.preservation_root
            ):
                raise OSError("preservation fsync failed")
            real_fsync(fd)

        def read(path, **kwargs):
            if str(path) == draft.preservation_path:
                raise OSError("preservation read failed")
            return real_read(path, **kwargs)

        if failure == "read":
            monkeypatch.setattr(persistence, "read_stable", read)
        else:
            monkeypatch.setattr(persistence.os, "fsync", fsync)
        with pytest.raises(recovery.RecoveryFailure) as error:
            recovery.commit_recovery(draft)
        assert not error.value.may_have_written
        assert "configuration not replaced" in str(error.value)
        assert files[0].read_bytes() == draft.previous_text.encode()

    @pytest.mark.parametrize("when", ["before", "lock", "preserved", "after"])
    def test_cancel(self, files, monkeypatch, when):
        draft = stage(files)
        event = threading.Event()
        if when == "before":
            event.set()
        elif when == "lock":
            real_lock = persistence.fcntl.flock

            def lock(fd, operation):
                real_lock(fd, operation)
                event.set()

            monkeypatch.setattr(persistence.fcntl, "flock", lock)
        elif when == "preserved":
            real_fsync = os.fsync

            def fsync(fd):
                real_fsync(fd)
                if os.readlink(f"/proc/self/fd/{fd}") == draft.preservation_path:
                    event.set()

            monkeypatch.setattr(persistence.os, "fsync", fsync)
        else:
            real_replace = os.replace

            def replace_output(source, target):
                real_replace(source, target)
                event.set()

            monkeypatch.setattr(persistence.os, "replace", replace_output)
        if when == "after":
            assert recovery.commit_recovery(draft, cancel_event=event).status == "recovered"
        else:
            with pytest.raises(recovery.RecoveryFailure) as error:
                recovery.commit_recovery(draft, cancel_event=event)
            assert not error.value.may_have_written
            assert files[0].read_bytes() == draft.previous_text.encode()

    def test_lock_timeout(self, files, monkeypatch):
        draft = stage(files)
        ticks = iter([0, 6])
        monkeypatch.setattr(persistence.time, "monotonic", lambda: next(ticks))
        monkeypatch.setattr(persistence.fcntl, "flock", Mock(side_effect=BlockingIOError))
        with pytest.raises(recovery.RecoveryFailure, match="timed out") as error:
            recovery.commit_recovery(draft)
        assert not error.value.may_have_written
        assert not Path(draft.preservation_path).exists()

    def test_cancel_waiting_for_lock(self, files, monkeypatch):
        draft = stage(files)
        event = threading.Event()

        def busy(*args):
            event.set()
            raise BlockingIOError()

        monkeypatch.setattr(persistence.fcntl, "flock", busy)
        with pytest.raises(recovery.RecoveryFailure, match="cancelled") as error:
            recovery.commit_recovery(draft, cancel_event=event)
        assert not error.value.may_have_written
        assert not Path(draft.preservation_path).exists()

    def test_postreplace_directory_fsync_failure_is_uncertain(self, files, monkeypatch):
        draft = stage(files)
        real_fsync = os.fsync

        def fsync(fd):
            if os.readlink(f"/proc/self/fd/{fd}") == str(files[0].parent):
                raise OSError("output directory fsync failed")
            real_fsync(fd)

        monkeypatch.setattr(persistence.os, "fsync", fsync)
        invalidate = Mock()
        monkeypatch.setattr(config, "invalidate_cache", invalidate)
        with pytest.raises(recovery.RecoveryFailure) as error:
            recovery.commit_recovery(draft)
        assert error.value.may_have_written
        assert files[0].read_bytes() == draft.proposed_text.encode()
        assert Path(draft.preservation_path).read_bytes() == draft.previous_text.encode()
        invalidate.assert_called_once()

    @pytest.mark.parametrize("after", [False, True])
    def test_uncertain_replacement_invalidates_cache(self, files, monkeypatch, after):
        draft = stage(files)
        real = os.replace

        def fail(source, target):
            if after:
                real(source, target)
            raise OSError("replace failed")

        monkeypatch.setattr(persistence.os, "replace", fail)
        invalidate = Mock()
        monkeypatch.setattr(config, "invalidate_cache", invalidate)
        with pytest.raises(recovery.RecoveryFailure) as error:
            recovery.commit_recovery(draft)
        assert error.value.may_have_written
        invalidate.assert_called_once()
        assert Path(draft.preservation_path).read_bytes() == draft.previous_text.encode()
        assert (
            files[0].read_bytes()
            == (draft.proposed_text if after else draft.previous_text).encode()
        )

    def test_no_validator_and_forged_draft_fail_closed(self, files, monkeypatch):
        draft = stage(files)
        with pytest.raises(recovery.RecoveryFailure):
            recovery.commit_recovery(replace(draft, previous_sha256="bad"))
        monkeypatch.setattr(persistence.shutil, "which", lambda _: None)
        with pytest.raises(recovery.RecoveryFailure):
            recovery.commit_recovery(draft)
        assert files[0].read_bytes() == draft.previous_text.encode()
        assert not Path(draft.preservation_path).exists()

    def test_no_ipc_or_executing_reader(self, files, monkeypatch):
        draft = stage(files)
        forbidden = Mock(side_effect=AssertionError("No IPC, reload or evaluating reader"))
        monkeypatch.setattr(config, "load_any", forbidden)
        monkeypatch.setattr(health, "run_bounded", forbidden)
        recovery.commit_recovery(draft)
        forbidden.assert_not_called()

    def test_main_config_alias_is_never_recovered(self, files):
        main = Path(os.environ["XDG_CONFIG_HOME"]) / "hypr/hyprland.lua"
        main.parent.mkdir()
        main.symlink_to(files[0])
        with pytest.raises(ValueError, match="main config"):
            stage(files)
