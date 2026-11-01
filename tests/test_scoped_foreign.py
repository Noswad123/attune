"""Foreign CURRENT diagnostics use only temporary HOME/XDG and explicit fixtures."""

import base64
import builtins
import fcntl
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest

from hyprmod.core import (
    health,
    persistence,
    route_approval,
    scoped_config,
    transaction_publication,
    transaction_store,
)
from hyprmod.core import scoped_foreign as foreign
from hyprmod.core.scopes import Scope
from tests.test_route_approval import Layout
from tests.test_route_approval import layout as layout


@pytest.fixture(params=tuple(Scope))
def selected_scope(request) -> Scope:
    return request.param


@pytest.fixture
def foreign_pair(layout: Layout, selected_scope: Scope) -> Layout:
    path: Path = getattr(layout, selected_scope.value)
    path.write_bytes(b'-- authored\r\n\tprint("not executed")')
    return layout


def _rehash(data: dict) -> str:
    payload = data["observation"].copy()
    del payload["observed_at"]
    data["observation_hash"] = hashlib.sha256(
        route_approval._json(payload).encode("ascii")
    ).hexdigest()
    return route_approval._json(data)


class TestObservation:
    def test_exact_roundtrip_and_no_canonical_selected_identity(
        self, foreign_pair: Layout, selected_scope: Scope
    ):
        pair = foreign_pair
        path: Path = getattr(pair, selected_scope.value)
        raw = path.read_bytes()
        before = (raw, path.stat(), pair.registry.read_bytes())
        result = foreign.observe_current(pair.config, pair.state, selected_scope)
        assert result.selected.status == "foreign"
        assert result.selected.scope is selected_scope
        assert result.selected.text.encode() == raw
        assert result.selected.file.source_sha256 == hashlib.sha256(raw).hexdigest()
        assert set(asdict(result.selected)) == {"scope", "file", "status", "text"}
        assert not hasattr(result.selected, "content_id")
        assert not hasattr(result.selected, "counts")
        assert result.sibling.route.scope is not selected_scope
        assert foreign.ScopedForeignObservation.from_json(result.to_json()) == result
        assert foreign.revalidate_current(result).observation_hash == result.observation_hash
        assert replace(result, observed_at="2000-01-01T00:00:00Z").observation_hash == (
            result.observation_hash
        )
        assert (path.read_bytes(), path.stat(), pair.registry.read_bytes()) == before
        assert not pair.state.exists()
        with pytest.raises(FrozenInstanceError):
            setattr(result.selected, "status", "invalid-scoped")
        assert not hasattr(result, "__dict__")

    @pytest.mark.parametrize(
        "text",
        [
            persistence.MARKER,
            persistence.MARKER + persistence.RECORD + "invalid base64\n",
            persistence.MARKER + scoped_config.RECORD + "!!!!\n",
            persistence.MARKER + scoped_config.RECORD + "e30=\n",
            persistence.MARKER + "-- damaged body without record",
        ],
    )
    def test_damaged_owned_text(self, layout: Layout, selected_scope: Scope, text: str):
        path: Path = getattr(layout, selected_scope.value)
        path.write_bytes(text.encode())
        result = foreign.observe_current(layout.config, layout.state, selected_scope)
        assert result.selected.status == "invalid-scoped"
        assert result.selected.text == text
        assert result.selected.file.source_sha256 == hashlib.sha256(text.encode()).hexdigest()

    @pytest.mark.parametrize("kind", ["v1-body", "v2-body", "v2-id", "v2-payload", "v2-json"])
    def test_damaged_records_are_raw_not_claimed_ids(
        self, layout: Layout, selected_scope: Scope, kind: str
    ):
        path: Path = getattr(layout, selected_scope.value)
        text = path.read_text()
        if kind == "v1-body":
            text = persistence._render({}, {}) + "-- edited\n"
        elif kind == "v2-body":
            text += "os.execute('not executed')\n"
        else:
            if kind == "v2-json":
                encoded = base64.b64encode(b"not json").decode()
            else:
                record = json.loads(
                    base64.b64decode(text.splitlines()[1][len(scoped_config.RECORD) :])
                )
                if kind == "v2-id":
                    record["content_id"] = "a" * 64
                else:
                    record["payload"] = {"not": "valid"}
                encoded = base64.b64encode(json.dumps(record).encode()).decode()
            text = persistence.MARKER + scoped_config.RECORD + encoded + "\n"
        path.write_bytes(text.encode())
        result = foreign.observe_current(layout.config, layout.state, selected_scope)
        assert result.selected.status == "invalid-scoped"
        assert result.selected.file.source_sha256 == hashlib.sha256(text.encode()).hexdigest()

    @pytest.mark.parametrize(
        "raw",
        [
            b"a\r\nb\r\n",
            b"a\rb",
            b"\t\n",
            b"a",
            b"\xef\xbb\xbfa",
            "-- \u00e9 \u0065\u0301 \U0001f680".encode(),
            persistence.MARKER.replace("\n", "\r\n").encode() + b"damaged",
            b" -- Generated by Attune\n",
        ],
    )
    def test_no_newline_bom_or_unicode_normalization(
        self, layout: Layout, selected_scope: Scope, raw: bytes
    ):
        path: Path = getattr(layout, selected_scope.value)
        path.write_bytes(raw)
        result = foreign.observe_current(layout.config, layout.state, selected_scope)
        assert result.selected.status == "foreign"
        assert result.selected.text.encode() == raw
        assert (
            foreign.ScopedForeignObservation.from_json(result.to_json()).selected.text.encode()
            == raw
        )

    @pytest.mark.parametrize("kind", ["same", "other", "v1"])
    def test_canonical_selected_is_never_foreign(
        self, layout: Layout, selected_scope: Scope, kind: str
    ):
        path: Path = getattr(layout, selected_scope.value)
        if kind == "other":
            other = next(s for s in Scope if s is not selected_scope)
            path.write_bytes(getattr(layout, other.value).read_bytes())
        elif kind == "v1":
            path.write_text(persistence._render({}, {}))
        message = {"same": "canonical restore", "other": "another scope", "v1": "conversion"}[kind]
        with pytest.raises(route_approval.ApprovalError, match=message):
            foreign.observe_current(layout.config, layout.state, selected_scope)

    @pytest.mark.parametrize("kind", ["v1", "wrong-scope", "foreign", "damaged", "v3"])
    def test_sibling_must_be_correct_canonical_v2(
        self, foreign_pair: Layout, selected_scope: Scope, kind: str
    ):
        other = next(s for s in Scope if s is not selected_scope)
        path: Path = getattr(foreign_pair, other.value)
        if kind == "v1":
            raw = persistence._render({}, {}).encode()
        elif kind == "wrong-scope":
            raw = scoped_config.build_text(
                scoped_config.ScopedConfig(
                    selected_scope,
                    {"values": {}, "beziers": [], "animations": []}
                    if selected_scope is Scope.APPEARANCE
                    else {"monitors": []},
                )
            ).encode()
        elif kind == "damaged":
            raw = path.read_bytes() + b"-- edit\n"
        elif kind == "v3":
            raw = path.read_bytes().replace(b"data v2", b"data v3")
        else:
            raw = b"authored sibling"
        path.write_bytes(raw)
        with pytest.raises(route_approval.ApprovalError):
            foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)

    @pytest.mark.parametrize("version", ["0", "3", "99", "-1", "future"])
    @pytest.mark.parametrize("prefix", [persistence.MARKER, "-- Generated by Attune\r\n", ""])
    def test_unknown_record_prefix_is_refused(
        self, layout: Layout, selected_scope: Scope, version: str, prefix: str
    ):
        path: Path = getattr(layout, selected_scope.value)
        path.write_text(prefix + f"-- Attune data v{version}: broken\nos.execute('never')\n")
        with pytest.raises(route_approval.ApprovalError, match="Unsupported"):
            foreign.observe_current(layout.config, layout.state, selected_scope)

    @pytest.mark.parametrize("prefix", [persistence.RECORD, scoped_config.RECORD])
    def test_unknown_embedded_record_version_is_refused(
        self, layout: Layout, selected_scope: Scope, prefix: str
    ):
        path: Path = getattr(layout, selected_scope.value)
        record = base64.b64encode(b'{"version":3}').decode()
        path.write_text(persistence.MARKER + prefix + record + "\n")
        with pytest.raises(route_approval.ApprovalError, match="Unsupported"):
            foreign.observe_current(layout.config, layout.state, selected_scope)

    @pytest.mark.parametrize("leading", ["-- authored comment\r\n", "\n", "\ufeff"])
    @pytest.mark.parametrize("marker", ["", persistence.MARKER])
    @pytest.mark.parametrize("indent", ["", " \t", " \t\ufeff\t"])
    @pytest.mark.parametrize("version", ["3", "1", "2"])
    def test_embedded_future_version_refuses_independent_of_file_prefix(
        self,
        layout: Layout,
        selected_scope: Scope,
        leading: str,
        marker: str,
        indent: str,
        version: str,
    ):
        encoded = base64.b64encode(b'{"version":3}').decode()
        record = f"-- Attune data v{version}: {encoded}\r\n"
        raw = (leading + marker + indent + record + "os.execute('never')").encode()
        path: Path = getattr(layout, selected_scope.value)
        path.write_bytes(raw)
        with pytest.raises(route_approval.ApprovalError, match="Unsupported Attune record version"):
            foreign.observe_current(layout.config, layout.state, selected_scope)
        assert path.read_bytes() == raw

    @pytest.mark.parametrize("leading", ["-- authored comment\r\n", "\n", "\ufeff"])
    @pytest.mark.parametrize("marker", ["", persistence.MARKER])
    @pytest.mark.parametrize("version", [None, 1, 2])
    def test_foreign_without_unsupported_record_preserves_exact_bytes(
        self, layout: Layout, selected_scope: Scope, leading: str, marker: str, version: int | None
    ):
        text = leading + marker + "-- ordinary authored content\r\n"
        if version is not None:
            encoded = base64.b64encode(json.dumps({"version": version}).encode()).decode()
            text += f" \t\ufeff\t-- Attune data v{version}: {encoded}\r\n"
        raw = (text + "\tprint('not executed')").encode()
        path: Path = getattr(layout, selected_scope.value)
        path.write_bytes(raw)
        result = foreign.observe_current(layout.config, layout.state, selected_scope)
        assert result.selected.status == "foreign"
        assert result.selected.text.encode() == raw
        assert result.selected.file.source_sha256 == hashlib.sha256(raw).hexdigest()
        assert path.read_bytes() == raw

    @pytest.mark.parametrize("leading", ["", "\ufeff", " \t", "-- authored\n", "\n"])
    def test_header_tolerance_does_not_normalize_ownership_classification(
        self, layout: Layout, selected_scope: Scope, leading: str
    ):
        text = leading + persistence.MARKER + " \t\ufeff\t-- Attune data v2: e30=\r\n"
        raw = text.encode()
        path: Path = getattr(layout, selected_scope.value)
        path.write_bytes(raw)
        result = foreign.observe_current(layout.config, layout.state, selected_scope)
        assert result.selected.status == ("foreign" if leading else "invalid-scoped")
        assert result.selected.text.encode() == raw
        assert result.selected.file.source_sha256 == hashlib.sha256(raw).hexdigest()

    @pytest.mark.parametrize("record", ["-- Attune data v3", "-- Attune data v3 broken"])
    def test_unknown_version_cannot_hide_behind_missing_colon(
        self, layout: Layout, selected_scope: Scope, record: str
    ):
        path: Path = getattr(layout, selected_scope.value)
        path.write_text(persistence.MARKER + record)
        with pytest.raises(route_approval.ApprovalError, match="Unsupported"):
            foreign.observe_current(layout.config, layout.state, selected_scope)

    @pytest.mark.parametrize(
        "raw",
        [b"", b"\xff", b"\xed\xa0\x80", b"x" * (foreign.MAX_INPUT_BYTES + 1), b"x\n" * 10001],
    )
    def test_selected_bounds_and_invalid_utf8(
        self, layout: Layout, selected_scope: Scope, raw: bytes
    ):
        path: Path = getattr(layout, selected_scope.value)
        path.write_bytes(raw)
        with pytest.raises(route_approval.ApprovalError):
            foreign.observe_current(layout.config, layout.state, selected_scope)

    @pytest.mark.parametrize("code", [*range(0, 9), 11, 12, *range(14, 32), *range(127, 160)])
    def test_controls_rejected(self, layout: Layout, selected_scope: Scope, code: int):
        path: Path = getattr(layout, selected_scope.value)
        path.write_bytes(("a" + chr(code)).encode())
        with pytest.raises(route_approval.ApprovalError, match="control"):
            foreign.observe_current(layout.config, layout.state, selected_scope)

    @pytest.mark.parametrize("raw", [b"x" * foreign.MAX_INPUT_BYTES, b"x\n" * 10000])
    def test_explicit_one_mib_and_line_boundary(
        self, layout: Layout, selected_scope: Scope, raw: bytes
    ):
        path: Path = getattr(layout, selected_scope.value)
        path.write_bytes(raw)
        result = foreign.observe_current(layout.config, layout.state, selected_scope)
        assert result.selected.text.encode() == raw


