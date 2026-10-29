"""Read-only M3 route observations, using only temporary filesystem fixtures."""

import builtins
import io
import json
import os
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path

import pytest

from hyprmod.core import health, installation, persistence
from hyprmod.core import route_approval as approval
from hyprmod.core.scoped_config import ScopedConfig, build_text
from hyprmod.core.scopes import SCOPE_BASENAMES, Scope


@dataclass
class Layout:
    config: Path
    state: Path
    registry: Path
    appearance: Path
    displays: Path

    def declare(self) -> None:
        routes = [
            installation.ScopeRoute(scope, str(path), str(path.resolve()))
            for scope, path in (
                (Scope.APPEARANCE, self.appearance),
                (Scope.DISPLAYS, self.displays),
            )
        ]
        self.registry.write_text(installation.InstallationRegistry(*routes).to_json())
        self.registry.chmod(0o600)

    def inspect(self) -> approval.InstallationEvidence:
        return approval.inspect_installation(
            self.registry, config_root=self.config, state_root=self.state
        )


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    config = tmp_path / "config"
    state = tmp_path / "state"
    (config / "attune").mkdir(parents=True)
    (config / "hypr").mkdir()
    local = tmp_path / "local"
    local.mkdir()
    appearance = config / "hypr" / SCOPE_BASENAMES[Scope.APPEARANCE]
    displays = local / SCOPE_BASENAMES[Scope.DISPLAYS]
    for scope, path in ((Scope.APPEARANCE, appearance), (Scope.DISPLAYS, displays)):
        payload = (
            {"values": {"general:border_size": "2"}, "beziers": [], "animations": []}
            if scope == Scope.APPEARANCE
            else {"monitors": ["monitor = DP-1, disable"]}
        )
        path.write_text(build_text(ScopedConfig(scope, payload)))
        path.chmod(0o644)
    result = Layout(config, state, config / "attune/installation.json", appearance, displays)
    result.declare()
    return result


