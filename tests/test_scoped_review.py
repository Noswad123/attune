"""Inactive group reviews use only explicit, temporary canonical installations."""

import difflib
import os
import socket
import subprocess
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hyprmod.core import config, installation, persistence, route_approval, scoped_config
from hyprmod.core import scoped_review as review
from hyprmod.core.route_approval import InstallationEvidence
from hyprmod.core.scoped_config import LegacyBundle, ScopedConfig, build_text, byte_hash
from hyprmod.core.scopes import SCOPE_BASENAMES, Scope


def appearance(border: str = "2") -> ScopedConfig:
    return ScopedConfig(
        Scope.APPEARANCE,
        {
            "values": {"general:border_size": border},
            "beziers": ["bezier = z, 0, 0, 1, 1", "bezier = unused, 0, 0, 1, 1"],
            "animations": ["animation = windows, 1, 5, z", "animation = fade, 0"],
        },
    )


def displays(disabled: str = "HDMI-A-9") -> ScopedConfig:
    return ScopedConfig(
        Scope.DISPLAYS,
        {"monitors": ["monitor = DP-9, preferred, auto, 1", f"monitor = {disabled}, disable"]},
    )


@pytest.fixture
def evidence(tmp_path: Path) -> InstallationEvidence:
    config_root = tmp_path / "config"
    state_root = tmp_path / "state"
    registry = config_root / "attune/installation.json"
    registry.parent.mkdir(parents=True)
    (config_root / "hypr").mkdir()
    local = tmp_path / "local"
    local.mkdir()
    routes = []
    for model, directory in ((appearance(), config_root / "hypr"), (displays(), local)):
        path = directory / SCOPE_BASENAMES[model.scope]
        path.write_text(build_text(model))
        path.chmod(0o644)
        routes.append(installation.ScopeRoute(model.scope, str(path), str(path)))
    registry.write_text(installation.InstallationRegistry(*routes).to_json())
    registry.chmod(0o600)
    return route_approval.inspect_installation(
        registry, config_root=config_root, state_root=state_root
    )


def snapshot(evidence: InstallationEvidence) -> tuple:
    return tuple(
        (
            path.read_bytes(),
            path.stat().st_ino,
            path.stat().st_mtime_ns,
            path.stat().st_mode,
        )
        for path in (
            Path(evidence.registry.path.resolved_path),
            *(Path(r.file.path.resolved_path) for r in evidence.routes),
        )
    )