class TestFilesystemPolicy:
    def test_unsafe_state_metadata_not_exempted(self, foreign_pair: Layout, selected_scope: Scope):
        foreign_pair.state.mkdir(mode=0o700)
        foreign_pair.state.chmod(0o777)
        try:
            with pytest.raises(route_approval.ApprovalError, match="Unsafe dependent"):
                foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)
        finally:
            foreign_pair.state.chmod(0o700)

    @pytest.mark.parametrize("which", ["registry", "appearance", "displays"])
    @pytest.mark.parametrize(
        "kind", ["missing", "hardlink", "fifo", "directory", "dangling", "cycle"]
    )
    def test_objects_fail_without_content_reads(
        self,
        foreign_pair: Layout,
        selected_scope: Scope,
        which: str,
        kind: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        path: Path = getattr(foreign_pair, which)
        if kind == "hardlink":
            os.link(path, tmp_path / "hardlink")
        else:
            path.unlink()
            if kind == "fifo":
                os.mkfifo(path)
            elif kind == "directory":
                path.mkdir()
            elif kind == "dangling":
                path.symlink_to(tmp_path / "absent")
            elif kind == "cycle":
                path.symlink_to(path)
        original = os.open

        def guarded(path_arg, flags, *args, **kwargs):
            assert Path(path_arg) != path
            return original(path_arg, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", guarded)
        with pytest.raises(route_approval.ApprovalError):
            foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)

    @pytest.mark.parametrize("which", ["registry", "appearance", "displays"])
    @pytest.mark.parametrize("mode", [0o444, 0o200, 0o666, 0o755, 0o1644])
    def test_modes_before_content(
        self,
        foreign_pair: Layout,
        selected_scope: Scope,
        which: str,
        mode: int,
        monkeypatch: pytest.MonkeyPatch,
    ):
        path: Path = getattr(foreign_pair, which)
        original_mode = path.stat().st_mode & 0o7777
        original = os.open

        def guarded(path_arg, flags, *args, **kwargs):
            assert Path(path_arg) != path
            return original(path_arg, flags, *args, **kwargs)

        path.chmod(mode)
        monkeypatch.setattr(os, "open", guarded)
        try:
            with pytest.raises(route_approval.ApprovalError):
                foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)
        finally:
            path.chmod(original_mode)

    @pytest.mark.parametrize("which", ["registry", "appearance", "displays"])
    def test_unowned_file_before_content(
        self,
        foreign_pair: Layout,
        selected_scope: Scope,
        which: str,
        monkeypatch: pytest.MonkeyPatch,
    ):
        path: Path = getattr(foreign_pair, which)
        original_fact = route_approval._fact
        original_open = os.open

        def unowned(candidate):
            fact = original_fact(candidate)
            if candidate == path:
                numbers = list(fact.identity)
                numbers[3] = os.getuid() + 1
                return replace(fact, identity=tuple(numbers))
            return fact

        def guarded(candidate, flags, *args, **kwargs):
            assert Path(candidate) != path
            return original_open(candidate, flags, *args, **kwargs)

        monkeypatch.setattr(route_approval, "_fact", unowned)
        monkeypatch.setattr(os, "open", guarded)
        with pytest.raises(route_approval.ApprovalError):
            foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)

    @pytest.mark.parametrize("which", ["registry", "displays"])
    @pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
    def test_git_before_content(
        self,
        foreign_pair: Layout,
        selected_scope: Scope,
        which: str,
        kind: str,
        monkeypatch: pytest.MonkeyPatch,
    ):
        path: Path = getattr(foreign_pair, which)
        marker = path.parent / ".git"
        if kind == "directory":
            marker.mkdir()
        elif kind == "file":
            marker.write_text("gitdir: /must/not/read")
        else:
            marker.symlink_to("absent")
        original = os.open

        def guarded(candidate, flags, *args, **kwargs):
            assert Path(candidate) != path
            return original(candidate, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", guarded)
        with pytest.raises(route_approval.ApprovalError, match="Git"):
            foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)

    @pytest.mark.parametrize("name", ["hyprland.lua", "hyprland.conf", "attune.lua"])
    def test_protected_alias_before_scoped_content(
        self,
        foreign_pair: Layout,
        selected_scope: Scope,
        name: str,
        monkeypatch: pytest.MonkeyPatch,
    ):
        path: Path = getattr(foreign_pair, selected_scope.value)
        (foreign_pair.config / "hypr" / name).symlink_to(path)
        original = os.open

        def guarded(candidate, flags, *args, **kwargs):
            assert Path(candidate) not in (foreign_pair.appearance, foreign_pair.displays)
            return original(candidate, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", guarded)
        with pytest.raises(route_approval.ApprovalError, match="collide|alias"):
            foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)

    @pytest.mark.parametrize("parent_link", [False, True])
    def test_stow_appearance_git_links_preserved(
        self, foreign_pair: Layout, selected_scope: Scope, parent_link: bool, tmp_path: Path
    ):
        repo = tmp_path / "dotfiles"
        repo.mkdir()
        (repo / ".git").mkdir()
        target = repo / foreign_pair.appearance.name
        foreign_pair.appearance.rename(target)
        if parent_link:
            foreign_pair.appearance.parent.rmdir()
            foreign_pair.appearance.parent.symlink_to(repo, target_is_directory=True)
            link = foreign_pair.appearance.parent
        else:
            foreign_pair.appearance.symlink_to(target)
            link = foreign_pair.appearance
        foreign_pair.declare()
        before = (link.lstat(), os.readlink(link), target.read_bytes(), target.stat())
        result = foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)
        foreign.revalidate_current(result)
        assert (link.lstat(), os.readlink(link), target.read_bytes(), target.stat()) == before

    @pytest.mark.parametrize("journal", [b"corrupt", b'{"phase":"PREPARED"}'])
    def test_journal_presence_not_scanned_and_no_live_effects(
        self,
        foreign_pair: Layout,
        selected_scope: Scope,
        journal: bytes,
        monkeypatch: pytest.MonkeyPatch,
    ):
        transactions = foreign_pair.state / "attune/transactions" / ("1" * 32)
        transactions.mkdir(parents=True)
        record = transactions / "intent.json"
        record.write_bytes(journal)
        main = foreign_pair.config / "hypr/hyprland.lua"
        main.write_text("os.execute('must not read or execute')")
        original_open = os.open
        original_io = io.open
        allowed = {foreign_pair.registry, foreign_pair.appearance, foreign_pair.displays}

        def guarded(candidate, flags, *args, **kwargs):
            assert Path(candidate) in allowed
            assert flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) == 0
            return original_open(candidate, flags, *args, **kwargs)

        def descriptors_only(candidate, *args, **kwargs):
            assert isinstance(candidate, int)
            return original_io(candidate, *args, **kwargs)

        def forbidden(*args, **kwargs):
            pytest.fail("Unexpected write, journal scan, Lua/IPC, or high-level read")

        with monkeypatch.context() as patch:
            patch.setattr(os, "open", guarded)
            patch.setattr(io, "open", descriptors_only)
            for obj, name in (
                (builtins, "open"),
                (os, "mkdir"),
                (os, "chmod"),
                (os, "replace"),
                (os, "scandir"),
                (fcntl, "flock"),
                (subprocess, "Popen"),
                (socket, "socket"),
                (persistence, "validate_lua"),
                (persistence, "_preserve"),
                (transaction_store, "initialize_store"),
                (transaction_store, "refuse_pending_readonly"),
                (transaction_store, "list_transaction_ids"),
                (transaction_store, "exclusive_store_session"),
                (transaction_publication, "publish_reviewed"),
            ):
                patch.setattr(obj, name, forbidden)
            result = foreign.observe_current(
                foreign_pair.config, foreign_pair.state, selected_scope
            )
            foreign.revalidate_current(result)
        assert record.read_bytes() == journal
        assert tuple(transactions.iterdir()) == (record,)