class TestEvidence:
    @pytest.mark.skipif(os.geteuid() == 0, reason="Root can traverse non-searchable directories")
    @pytest.mark.parametrize("reinspection", [False, True])
    def test_dotdot_cannot_bypass_kernel_search_permissions(
        self, layout: Layout, tmp_path: Path, reinspection: bool
    ):
        source = tmp_path / "source"
        source.mkdir()
        target = source / layout.appearance.name
        layout.appearance.rename(target)
        unsearchable = source / "no-search"
        unsearchable.mkdir(mode=0o700)
        layout.appearance.symlink_to(unsearchable / ".." / target.name)
        layout.declare()
        previous = layout.inspect() if reinspection else None
        unsearchable.chmod(0o600)
        try:
            with pytest.raises(PermissionError):
                layout.appearance.stat()
            with pytest.raises(approval.ApprovalError):
                if previous is not None:
                    approval.revalidate(previous)
                else:
                    layout.inspect()
        finally:
            unsearchable.chmod(0o700)

    def test_roundtrip_immutable_and_timestamp_independent(self, layout: Layout):
        evidence = layout.inspect()
        assert approval.InstallationEvidence.from_json(evidence.to_json()) == evidence
        assert approval.revalidate(evidence).evidence_hash == evidence.evidence_hash
        assert (
            replace(evidence, observed_at="2000-01-01T00:00:00+00:00").evidence_hash
            == evidence.evidence_hash
        )
        assert evidence.routes[0].counts == (1, 0, 0, 0)
        assert evidence.routes[1].counts == (0, 0, 0, 1)
        assert (
            evidence.registry.source_sha256
            == installation.parse_registry(layout.registry.read_text()).source_sha256
        )
        with pytest.raises(FrozenInstanceError):
            setattr(evidence, "config_root", "/elsewhere")
        assert not layout.state.exists()

    @pytest.mark.parametrize("mode", [0o600, 0o640, 0o644])
    def test_normal_scope_permissions(self, layout: Layout, mode: int):
        layout.appearance.chmod(mode)
        layout.displays.chmod(mode)
        layout.inspect()

    @pytest.mark.parametrize("mode", [0o644, 0o640, 0o400, 0o200, 0o700, 0o1600, 0o4600])
    def test_registry_permissions(self, layout: Layout, mode: int):
        layout.registry.chmod(mode)
        with pytest.raises(approval.ApprovalError):
            layout.inspect()

    @pytest.mark.parametrize("mode", [0o444, 0o200, 0o666, 0o664, 0o755, 0o1644, 0o2644])
    def test_scope_permissions(self, layout: Layout, mode: int):
        layout.appearance.chmod(mode)
        with pytest.raises(approval.ApprovalError):
            layout.inspect()

    @pytest.mark.parametrize("which", ["registry", "appearance", "displays"])
    @pytest.mark.parametrize(
        "kind", ["missing", "hardlink", "fifo", "directory", "cycle", "dangling"]
    )
    def test_unsafe_objects(self, layout: Layout, which: str, kind: str, tmp_path: Path):
        path: Path = getattr(layout, which)
        if kind == "hardlink":
            os.link(path, tmp_path / "hardlink")
        else:
            path.unlink()
            if kind == "fifo":
                os.mkfifo(path)
            elif kind == "directory":
                path.mkdir()
            elif kind == "cycle":
                path.symlink_to(path)
            elif kind == "dangling":
                path.symlink_to(tmp_path / "absent")
        with pytest.raises(approval.ApprovalError):
            layout.inspect()

    @pytest.mark.parametrize("raw", [b"", b"\xff", b"{}", b"x" * 65537, b'{"schema":1,"schema":1}'])
    def test_bad_registry_bytes(self, layout: Layout, raw: bytes):
        layout.registry.write_bytes(raw)
        with pytest.raises(approval.ApprovalError):
            layout.inspect()

    @pytest.mark.parametrize("kind", ["empty", "utf8", "syntax", "legacy", "scope", "version"])
    def test_bad_scope_bytes(self, layout: Layout, kind: str):
        raw = layout.appearance.read_bytes()
        if kind == "empty":
            raw = b""
        elif kind == "utf8":
            raw = b"\xff"
        elif kind == "syntax":
            raw += b"os.execute('unsafe')\n"
        elif kind == "legacy":
            raw = persistence._render({}, {}).encode()
        elif kind == "scope":
            raw = layout.displays.read_bytes()
        elif kind == "version":
            raw = raw.replace(b"data v2", b"data v3")
        layout.appearance.write_bytes(raw)
        with pytest.raises(approval.ApprovalError):
            layout.inspect()

    def test_file_and_parent_stow_links(self, layout: Layout, tmp_path: Path):
        repo = tmp_path / "dotfiles"
        repo.mkdir()
        (repo / ".git").mkdir()
        target = repo / layout.appearance.name
        layout.appearance.rename(target)
        hypr = layout.appearance.parent
        hypr.rmdir()
        hypr.symlink_to(repo, target_is_directory=True)
        local_source = tmp_path / "source"
        local_source.mkdir()
        display_target = local_source / layout.displays.name
        layout.displays.rename(display_target)
        layout.displays.symlink_to(display_target)
        reg_source = tmp_path / "registry.json"
        layout.registry.rename(reg_source)
        layout.registry.symlink_to(reg_source)
        layout.declare()
        evidence = layout.inspect()
        assert evidence.routes[0].file.path.resolved_path == str(target)
        assert evidence.routes[1].file.path.resolved_path == str(display_target)
        assert evidence.registry.path.resolved_path == str(reg_source)
        assert any(f.link_target for f in evidence.routes[0].file.path.facts)
        assert layout.displays.is_symlink() and hypr.is_symlink()
        approval.revalidate(evidence)

    @pytest.mark.parametrize("which", ["registry", "displays"])
    @pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
    def test_local_files_outside_git(self, layout: Layout, which: str, kind: str):
        path: Path = getattr(layout, which)
        marker = path.parent / ".git"
        if kind == "directory":
            marker.mkdir()
        elif kind == "file":
            marker.write_text("gitdir: /never/read/this")
        else:
            marker.symlink_to("uninspectable")
        with pytest.raises(approval.ApprovalError, match="Git"):
            layout.inspect()

    def test_appearance_git_file_allowed(self, layout: Layout):
        (layout.appearance.parent / ".git").write_text("gitdir: /not/read")
        layout.inspect()

    @pytest.mark.parametrize("name", ["hyprland.lua", "hyprland.conf", "attune.lua"])
    def test_protected_inode_symlink_alias(self, layout: Layout, name: str):
        (layout.config / "hypr" / name).symlink_to(layout.appearance)
        with pytest.raises(approval.ApprovalError, match="collide|alias"):
            layout.inspect()

    @pytest.mark.parametrize("which", ["registry", "appearance", "displays"])
    def test_state_symlink_root_collision(self, layout: Layout, which: str):
        layout.state.mkdir()
        path: Path = getattr(layout, which)
        (layout.state / "attune").symlink_to(path.parent, target_is_directory=True)
        with pytest.raises(approval.ApprovalError, match="collide"):
            layout.inspect()

    def test_state_parent_symlink_collision(self, layout: Layout, tmp_path: Path):
        actual = tmp_path / "actual-state"
        (actual / "attune/backups").mkdir(parents=True)
        layout.state.symlink_to(actual)
        target = actual / "attune/backups" / layout.displays.name
        layout.displays.rename(target)
        layout.displays.symlink_to(target)
        layout.declare()
        with pytest.raises(approval.ApprovalError, match="collide"):
            layout.inspect()

    def test_actual_resolution_must_match(self, layout: Layout, tmp_path: Path):
        target = tmp_path / layout.appearance.name
        layout.appearance.rename(target)
        layout.appearance.symlink_to(target)
        with pytest.raises(approval.ApprovalError, match="resolution"):
            layout.inspect()

    def test_wrong_resolved_basename(self, layout: Layout, tmp_path: Path):
        target = tmp_path / "wrong.lua"
        layout.appearance.rename(target)
        layout.appearance.symlink_to(target)
        data = json.loads(layout.registry.read_text())
        data["routes"]["appearance"]["approved_resolved_path"] = str(target)
        layout.registry.write_text(json.dumps(data))
        with pytest.raises(approval.ApprovalError):
            layout.inspect()

    @pytest.mark.parametrize("mode", [0o777, 0o775, 0o500, 0o1700])
    def test_immediate_parent_security(self, layout: Layout, mode: int):
        layout.displays.parent.chmod(mode)
        with pytest.raises(approval.ApprovalError):
            layout.inspect()

    @pytest.mark.parametrize("value", ["relative", "/a/../b", "/a/$HOME", "/" + "a" * 4096])
    def test_explicit_context_validation(self, layout: Layout, value: str):
        with pytest.raises(approval.ApprovalError):
            approval.inspect_installation(
                layout.registry, config_root=Path(value), state_root=layout.state
            )
        with pytest.raises(approval.ApprovalError):
            approval.inspect_installation(
                layout.registry, config_root=layout.config, state_root=Path(value)
            )

    def test_no_other_registry_and_no_default_context(self, layout: Layout):
        with pytest.raises(approval.ApprovalError, match="config_root"):
            approval.inspect_installation(
                layout.appearance, config_root=layout.config, state_root=layout.state
            )
        with pytest.raises(TypeError):
            approval.inspect_installation(layout.registry)  # type: ignore[call-arg]

    def test_depth_and_link_hop_bounds(self, layout: Layout, tmp_path: Path):
        with pytest.raises(approval.ApprovalError):
            approval._path("/" + "/".join("x" for _ in range(approval.MAX_DEPTH)))
        target = tmp_path / layout.appearance.name
        layout.appearance.rename(target)
        previous = target
        for index in range(41):
            link = tmp_path / f"link-{index}"
            link.symlink_to(previous)
            previous = link
        layout.appearance.symlink_to(previous)
        with pytest.raises(approval.ApprovalError, match="40 hops"):
            layout.inspect()

    def test_cross_scope_actual_inode_collision(self, layout: Layout):
        layout.displays.unlink()
        os.link(layout.appearance, layout.displays)
        with pytest.raises(approval.ApprovalError, match="alias|single-link"):
            layout.inspect()

    def test_relative_links_at_hop_limit(self, layout: Layout, tmp_path: Path):
        target = tmp_path / layout.appearance.name
        layout.appearance.rename(target)
        previous = target
        for index in range(39):
            link = tmp_path / f"relative-{index}"
            link.symlink_to(previous.name)
            previous = link
        layout.appearance.symlink_to(previous)
        layout.declare()
        layout.inspect()

    def test_protected_directory_descendant_collision(self, layout: Layout):
        protected = layout.config / "hypr/hyprland.lua"
        protected.mkdir()
        target = protected / layout.appearance.name
        layout.appearance.rename(target)
        layout.appearance.symlink_to(target)
        layout.declare()
        with pytest.raises(approval.ApprovalError, match="collide"):
            layout.inspect()

    def test_registry_output_alias(self, layout: Layout):
        layout.appearance.unlink()
        layout.appearance.symlink_to(layout.registry)
        with pytest.raises(approval.ApprovalError, match="collide"):
            layout.inspect()

    def test_uninspectable_git_fact_fails_closed(
        self, layout: Layout, monkeypatch: pytest.MonkeyPatch
    ):
        original = Path.lstat

        def inaccessible(path, *args, **kwargs):
            if path == layout.displays.parent / ".git":
                raise PermissionError("Git marker inaccessible")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "lstat", inaccessible)
        with pytest.raises(approval.ApprovalError, match="inaccessible"):
            layout.inspect()

    @pytest.mark.parametrize("which", ["registry", "appearance", "parent"])
    def test_foreign_owner(self, layout: Layout, monkeypatch: pytest.MonkeyPatch, which: str):
        path = layout.appearance.parent if which == "parent" else getattr(layout, which)
        original = approval._fact

        def foreign_owner(candidate):
            fact = original(candidate)
            if candidate == path:
                identity = list(fact.identity)
                identity[3] = os.getuid() + 1
                return replace(fact, identity=tuple(identity))
            return fact

        monkeypatch.setattr(approval, "_fact", foreign_owner)
        with pytest.raises(approval.ApprovalError):
            layout.inspect()

    def test_protected_alias_refused_before_read(
        self, layout: Layout, monkeypatch: pytest.MonkeyPatch
    ):
        (layout.config / "hypr/hyprland.lua").symlink_to(layout.appearance)
        original = os.open

        def no_scope_read(path, flags, *args, **kwargs):
            assert Path(path) != layout.appearance
            return original(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", no_scope_read)
        with pytest.raises(approval.ApprovalError, match="collide"):
            layout.inspect()

    def test_no_writes_execution_or_main_reads(
        self, layout: Layout, monkeypatch: pytest.MonkeyPatch
    ):
        main = layout.config / "hypr/hyprland.lua"
        main.write_text("arbitrary authored bytes")
        original_open = os.open
        original_io_open = io.open

        def guarded_open(path, flags, *args, **kwargs):
            assert Path(path) != main
            assert flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC) == 0
            return original_open(path, flags, *args, **kwargs)

        def forbidden(*args, **kwargs):
            pytest.fail("Unexpected write, execution, or high-level file read")

        def descriptor_only(path, *args, **kwargs):
            assert isinstance(path, int)
            return original_io_open(path, *args, **kwargs)

        monkeypatch.setattr(os, "open", guarded_open)
        monkeypatch.setattr(io, "open", descriptor_only)
        for obj, name in (
            (os, "mkdir"),
            (os, "chmod"),
            (os, "replace"),
            (subprocess, "Popen"),
            (builtins, "open"),
            (persistence, "validate_lua"),
        ):
            monkeypatch.setattr(obj, name, forbidden)
        layout.inspect()


