"""Explicit temporary installations and privacy-only report projections."""

import builtins
import io
import os
import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from hyprmod.core import health, installation, persistence, route_approval, scoped_config
from hyprmod.core.scoped_diagnostics import (
    ScopeObservation,
    build_scoped_diagnostics_report,
    collect_scoped_diagnostics,
)
from hyprmod.core.scopes import SCOPE_BASENAMES, Scope


@pytest.fixture
def installation_pair(tmp_path):
    config = tmp_path / "private-user-config"
    state = tmp_path / "private-state"
    registry = config / "attune/installation.json"
    registry.parent.mkdir(parents=True)
    paths = []
    for scope in Scope:
        directory = tmp_path / scope.value
        directory.mkdir()
        path = directory / SCOPE_BASENAMES[scope]
        payload = (
            {
                "values": {"decoration:shadow:color": "private  value \u2603"},
                "beziers": [],
                "animations": [],
            }
            if scope == Scope.APPEARANCE
            else {"monitors": ["monitor = PRIVATE-DISPLAY, disable"]}
        )
        path.write_text(scoped_config.build_text(scoped_config.ScopedConfig(scope, payload)))
        path.chmod(0o600)
        paths.append(path)
    registry.write_text(
        installation.InstallationRegistry(
            *(
                installation.ScopeRoute(scope, str(path), str(path))
                for scope, path in zip(Scope, paths, strict=True)
            )
        ).to_json()
    )
    registry.chmod(0o600)
    evidence = route_approval.inspect_installation(registry, config_root=config, state_root=state)
    return evidence, registry, paths


class TestScopedCollection:
    def test_identical_bytes_symlink_retarget_invalidates(self, installation_pair, tmp_path):
        evidence, registry, paths = installation_pair
        original = tmp_path / "original"
        replacement = tmp_path / "replacement"
        original.mkdir()
        replacement.mkdir()
        first = original / paths[0].name
        second = replacement / paths[0].name
        paths[0].rename(first)
        second.write_bytes(first.read_bytes())
        second.chmod(0o600)
        paths[0].symlink_to(first)
        registry.write_text(
            installation.InstallationRegistry(
                installation.ScopeRoute(Scope.APPEARANCE, str(paths[0]), str(first)),
                installation.ScopeRoute(Scope.DISPLAYS, str(paths[1]), str(paths[1])),
            ).to_json()
        )
        evidence = route_approval.inspect_installation(
            registry, config_root=Path(evidence.config_root), state_root=Path(evidence.state_root)
        )
        paths[0].unlink()
        paths[0].symlink_to(second)
        with pytest.raises(route_approval.ApprovalError):
            collect_scoped_diagnostics(evidence)

    def test_fresh_facts_and_stable_binding(self, installation_pair, monkeypatch):
        evidence, _, _ = installation_pair
        old = replace(evidence, observed_at="2000-01-01T00:00:00+00:00")
        actual_revalidate = route_approval.revalidate
        returned = []

        def capture(value):
            fresh = actual_revalidate(value)
            returned.append(fresh)
            return fresh

        monkeypatch.setattr(route_approval, "revalidate", capture)
        observation = collect_scoped_diagnostics(old)
        assert observation.observed_at == returned[0].observed_at != old.observed_at
        assert observation.evidence_hash == old.evidence_hash == returned[0].evidence_hash
        for summary, route in zip(observation.scopes, returned[0].routes, strict=True):
            assert summary.scope is route.scope
            assert summary.counts == route.counts
            assert summary.content_id == route.content_id
            assert summary.sha256 == route.file.source_sha256
        assert observation.scopes[0].counts == (1, 0, 0, 0)
        assert observation.scopes[1].counts == (0, 0, 0, 1)
        with pytest.raises(FrozenInstanceError):
            setattr(observation, "observed_at", "changed")
        with pytest.raises(FrozenInstanceError):
            setattr(observation.scopes[0], "counts", ())

    @pytest.mark.parametrize(
        "change",
        ["whitespace", "content", "permissions", "parent_permissions", "retarget", "proof"],
    )
    def test_stale_evidence_refused(self, installation_pair, tmp_path, change):
        evidence, registry, paths = installation_pair
        if change == "whitespace":
            registry.write_text(registry.read_text() + " \n")
        elif change == "content":
            paths[0].write_text(
                scoped_config.build_text(
                    scoped_config.ScopedConfig(
                        Scope.APPEARANCE, {"values": {}, "beziers": [], "animations": []}
                    )
                )
            )
        elif change == "permissions":
            paths[1].chmod(0o666)
        elif change == "parent_permissions":
            paths[0].parent.chmod(0o777)
        elif change == "retarget":
            target = tmp_path / paths[0].name
            paths[0].rename(target)
            paths[0].symlink_to(target)
        else:
            evidence = replace(
                evidence,
                routes=(replace(evidence.routes[0], counts=(0, 0, 0, 0)), evidence.routes[1]),
            )
        with pytest.raises(route_approval.ApprovalError):
            collect_scoped_diagnostics(evidence)

    def test_no_writes_subprocess_health_or_lua(self, installation_pair, monkeypatch):
        evidence, _, paths = installation_pair
        before = [(p.read_bytes(), p.stat()) for p in paths]
        actual_open = os.open

        def read_only(path, flags, *args, **kwargs):
            assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            return actual_open(path, flags, *args, **kwargs)

        def forbidden(*args, **kwargs):
            pytest.fail("Unexpected mutation, worker, or Lua validation")

        monkeypatch.setattr(os, "open", read_only)
        for module, attr in (
            (Path, "write_text"),
            (Path, "write_bytes"),
            (os, "replace"),
            (subprocess, "run"),
            (subprocess, "Popen"),
            (health, "run_bounded"),
            (health, "collect_snapshot"),
            (persistence, "validate_lua"),
        ):
            monkeypatch.setattr(module, attr, forbidden)
        collect_scoped_diagnostics(evidence)
        for path, (raw, info) in zip(paths, before, strict=True):
            assert path.read_bytes() == raw
            assert (path.stat().st_ino, path.stat().st_mtime_ns, path.stat().st_mode) == (
                info.st_ino,
                info.st_mtime_ns,
                info.st_mode,
            )