class TestDrift:
    @pytest.mark.parametrize(
        "kind",
        [
            "registry",
            "selected",
            "sibling",
            "protected",
            "state",
            "git",
            "display-git",
            "canonical",
        ],
    )
    @pytest.mark.parametrize("when", ["revalidate", "collection", "parse", "post-read"])
    def test_dependency_drift_refused(
        self,
        foreign_pair: Layout,
        selected_scope: Scope,
        kind: str,
        when: str,
        monkeypatch: pytest.MonkeyPatch,
    ):
        pair = foreign_pair
        selected: Path = getattr(pair, selected_scope.value)
        other = next(s for s in Scope if s is not selected_scope)
        sibling: Path = getattr(pair, other.value)

        def mutate():
            if kind == "registry":
                pair.registry.write_bytes(pair.registry.read_bytes() + b"\n")
            elif kind == "selected":
                selected.write_bytes(selected.read_bytes() + b"-- edit")
            elif kind == "sibling":
                sibling.chmod(0o640)
            elif kind == "protected":
                (pair.config / "hypr/hyprland.lua").write_text("not read")
            elif kind == "state":
                (pair.state / "attune").mkdir(parents=True)
            elif kind == "git":
                (pair.appearance.parent / ".git").mkdir()
            elif kind == "display-git":
                (pair.displays.parent / ".git").mkdir()
            elif kind == "canonical":
                selected.write_text(
                    scoped_config.build_text(
                        scoped_config.ScopedConfig(
                            selected_scope,
                            {"values": {}, "beziers": [], "animations": []}
                            if selected_scope is Scope.APPEARANCE
                            else {"monitors": []},
                        )
                    )
                )

        if when == "revalidate":
            result = foreign.observe_current(pair.config, pair.state, selected_scope)
            mutate()
            with pytest.raises(route_approval.ApprovalError):
                foreign.revalidate_current(result)
            return
        changed = False
        if when == "collection":
            original = route_approval._read_file

            def racing_read(path, **kwargs):
                nonlocal changed
                result = original(path, **kwargs)
                if path == pair.displays and not changed:
                    changed = True
                    mutate()
                return result

            monkeypatch.setattr(route_approval, "_read_file", racing_read)
        elif when == "parse":
            original_parse = scoped_config.read_document

            def racing_parse(text, **kwargs):
                nonlocal changed
                try:
                    return original_parse(text, **kwargs)
                finally:
                    if not changed:
                        changed = True
                        mutate()

            monkeypatch.setattr(scoped_config, "read_document", racing_parse)
        else:
            original_fdopen = os.fdopen
            reads = 0

            class RacingStream:
                def __init__(self, stream):
                    self.stream = stream

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    self.stream.close()

                def fileno(self):
                    return self.stream.fileno()

                def read(self, limit):
                    nonlocal changed, reads
                    raw = self.stream.read(limit)
                    reads += 1
                    if reads == 3 and not changed:
                        changed = True
                        mutate()
                    return raw

            monkeypatch.setattr(
                os, "fdopen", lambda *args, **kwargs: RacingStream(original_fdopen(*args, **kwargs))
            )
        with pytest.raises(route_approval.ApprovalError):
            foreign.observe_current(pair.config, pair.state, selected_scope)
        assert changed

    @pytest.mark.parametrize("which", ["registry", "appearance", "displays"])
    @pytest.mark.parametrize("when", ["revalidate", "parse", "collection"])
    @pytest.mark.parametrize("parent_link", [False, True])
    def test_same_bytes_link_retarget(
        self,
        foreign_pair: Layout,
        selected_scope: Scope,
        which: str,
        when: str,
        parent_link: bool,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        path: Path = getattr(foreign_pair, which)
        a_dir = tmp_path / "first"
        b_dir = tmp_path / "second"
        a_dir.mkdir()
        b_dir.mkdir()
        first = a_dir / path.name
        second = b_dir / path.name
        path.rename(first)
        second.write_bytes(first.read_bytes())
        second.chmod(first.stat().st_mode & 0o777)
        if parent_link:
            path.parent.rmdir()
            path.parent.symlink_to(a_dir, target_is_directory=True)
            link = path.parent
        else:
            path.symlink_to(first)
            link = path
        foreign_pair.declare()
        if which == "registry":
            second.write_bytes(first.read_bytes())

        def retarget():
            link.unlink()
            link.symlink_to(b_dir if parent_link else second)

        if when == "revalidate":
            result = foreign.observe_current(
                foreign_pair.config, foreign_pair.state, selected_scope
            )
            retarget()
            with pytest.raises(route_approval.ApprovalError):
                foreign.revalidate_current(result)
        elif when == "parse":
            original = scoped_config.read_document
            changed = False

            def racing(text, **kwargs):
                nonlocal changed
                try:
                    return original(text, **kwargs)
                finally:
                    if not changed:
                        changed = True
                        retarget()

            monkeypatch.setattr(scoped_config, "read_document", racing)
            with pytest.raises(route_approval.ApprovalError):
                foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)
        else:
            original_read = route_approval._read_file
            changed = False

            def racing_read(candidate, **kwargs):
                nonlocal changed
                result = original_read(candidate, **kwargs)
                if candidate == foreign_pair.displays and not changed:
                    changed = True
                    retarget()
                return result

            monkeypatch.setattr(route_approval, "_read_file", racing_read)
            with pytest.raises(route_approval.ApprovalError):
                foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)

    def test_canonical_inspector_rechecks_after_parse(
        self, layout: Layout, monkeypatch: pytest.MonkeyPatch
    ):
        original = scoped_config.read_document

        def racing(text, **kwargs):
            result = original(text, **kwargs)
            layout.registry.write_bytes(layout.registry.read_bytes() + b"\n")
            return result

        monkeypatch.setattr(scoped_config, "read_document", racing)
        with pytest.raises(route_approval.ApprovalError, match="changed during inspection"):
            layout.inspect()