class TestRevalidation:
    @pytest.mark.parametrize(
        "kind",
        [
            "bytes",
            "whitespace",
            "permission",
            "parent",
            "parent_mode",
            "git",
            "protected",
            "hardlink",
        ],
    )
    def test_changes_refused(self, layout: Layout, tmp_path: Path, kind: str):
        evidence = layout.inspect()
        if kind == "bytes":
            layout.appearance.write_text(
                build_text(
                    ScopedConfig(Scope.APPEARANCE, {"values": {}, "beziers": [], "animations": []})
                )
            )
        elif kind == "whitespace":
            layout.registry.write_text(layout.registry.read_text() + "\n")
        elif kind == "permission":
            layout.appearance.chmod(0o640)
        elif kind == "parent":
            parent = layout.displays.parent
            parent.rename(tmp_path / "old")
            parent.mkdir()
            (tmp_path / "old" / layout.displays.name).rename(layout.displays)
        elif kind == "parent_mode":
            layout.displays.parent.chmod(0o750)
        elif kind == "git":
            (layout.displays.parent / ".git").write_text("gitdir: elsewhere")
        elif kind == "protected":
            (layout.config / "hypr/hyprland.lua").symlink_to(layout.appearance)
        elif kind == "hardlink":
            os.link(layout.appearance, tmp_path / "alias")
        with pytest.raises(approval.ApprovalError):
            approval.revalidate(evidence)

    def test_same_bytes_link_retarget(self, layout: Layout, tmp_path: Path):
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        a = first / layout.appearance.name
        b = second / layout.appearance.name
        layout.appearance.rename(a)
        b.write_bytes(a.read_bytes())
        layout.appearance.symlink_to(a)
        layout.declare()
        evidence = layout.inspect()
        layout.appearance.unlink()
        layout.appearance.symlink_to(b)
        with pytest.raises(approval.ApprovalError):
            approval.revalidate(evidence)

    def test_unrelated_sibling_activity_is_harmless(self, layout: Layout):
        evidence = layout.inspect()
        (layout.displays.parent / "unrelated").write_text("sibling")
        approval.revalidate(evidence)

    @pytest.mark.parametrize(
        "kind",
        [
            "hash",
            "nested_unknown",
            "scope",
            "counts",
            "metadata",
            "context",
            "duplicate",
            "deep",
            "oversize",
        ],
    )
    def test_transport_rejects_malformed_or_tampered(self, layout: Layout, kind: str):
        text = layout.inspect().to_json()
        data = json.loads(text)
        if kind == "hash":
            data["evidence_hash"] = "0" * 64
        elif kind == "nested_unknown":
            data["evidence"]["registry"]["extra"] = True
        elif kind == "scope":
            data["evidence"]["routes"][0]["scope"] = "displays"
        elif kind == "counts":
            data["evidence"]["routes"][0]["counts"] = [True, 0, 0, 0]
        elif kind == "metadata":
            data["evidence"]["registry"]["path"]["facts"][0]["identity"] = [1]
        elif kind == "context":
            data["evidence"]["state_root"] = "/different"
        elif kind == "duplicate":
            text = text.replace('"scope":"appearance"', '"scope":"appearance","scope":"appearance"')
        elif kind == "deep":
            text = "[" * 2000 + "]" * 2000
        elif kind == "oversize":
            text = " " * (approval.MAX_EVIDENCE_BYTES + 1)
        if kind not in {"duplicate", "deep", "oversize"}:
            text = json.dumps(data)
        with pytest.raises(approval.ApprovalError):
            approval.InstallationEvidence.from_json(text)

    def test_recomputed_hash_is_not_approval(self, layout: Layout):
        evidence = layout.inspect()
        forged_file = replace(evidence.routes[0].file, source_sha256="0" * 64)
        forged = replace(
            evidence, routes=(replace(evidence.routes[0], file=forged_file), evidence.routes[1])
        )
        decoded = approval.InstallationEvidence.from_json(forged.to_json())
        with pytest.raises(approval.ApprovalError, match="changed since review"):
            approval.revalidate(decoded)

    def test_final_recheck_detects_mixed_observation(
        self, layout: Layout, monkeypatch: pytest.MonkeyPatch
    ):
        original = approval._read_file

        def racing_read(path, **kwargs):
            result = original(path, **kwargs)
            if path == layout.displays:
                layout.appearance.chmod(0o640)
            return result

        monkeypatch.setattr(approval, "_read_file", racing_read)
        with pytest.raises(approval.ApprovalError, match="changed during inspection"):
            layout.inspect()

    def test_open_race_detected(self, layout: Layout, monkeypatch: pytest.MonkeyPatch):
        original = os.open

        def racing_open(path, flags, *args, **kwargs):
            if Path(path) == layout.appearance:
                layout.appearance.chmod(0o640)
            return original(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", racing_open)
        with pytest.raises(approval.ApprovalError, match="changed before read"):
            layout.inspect()

    def test_read_race_detected(self, layout: Layout, monkeypatch: pytest.MonkeyPatch):
        original = os.fdopen

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
                raw = self.stream.read(limit)
                layout.registry.chmod(0o640)
                return raw

        monkeypatch.setattr(
            os, "fdopen", lambda *args, **kwargs: RacingStream(original(*args, **kwargs))
        )
        with pytest.raises(approval.ApprovalError, match="changed during read"):
            layout.inspect()

    def test_disappeared_before_read(self, layout: Layout, monkeypatch: pytest.MonkeyPatch):
        original = approval._fact

        def vanished(path):
            if path == layout.registry:
                return approval.PathFact(str(path), ())
            return original(path)

        monkeypatch.setattr(approval, "_fact", vanished)
        with pytest.raises(approval.ApprovalError, match="Missing"):
            layout.inspect()

    def test_git_appearance_added_invalidates(self, layout: Layout):
        evidence = layout.inspect()
        (layout.appearance.parent / ".git").mkdir()
        with pytest.raises(approval.ApprovalError, match="changed since review"):
            approval.revalidate(evidence)

    def test_new_nonalias_protected_file_invalidates(self, layout: Layout):
        evidence = layout.inspect()
        (layout.config / "hypr/hyprland.conf").write_text("authored, not parsed")
        with pytest.raises(approval.ApprovalError, match="changed since review"):
            approval.revalidate(evidence)


class TestWorker:
    def test_real_worker_and_revalidate(self, layout: Layout):
        evidence = approval.run_inspect(
            layout.registry, config_root=layout.config, state_root=layout.state
        )
        assert approval.run_revalidate(evidence).evidence_hash == evidence.evidence_hash
        assert not layout.state.exists()

    def test_real_worker_missing_context(self, tmp_path: Path):
        before = tuple(tmp_path.iterdir())
        result = health.run_bounded(
            [sys.executable, "-I", "-B", "-m", "hyprmod.core.route_approval"],
            timeout=10,
            max_bytes=approval.MAX_EVIDENCE_BYTES,
            cwd=tmp_path,
        )
        assert result.returncode != 0
        assert "required" in result.stderr
        assert tuple(tmp_path.iterdir()) == before

    def test_real_worker_missing_registry_no_creation(self, layout: Layout):
        layout.registry.unlink()
        with pytest.raises(approval.ApprovalError):
            approval.run_inspect(
                layout.registry, config_root=layout.config, state_root=layout.state
            )
        assert not layout.registry.exists() and not layout.state.exists()

    def test_cancellation_and_timeout(self, layout: Layout):
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(InterruptedError):
            approval.run_inspect(
                layout.registry,
                config_root=layout.config,
                state_root=layout.state,
                cancel_event=cancel,
            )
        with pytest.raises(subprocess.TimeoutExpired):
            approval.run_inspect(
                layout.registry,
                config_root=layout.config,
                state_root=layout.state,
                timeout=0.000001,
            )

    @pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
    def test_invalid_timeout(self, layout: Layout, timeout: float):
        with pytest.raises(approval.ApprovalError):
            approval.run_inspect(
                layout.registry, config_root=layout.config, state_root=layout.state, timeout=timeout
            )