class TestGroupReview:
    @pytest.mark.parametrize("changed", [(), (Scope.APPEARANCE,), (Scope.DISPLAYS,), tuple(Scope)])
    def test_changed_sets_preservation_and_exact_diffs(self, evidence, changed):
        before = snapshot(evidence)
        proposals = {
            scope: appearance("7") if scope is Scope.APPEARANCE else displays("HDMI-A-8")
            for scope in changed
        }
        plan = review.build_review(evidence, proposals)
        assert plan.changed_scopes == changed
        assert tuple(r.scope for r in plan.scopes) == tuple(Scope)
        assert datetime.fromisoformat(plan.observed_at).utcoffset() == timedelta(0)
        assert plan.evidence.evidence_hash == evidence.evidence_hash
        assert plan.evidence.registry.source_sha256 == byte_hash(
            Path(evidence.registry.path.resolved_path).read_text()
        )
        for item, route in zip(plan.scopes, evidence.routes, strict=True):
            assert item.lexical_path == route.file.path.lexical_path
            assert item.resolved_path == route.file.path.resolved_path
            assert item.previous_text.encode() == Path(item.resolved_path).read_bytes()
            assert item.previous_sha256 == byte_hash(item.previous_text)
            assert item.proposed_sha256 == byte_hash(item.proposed_text)
            assert item.diff_sha256 == byte_hash(item.diff)
            assert item.previous_content_id == route.content_id
            assert item.previous_content_id != item.previous_sha256
            expected = "".join(
                difflib.unified_diff(
                    item.previous_text.splitlines(keepends=True),
                    item.proposed_text.splitlines(keepends=True),
                    fromfile=f"current/{item.scope.value}",
                    tofile=f"proposed/{item.scope.value}",
                )
            )
            assert item.diff == expected
            assert item.added_lines == sum(s.startswith("+") for s in expected.splitlines()[2:])
            assert item.removed_lines == sum(s.startswith("-") for s in expected.splitlines()[2:])
            if item.scope not in changed:
                assert item.previous_text == item.proposed_text
                assert item.previous_sha256 == item.proposed_sha256
                assert item.previous_content_id == item.proposed_content_id
                assert (item.diff, item.added_lines, item.removed_lines) == ("", 0, 0)
            else:
                assert item.diff.startswith(
                    f"--- current/{item.scope}\n+++ proposed/{item.scope}\n"
                )
        assert review.revalidate_review(plan).review_hash == plan.review_hash
        assert review.build_review(evidence, proposals).review_hash == plan.review_hash
        assert snapshot(evidence) == before
        assert not Path(evidence.state_root).exists()

    def test_explicit_noop_and_record_order(self, evidence):
        plan = review.build_review(
            evidence, {Scope.APPEARANCE: appearance(), Scope.DISPLAYS: displays()}
        )
        assert plan.changed_scopes == ()
        assert all((r.diff, r.added_lines, r.removed_lines) == ("", 0, 0) for r in plan.scopes)
        for item, original in zip(plan.scopes, (appearance(), displays()), strict=True):
            assert scoped_config.read_document(item.proposed_text) == original
        text = plan.scopes[0].proposed_text
        assert (
            text.index('hl.curve("z"')
            < text.index('hl.curve("unused"')
            < text.index("hl.animation")
        )
        assert "not commit or file-load approval" in plan.notice
        assert "No compile, semantic, or write validation" in plan.notice

    def test_deep_immutable_and_timestamp_independent(self, evidence):
        plan = review.build_review(evidence, {})

        def immutable(value):
            assert not isinstance(value, (dict, list, set))
            if is_dataclass(value) and not isinstance(value, type):
                assert hasattr(type(value), "__slots__")
                for field in fields(value):
                    immutable(getattr(value, field.name))
            elif isinstance(value, tuple):
                for member in value:
                    immutable(member)

        immutable(plan)
        with pytest.raises(FrozenInstanceError):
            setattr(plan.scopes[0], "diff", "forged")
        with pytest.raises(FrozenInstanceError):
            setattr(plan, "changed_scopes", ())
        with pytest.raises(AttributeError):
            setattr(plan, "extra", True)
        moved_time = replace(
            plan,
            observed_at="2000-01-01T00:00:00+00:00",
            evidence=replace(plan.evidence, observed_at="2000-01-01T00:00:00+00:00"),
        )
        assert review.revalidate_review(moved_time).review_hash == plan.review_hash

    @pytest.mark.parametrize("kind", ["string-key", "unknown", "cross", "legacy", "foreign"])
    def test_reject_proposal_boundaries(self, evidence, kind):
        proposals = {
            "string-key": {"appearance": appearance()},
            "unknown": {"unknown": appearance()},
            "cross": {Scope.APPEARANCE: displays()},
            "legacy": {Scope.APPEARANCE: LegacyBundle("legacy")},
            "foreign": {Scope.DISPLAYS: "os.execute('no')"},
        }[kind]
        with pytest.raises(ValueError):
            review.build_review(evidence, proposals)

    @pytest.mark.parametrize("kind", ["extra-monitors", "unsupported", "scope-primitive"])
    def test_forged_models_not_candidates(self, evidence, kind):
        model = appearance()
        if kind == "extra-monitors":
            object.__setattr__(model, "monitors", ("monitor = DP-1, disable",))
        elif kind == "unsupported":
            object.__setattr__(model, "values", (("general:layout", "dwindle"),))
        else:
            object.__setattr__(model, "scope", "appearance")
        with pytest.raises(ValueError):
            review.build_review(evidence, {Scope.APPEARANCE: model})