class TestTransport:
    @pytest.mark.parametrize(
        "kind",
        [
            "unknown",
            "schema-bool",
            "schema",
            "kind",
            "scope",
            "scope-bool",
            "status",
            "classification",
            "text",
            "selected-hash",
            "leaf-size",
            "sibling-id",
            "counts",
            "counts-bool",
            "registry-context",
            "protected-context",
            "git-context",
            "stamp",
            "naive",
            "non-utc",
            "hash",
            "selected-extra",
            "surrogate",
        ],
    )
    def test_strict_semantic_validation_even_with_recomputed_hash(
        self, foreign_pair: Layout, selected_scope: Scope, kind: str
    ):
        result = foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)
        frame = json.loads(result.to_json())
        data = frame["observation"]
        if kind == "unknown":
            data["unknown"] = 1
        elif kind == "schema-bool":
            frame["schema"] = True
        elif kind == "schema":
            frame["schema"] = 2
        elif kind == "kind":
            frame["kind"] = "installation-evidence"
        elif kind == "scope":
            data["selected_scope"] = "unknown"
        elif kind == "scope-bool":
            data["selected"]["scope"] = True
        elif kind == "status":
            data["selected"]["status"] = "canonical"
        elif kind == "classification":
            data["selected"]["status"] = "invalid-scoped"
        elif kind == "text":
            data["selected"]["text"] += "edited"
        elif kind == "surrogate":
            data["selected"]["text"] = "\ud800"
        elif kind == "selected-hash":
            data["selected"]["file"]["source_sha256"] = "0" * 64
        elif kind == "leaf-size":
            data["selected"]["file"]["path"]["facts"][-1]["identity"][6] += 1
        elif kind == "sibling-id":
            data["sibling"]["route"]["content_id"] = "0" * 64
        elif kind == "counts":
            data["sibling"]["route"]["counts"][0] += 1
        elif kind == "counts-bool":
            data["sibling"]["route"]["counts"][0] = True
        elif kind == "registry-context":
            data["config_root"] = "/different"
        elif kind == "protected-context":
            data["protected"][0]["lexical_path"] = "/different"
        elif kind == "git-context":
            data["registry"]["git_context"][0]["path"] = "/different/.git"
        elif kind == "stamp":
            data["observed_at"] = False
        elif kind == "naive":
            data["observed_at"] = "2000-01-01T00:00:00"
        elif kind == "non-utc":
            data["observed_at"] = "2000-01-01T00:00:00+02:00"
        elif kind == "selected-extra":
            data["selected"]["content_id"] = "0" * 64
        text = _rehash(frame)
        if kind == "hash":
            frame["observation_hash"] = "0" * 64
            text = route_approval._json(frame)
        with pytest.raises(route_approval.ApprovalError):
            foreign.ScopedForeignObservation.from_json(text)

    @pytest.mark.parametrize("kind", ["duplicate", "nested-duplicate", "deep", "oversize", "nan"])
    def test_json_envelope_bounds(self, foreign_pair: Layout, selected_scope: Scope, kind: str):
        text = foreign.observe_current(
            foreign_pair.config, foreign_pair.state, selected_scope
        ).to_json()
        if kind == "duplicate":
            text = text.replace('"schema":1', '"schema":1,"schema":1')
        elif kind == "nested-duplicate":
            text = text.replace('"status":"foreign"', '"status":"foreign","status":"foreign"')
        elif kind == "deep":
            text = "[" * 25 + "]" * 25
        elif kind == "oversize":
            text = " " * (foreign.MAX_OBSERVATION_BYTES + 1)
        else:
            text = text.replace('"schema":1', '"schema":NaN')
        with pytest.raises(route_approval.ApprovalError):
            foreign.ScopedForeignObservation.from_json(text)

    @pytest.mark.parametrize(
        "kind", ["protected-list", "facts-list", "identity-list", "counts-list", "enum"]
    )
    def test_original_nested_mutability_not_hidden_by_json(
        self,
        foreign_pair: Layout,
        selected_scope: Scope,
        kind: str,
        monkeypatch: pytest.MonkeyPatch,
    ):
        result = foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)
        if kind == "protected-list":
            obj, name, value = result, "protected", list(result.protected)
        elif kind == "facts-list":
            obj, name, value = (
                result.selected.file.path,
                "facts",
                list(result.selected.file.path.facts),
            )
        elif kind == "identity-list":
            fact = result.selected.file.path.facts[-1]
            obj, name, value = fact, "identity", list(fact.identity)
        elif kind == "counts-list":
            obj, name, value = result.sibling.route, "counts", list(result.sibling.route.counts)
        else:
            obj, name, value = result.selected, "scope", selected_scope.value
        object.__setattr__(obj, name, value)

        def forbidden(*args, **kwargs):
            pytest.fail("JSON normalization preceded original-type validation")

        monkeypatch.setattr(foreign, "asdict", forbidden)
        with pytest.raises(route_approval.ApprovalError):
            result.to_json()
        with pytest.raises(route_approval.ApprovalError):
            foreign.revalidate_current(result)

    def test_decode_is_pure_not_filesystem_authentication(
        self, foreign_pair: Layout, selected_scope: Scope, monkeypatch: pytest.MonkeyPatch
    ):
        result = foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)
        data = json.loads(result.to_json())
        data["observation"]["registry"]["source_sha256"] = "0" * 64
        text = _rehash(data)

        def forbidden(*args, **kwargs):
            pytest.fail("Pure codec touched filesystem")

        with monkeypatch.context() as patch:
            patch.setattr(os, "open", forbidden)
            patch.setattr(Path, "lstat", forbidden)
            patch.setattr(Path, "stat", forbidden)
            forged = foreign.ScopedForeignObservation.from_json(text)
        with pytest.raises(route_approval.ApprovalError, match="changed"):
            foreign.revalidate_current(forged)

    def test_metadata_limit_is_independent_of_text_limit(
        self, foreign_pair: Layout, selected_scope: Scope
    ):
        result = foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)
        fact = result.protected[0].facts[0]
        long_fact = replace(fact, path="/" + "x" * 3500)
        proof = replace(result.protected[0], facts=(long_fact,) * 400)
        with pytest.raises(route_approval.ApprovalError, match="metadata"):
            replace(result, protected=(proof, *result.protected[1:]))

    def test_actual_unicode_ascii_escape_aggregate_bound(self, layout: Layout):
        # U+0800 takes 3 UTF-8 bytes but 6 ASCII JSON bytes; v2 also embeds base64.
        value = "\u0800" * 90000
        layout.appearance.write_text(
            scoped_config.build_text(
                scoped_config.ScopedConfig(
                    Scope.APPEARANCE,
                    {"values": {"decoration:custom": value}, "beziers": [], "animations": []},
                )
            )
        )
        layout.displays.write_bytes(b"\\" * foreign.MAX_INPUT_BYTES)
        result = foreign.observe_current(layout.config, layout.state, Scope.DISPLAYS)
        text = result.to_json()
        assert text.isascii()
        assert len(text) <= foreign.MAX_OBSERVATION_BYTES
        assert foreign.ScopedForeignObservation.from_json(text) == result

    def test_actual_unescaped_unicode_transport_cannot_hide_ascii_overflow(
        self, foreign_pair: Layout, selected_scope: Scope
    ):
        result = foreign.observe_current(foreign_pair.config, foreign_pair.state, selected_scope)
        frame = json.loads(result.to_json())
        frame["observation"]["selected"]["text"] = "\u00a0" * 1400000
        text = json.dumps(frame, ensure_ascii=False)
        assert len(text.encode()) < foreign.MAX_OBSERVATION_BYTES
        assert len(json.dumps(frame, ensure_ascii=True)) > foreign.MAX_OBSERVATION_BYTES
        with pytest.raises(route_approval.ApprovalError, match="ASCII transport"):
            foreign.ScopedForeignObservation.from_json(text)