class TestScopedReport:
    def test_arbitrary_titles_errors_and_paths_never_render(self):
        class ArbitraryObservation:
            title = "/home/private user\n\u2603"
            status = "raw error /secret"
            observed_at = "2000-01-01T00:00:00+00:00"

        with pytest.raises(ValueError, match="^Invalid diagnostics report input$"):
            build_scoped_diagnostics_report(ArbitraryObservation())  # type: ignore[arg-type]

    def test_projection_privacy_and_stale_timestamp(self, installation_pair, monkeypatch):
        evidence, _, _ = installation_pair
        observation = collect_scoped_diagnostics(evidence)
        observation = replace(observation, observed_at="2001-02-03T04:05:06+00:00")

        def forbidden(*args, **kwargs):
            pytest.fail("Report must be pure")

        for module, attr in (
            (builtins, "open"),
            (io, "open"),
            (os, "open"),
            (route_approval, "revalidate"),
            (subprocess, "Popen"),
        ):
            monkeypatch.setattr(module, attr, forbidden)
        report = build_scoped_diagnostics_report(observation, stale=True)
        assert "STALE - previous observation: 2001-02-03T04:05:06+00:00" in report
        assert "Recorded observation" in build_scoped_diagnostics_report(observation)
        assert len(report.encode()) < 4096
        for secret in (
            evidence.config_root,
            evidence.state_root,
            evidence.registry.source_sha256,
            evidence.evidence_hash,
            "PRIVATE-DISPLAY",
            "private  value",
            "\u2603",
            *(r.content_id for r in evidence.routes),
            *(r.file.source_sha256 for r in evidence.routes),
        ):
            assert secret not in report
        for caveat in (
            "not loaded",
            "not write authority",
            "not authentication",
            "not Lua syntax or semantic validation",
            "No journal or split writer is active",
            "does not recheck freshness",
        ):
            assert caveat in report

    @pytest.mark.parametrize(
        "field,value",
        [
            ("status", "/home/private\nraw error \u2603"),
            ("observed_at", "/home/private"),
            ("observed_at", "T/home/private\n\u2603"),
            ("evidence_hash", "private"),
            ("scopes", []),
            ("scopes", ()),
        ],
    )
    def test_injected_metadata_rejected_without_dump(self, installation_pair, field, value):
        observation = collect_scoped_diagnostics(installation_pair[0])
        object.__setattr__(observation, field, value)
        with pytest.raises(ValueError) as error:
            build_scoped_diagnostics_report(observation)
        assert "/home/private" not in str(error.value)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("scope", "appearance"),
            ("version", True),
            ("counts", [0, 0, 0, 0]),
            ("counts", (True, 0, 0, 0)),
            ("counts", (-1, 0, 0, 0)),
            ("counts", (2**30, 0, 0, 0)),
            ("counts", (0, 0, 0, 1)),
            ("content_id", "/private/error"),
        ],
    )
    def test_nested_injection_rejected(self, installation_pair, field, value):
        observation = collect_scoped_diagnostics(installation_pair[0])
        object.__setattr__(observation.scopes[0], field, value)
        with pytest.raises(ValueError):
            build_scoped_diagnostics_report(observation)

    @pytest.mark.parametrize(
        "stamp", ["2000-01-01", "2000-01-01T00:00:00", "2000-01-01T00:00:00+01:00", "x" * 100, True]
    )
    def test_bad_times(self, installation_pair, stamp):
        observation = collect_scoped_diagnostics(installation_pair[0])
        with pytest.raises(ValueError):
            replace(observation, observed_at=stamp)

    def test_scope_shape_boundary(self):
        with pytest.raises(ValueError):
            ScopeObservation(Scope.DISPLAYS, "a" * 64, "b" * 64, (1, 0, 0, 0))