class TestFreshness:
    @pytest.mark.parametrize(
        "kind", ["bytes", "registry-space", "permissions", "git", "protected", "same-byte-link"]
    )
    @pytest.mark.parametrize("recheck", [False, True])
    def test_stale_context(self, evidence, kind, recheck, tmp_path):
        plan = review.build_review(evidence, {})
        path = Path(evidence.routes[0].file.path.lexical_path)
        if kind == "bytes":
            path.write_text(build_text(appearance("7")))
        elif kind == "registry-space":
            registry = Path(evidence.registry.path.lexical_path)
            registry.write_text(registry.read_text() + "\n")
        elif kind == "permissions":
            path.chmod(0o640)
        elif kind == "git":
            Path(evidence.routes[1].file.path.resolved_path).parent.joinpath(".git").mkdir()
        elif kind == "protected":
            path.parent.joinpath("hyprland.lua").symlink_to(path)
        else:
            target = tmp_path / path.name
            path.rename(target)
            path.symlink_to(target)
        with pytest.raises(ValueError):
            if recheck:
                review.revalidate_review(plan)
            else:
                review.build_review(evidence, {})

    @pytest.mark.parametrize("kind", ["foreign", "legacy", "cross", "unreadable"])
    def test_bad_sibling_blocks_review(self, evidence, kind):
        path = Path(evidence.routes[1].file.path.resolved_path)
        if kind == "unreadable":
            path.chmod(0o200)
        else:
            text = {
                "foreign": "return {}\n",
                "legacy": persistence.build_text({}, config.ConfigSections()),
                "cross": build_text(appearance()),
            }[kind]
            path.write_text(text)
        with pytest.raises(ValueError):
            review.build_review(evidence, {Scope.APPEARANCE: appearance("7")})

    def test_revalidate_before_adapter_io(self, evidence, monkeypatch):
        Path(evidence.registry.path.resolved_path).chmod(0o644)

        def forbidden(*args, **kwargs):
            pytest.fail("Adapter read before route revalidation")

        monkeypatch.setattr(persistence, "read_stable", forbidden)
        with pytest.raises(ValueError):
            review.build_review(evidence, {})

    def test_existing_link_retargeted_to_identical_bytes(self, evidence, tmp_path):
        path = Path(evidence.routes[0].file.path.lexical_path)
        first = tmp_path / "first" / path.name
        second = tmp_path / "second" / path.name
        first.parent.mkdir()
        second.parent.mkdir()
        path.rename(first)
        second.write_bytes(first.read_bytes())
        path.symlink_to(first)
        routes = [
            installation.ScopeRoute(
                r.scope, r.file.path.lexical_path, str(Path(r.file.path.lexical_path).resolve())
            )
            for r in evidence.routes
        ]
        registry = Path(evidence.registry.path.lexical_path)
        registry.write_text(installation.InstallationRegistry(*routes).to_json())
        fresh = route_approval.inspect_installation(
            registry, config_root=Path(evidence.config_root), state_root=Path(evidence.state_root)
        )
        plan = review.build_review(fresh, {})
        assert plan.scopes[0].lexical_path == str(path)
        assert plan.scopes[0].resolved_path == str(first)
        path.unlink()
        path.symlink_to(second)
        with pytest.raises(ValueError):
            review.revalidate_review(plan)

    @pytest.mark.parametrize("stage", ["first-read", "second-read", "diff"])
    def test_intermediate_observation_changes(self, evidence, monkeypatch, stage):
        original_read = persistence.read_stable
        original_diff = difflib.unified_diff
        path = Path(evidence.routes[0].file.path.resolved_path)
        calls = 0

        def racing_read(target, **kwargs):
            nonlocal calls
            raw = original_read(target, **kwargs)
            calls += 1
            if (stage == "first-read" and calls == 1) or (stage == "second-read" and calls == 2):
                path.chmod(0o640)
            return raw

        def racing_diff(*args, **kwargs):
            result = original_diff(*args, **kwargs)
            if stage == "diff":
                path.chmod(0o640)
            return result

        monkeypatch.setattr(persistence, "read_stable", racing_read)
        monkeypatch.setattr(difflib, "unified_diff", racing_diff)
        with pytest.raises(ValueError):
            review.build_review(evidence, {})

    def test_read_hash_checked_against_fresh_evidence(self, evidence, monkeypatch):
        monkeypatch.setattr(
            persistence, "read_stable", lambda *a, **k: build_text(appearance("8")).encode()
        )
        with pytest.raises(ValueError, match="bytes differ"):
            review.build_review(evidence, {})

    @pytest.mark.parametrize("stage", ["open", "read"])
    def test_adapter_read_races(self, evidence, monkeypatch, stage):
        original_read = persistence.read_stable
        original_open = os.open
        original_fdopen = os.fdopen
        path = Path(evidence.routes[0].file.path.resolved_path)

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
                path.chmod(0o640)
                return raw

        def racing_open(target, flags, *args, **kwargs):
            if Path(target) == path:
                path.chmod(0o640)
            return original_open(target, flags, *args, **kwargs)

        def read_with_race(target, **kwargs):
            with monkeypatch.context() as patch:
                if stage == "open":
                    patch.setattr(os, "open", racing_open)
                else:
                    patch.setattr(
                        os, "fdopen", lambda *a, **k: RacingStream(original_fdopen(*a, **k))
                    )
                return original_read(target, **kwargs)

        monkeypatch.setattr(persistence, "read_stable", read_with_race)
        with pytest.raises(ValueError, match="changed (before|during) read"):
            review.build_review(evidence, {})