class TestWorker:
    def test_actual_isolated_roundtrip(self, foreign_pair: Layout, selected_scope: Scope):
        pair = foreign_pair
        result = foreign.run_observe(pair.config, pair.state, selected_scope)
        assert (
            result.observation_hash
            == foreign.observe_current(pair.config, pair.state, selected_scope).observation_hash
        )
        assert not pair.state.exists()

    def test_missing_registry_refuses_without_initialization(self, layout: Layout):
        layout.registry.unlink()
        with pytest.raises(route_approval.ApprovalError, match="worker refused"):
            foreign.run_observe(layout.config, layout.state, Scope.APPEARANCE)
        assert not layout.registry.exists()
        assert not layout.state.exists()

    @pytest.mark.parametrize("mode", ["commit", "preserve", "prepare", "observe"])
    def test_no_mutator_cli_or_implicit_context(self, tmp_path: Path, mode: str):
        before = tuple(tmp_path.iterdir())
        result = health.run_bounded(
            [sys.executable, "-I", "-B", "-m", "hyprmod.core.scoped_foreign", mode],
            timeout=10,
            max_bytes=4096,
            cwd=tmp_path,
        )
        assert result.returncode != 0
        assert tuple(tmp_path.iterdir()) == before

    def test_cancel_and_deadline(self, foreign_pair: Layout, selected_scope: Scope):
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(InterruptedError):
            foreign.run_observe(
                foreign_pair.config, foreign_pair.state, selected_scope, cancel_event=cancel
            )
        with pytest.raises(subprocess.TimeoutExpired):
            foreign.run_observe(
                foreign_pair.config, foreign_pair.state, selected_scope, timeout=0.000001
            )

    @pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), float("inf")])
    def test_invalid_timeout(self, layout: Layout, timeout: float):
        with pytest.raises(route_approval.ApprovalError):
            foreign.run_observe(layout.config, layout.state, Scope.APPEARANCE, timeout=timeout)

    @pytest.mark.parametrize("kind", ["root", "selection", "oversize", "invalid", "valid"])
    def test_response_bound_context_echo_and_no_parent_reread(
        self,
        foreign_pair: Layout,
        selected_scope: Scope,
        kind: str,
        monkeypatch: pytest.MonkeyPatch,
    ):
        pair = foreign_pair
        result = foreign.observe_current(pair.config, pair.state, selected_scope)
        data = json.loads(result.to_json())
        if kind == "root":
            data["observation"]["state_root"] = "/different"
            data["observation"]["protected"][-1]["lexical_path"] = "/different/attune"
        response = _rehash(data)
        if kind == "oversize":
            response = " " * (foreign.MAX_OBSERVATION_BYTES + 1)
        elif kind == "invalid":
            response = "{}"

        def fake_worker(command, **kwargs):
            assert command[:5] == [sys.executable, "-I", "-B", "-m", "hyprmod.core.scoped_foreign"]
            assert command[5] == "observe"
            assert kwargs["process_group"] is True
            assert kwargs["max_bytes"] == foreign.MAX_OBSERVATION_BYTES
            assert kwargs["timeout"] == 30
            return subprocess.CompletedProcess(command, 0, response, "")

        def forbidden(*args, **kwargs):
            pytest.fail("Parent reread filesystem after supervised response")

        monkeypatch.setattr(health, "run_bounded", fake_worker)
        monkeypatch.setattr(route_approval, "_collect_filesystem", forbidden)
        monkeypatch.setattr(Path, "stat", forbidden)
        monkeypatch.setattr(Path, "lstat", forbidden)
        if kind == "valid":
            assert foreign.run_observe(pair.config, pair.state, selected_scope) == result
        else:
            requested = (
                next(s for s in Scope if s is not selected_scope)
                if kind == "selection"
                else selected_scope
            )
            with pytest.raises(route_approval.ApprovalError):
                foreign.run_observe(pair.config, pair.state, requested)

    def test_actual_child_oversized_response_is_killed(
        self, foreign_pair: Layout, selected_scope: Scope, monkeypatch: pytest.MonkeyPatch
    ):
        original = health.run_bounded

        def oversized_worker(command, **kwargs):
            return original(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    f"import sys; sys.stdout.write('x' * {foreign.MAX_OBSERVATION_BYTES + 1})",
                ],
                **kwargs,
            )

        monkeypatch.setattr(health, "run_bounded", oversized_worker)
        with pytest.raises(ValueError, match="capture limit"):
            foreign.run_observe(foreign_pair.config, foreign_pair.state, selected_scope)