class TestPlanValidation:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("proposed_text", build_text(appearance("8"))),
            ("previous_text", build_text(appearance("8"))),
            ("previous_sha256", "0" * 64),
            ("proposed_sha256", "0" * 64),
            ("previous_content_id", "0" * 64),
            ("proposed_content_id", "0" * 64),
            ("diff_sha256", "0" * 64),
            ("diff", "truncated\n"),
            ("added_lines", 99),
            ("removed_lines", True),
            ("lexical_path", "/elsewhere"),
            ("resolved_path", "/elsewhere"),
            ("scope", "appearance"),
        ],
    )
    @pytest.mark.parametrize(
        "validate", [review.revalidate_review, review.validate_recorded_review]
    )
    def test_forged_scope_fields(self, evidence, field, value, validate):
        plan = review.build_review(evidence, {Scope.APPEARANCE: appearance("7")})
        forged = replace(plan.scopes[0], **{field: value})
        with pytest.raises(ValueError):
            validate(replace(plan, scopes=(forged, plan.scopes[1])))

    @pytest.mark.parametrize(
        "changes",
        [
            {"changed_scopes": ()},
            {"changed_scopes": (Scope.DISPLAYS,)},
            {"changed_scopes": ("appearance",)},
            {"review_hash": "0" * 64},
            {"observed_at": "2020-01-01T00:00:00+01:00"},
            {"scopes": ()},
        ],
    )
    @pytest.mark.parametrize(
        "validate", [review.revalidate_review, review.validate_recorded_review]
    )
    def test_forged_group_fields(self, evidence, changes, validate):
        plan = review.build_review(evidence, {Scope.APPEARANCE: appearance("7")})
        with pytest.raises(ValueError):
            validate(replace(plan, **changes))

    @pytest.mark.parametrize(
        "validate", [review.revalidate_review, review.validate_recorded_review]
    )
    def test_recomputed_fingerprint_does_not_validate_forged_counts(self, evidence, validate):
        plan = review.build_review(evidence, {})
        scopes = (replace(plan.scopes[0], added_lines=10), plan.scopes[1])
        forged = replace(
            plan, scopes=scopes, review_hash=review._review_hash(plan.evidence, scopes, ())
        )
        with pytest.raises(ValueError):
            validate(forged)


class TestLimitsAndIsolation:
    @pytest.mark.parametrize("count", [1100, 5000, 10001])
    def test_large_diff_or_input_refused(self, evidence, count):
        model = ScopedConfig(
            Scope.DISPLAYS, {"monitors": [f"monitor = DP-{i}, disable" for i in range(count)]}
        )
        with pytest.raises(ValueError, match="(exceeds|limits|256 KiB)"):
            review.build_review(evidence, {Scope.DISPLAYS: model})

    def test_oversized_existing_canonical_scope(self, evidence):
        model = ScopedConfig(
            Scope.DISPLAYS, {"monitors": [f"monitor = DP-{i}, disable" for i in range(5000)]}
        )
        path = Path(evidence.routes[1].file.path.resolved_path)
        path.write_text(build_text(model))
        fresh = route_approval.inspect_installation(
            Path(evidence.registry.path.lexical_path),
            config_root=Path(evidence.config_root),
            state_root=Path(evidence.state_root),
        )
        with pytest.raises(ValueError, match="read limit"):
            review.build_review(fresh, {})

    def test_oversized_model_before_reconstruction(self, evidence, monkeypatch):
        model = displays()
        object.__setattr__(model, "monitors", ("x" * (review.MAX_INPUT_BYTES + 1),))

        original = ScopedConfig.payload

        def bounded_payload(candidate):
            if candidate is model:
                pytest.fail("Oversized candidate reached reconstruction")
            return original(candidate)

        monkeypatch.setattr(ScopedConfig, "payload", bounded_payload)
        with pytest.raises(ValueError, match="limits"):
            review.build_review(evidence, {Scope.DISPLAYS: model})

    def test_exact_side_and_diff_bounds(self):
        for text in ("x" * (review.MAX_INPUT_BYTES + 1), "x\n" * (review.MAX_INPUT_LINES + 1)):
            with pytest.raises(ValueError):
                review._bounded(text)
        review._bounded("x" * review.MAX_INPUT_BYTES)
        review._bounded("x\n" * review.MAX_INPUT_LINES)
        with pytest.raises(ValueError, match="Complete scope diff"):
            review._diff("a" * 140000 + "\n", "b" * 140000 + "\n", Scope.APPEARANCE)
        diff, added, removed = review._diff("old", "new", Scope.DISPLAYS)
        assert diff == (
            "--- current/displays\n+++ proposed/displays\n@@ -1 +1 @@\n"
            "-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n"
        )
        assert (added, removed) == (1, 1)

    def test_no_writes_processes_compilation_ipc_or_activation(self, evidence, monkeypatch):
        before = snapshot(evidence)
        original_open = os.open

        def forbidden(*args, **kwargs):
            pytest.fail("Review attempted a side effect")

        def readonly_open(path, flags, *args, **kwargs):
            assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            return original_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", readonly_open)
        for method in ("mkdir", "write_bytes", "write_text", "chmod", "rename", "unlink"):
            monkeypatch.setattr(Path, method, forbidden)
        monkeypatch.setattr(subprocess, "Popen", forbidden)
        monkeypatch.setattr(socket, "socket", forbidden)
        monkeypatch.setattr(persistence, "validate_lua", forbidden)
        monkeypatch.setattr(persistence, "persist_snapshot", forbidden)
        for method in ("write", "mkdir", "replace", "rename", "unlink", "chmod"):
            monkeypatch.setattr(os, method, forbidden)
        plan = review.build_review(evidence, {Scope.APPEARANCE: appearance("7")})
        review.revalidate_review(plan)
        assert snapshot(evidence) == before
        assert not Path(evidence.state_root).exists()
        assert config.managed_path().name == "attune.lua"
        assert persistence.RECORD in persistence.build_text({}, config.ConfigSections())
        with pytest.raises(ValueError):
            persistence.read_document(plan.scopes[0].proposed_text)
