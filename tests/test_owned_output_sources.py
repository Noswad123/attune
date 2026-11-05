"""Independent Save units refresh sibling evidence only during a new review."""

import os
import subprocess
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from hyprmod.core import bindings, owned_output, persistence, route_approval
from hyprmod.core import input as device
from hyprmod.core import source_bindings as source
from hyprmod.core.config import ConfigSections
from hyprmod.core.focused_ui import ReviewSnapshot

UNITS = (device, bindings, source)
BUNDLE = Path(__file__).resolve().parents[1] / "integrations/hyprland/jdawson/keybindings.tsv"


@pytest.fixture
def roots(tmp_path, monkeypatch):
    config, state = tmp_path / "config", tmp_path / "state"
    (config / "hypr").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    (config / "hypr" / source.BASENAME).write_bytes(BUNDLE.read_bytes())
    (config / "hypr" / device.BASENAME).write_text(device.build_text(device.InputConfig()))
    (config / "hypr" / bindings.BASENAME).write_text(bindings.build_text(bindings.BindingsConfig()))
    return config, state


def observe(unit, roots):
    if unit is source:
        return source.observe(roots[0] / "hypr" / source.BASENAME, roots[1], config_root=roots[0])
    return unit.observe(*roots)


def source_proposal(baseline, revision=1):
    return replace(
        baseline.config,
        bindings=(
            replace(baseline.config.bindings[0], description=f"Retained source draft {revision}"),
            *baseline.config.bindings[1:],
        ),
    )


def proposal(unit, baseline, revision=1):
    if unit is source:
        return source_proposal(baseline, revision)
    if unit is device:
        return device.InputConfig.from_mapping(
            {
                "input:kb_layout": "no" if revision else "us",
                "input:kb_variant": "",
            }
        )
    key = "Q" if revision else "W"
    return bindings.BindingsConfig((f"bind = SUPER, {key}, killactive",))


def save(unit, baseline, proposed):
    result = unit.persist_reviewed(unit.prepare_review(baseline, proposed), proposed)
    assert result.outcome == "saved", result.error
    if result.baseline is None:
        pytest.fail("Save lacks verified baseline")
    return result.baseline


def replace_bytes(path, raw):
    replacement = path.with_name(path.name + ".replacement")
    replacement.write_bytes(raw)
    replacement.chmod(0o600)
    replacement.replace(path)


class TestSequentialSaves:
    @pytest.mark.parametrize(
        "first,second",
        [
            (device, bindings),
            (bindings, device),
            (device, source),
            (source, device),
            (bindings, source),
            (source, bindings),
        ],
    )
    @pytest.mark.parametrize("worker", [False, True])
    def test_retained_source_and_draft_after_sibling_save(self, roots, first, second, worker):
        initial = observe(second, roots)
        original = save(second, initial, proposal(second, initial, revision=0))
        first_baseline = observe(first, roots)
        retained = proposal(second, original)
        original_json = original.to_json()
        saved_first = save(first, first_baseline, proposal(first, first_baseline))
        current = observe(second, roots)
        assert current != original and current.protected != original.protected
        assert current.proof == original.proof
        assert second.same_source(original, current)
        review = (second.run_prepare_review if worker else second.prepare_review)(
            original, retained
        )
        assert review.baseline == current
        assert review.proposed == retained
        assert original.to_json() == original_json
        assert second.same_source(original, review.baseline)
        result = second.persist_reviewed(review, retained)
        assert result.outcome == "saved", result.error
        assert result.baseline == observe(second, roots)
        assert first.same_source(saved_first, observe(first, roots))
        assert observe(first, roots).text == saved_first.text

    @pytest.mark.parametrize("unit", UNITS)
    def test_visual_v1_physical_save_refreshes_protection(self, roots, unit):
        visual = roots[0] / "hypr/attune.lua"
        before_text = persistence.build_text({"general:gaps_in": "5"}, ConfigSections())
        visual.write_text(before_text)
        original = observe(unit, roots)
        retained = proposal(unit, original)
        after_text = persistence.build_text({"general:gaps_in": "9"}, ConfigSections())
        persistence.persist_snapshot(ReviewSnapshot(visual, before_text, after_text, visual))
        assert visual.read_text() == after_text and before_text != after_text
        current = observe(unit, roots)
        assert unit.same_source(original, current)
        assert original.protected != current.protected
        review = unit.run_prepare_review(original, retained)
        assert review.baseline == current
        result = unit.persist_reviewed(review, retained)
        assert result.outcome == "saved", result.error
        assert visual.read_text() == after_text

    @pytest.mark.parametrize("unit", [device, bindings])
    def test_sibling_first_save_absent_leaf(self, roots, unit):
        sibling = bindings if unit is device else device
        target = roots[0] / "hypr" / sibling.BASENAME
        target.unlink()
        original = observe(unit, roots)
        sibling_before = observe(sibling, roots)
        save(sibling, sibling_before, proposal(sibling, sibling_before))
        review = unit.run_prepare_review(original, proposal(unit, original))
        assert unit.same_source(original, review.baseline)
        assert review.baseline == observe(unit, roots)
        assert unit.persist_reviewed(review, review.proposed).outcome == "saved"

    def test_source_stow_parent_and_actual_config_protection(self, roots, tmp_path):
        config, state = roots
        stow = tmp_path / "stow"
        stow.mkdir()
        selected = stow / source.BASENAME
        installed = config / "hypr" / source.BASENAME
        installed.rename(selected)
        installed.symlink_to(selected)
        sibling = stow / device.BASENAME
        sibling.write_text(device.build_text(device.InputConfig()))
        (config / "hypr" / device.BASENAME).unlink()
        (config / "hypr" / device.BASENAME).symlink_to(sibling)
        original = source.observe(selected, state, config_root=config)
        first = device.observe(*roots)
        save(device, first, proposal(device, first))
        current = source.observe(selected, state, config_root=config)
        assert original.installed_route == current.installed_route
        changed = [p.lexical_path for p, q in zip(original.protected, current.protected) if p != q]
        assert changed == [str(config / "hypr" / device.BASENAME), str(sibling)]
        assert source.same_source(original, current)
        reviewed = source.run_prepare_review(original, source_proposal(original))
        assert reviewed.baseline == current
        result = source.persist_reviewed(reviewed, reviewed.proposed)
        assert result.outcome == "saved", result.error


class TestStrictSource:
    @pytest.mark.parametrize("unit", UNITS)
    @pytest.mark.parametrize(
        "critical",
        [
            "hypr/hyprland.lua",
            "hypr/hyprland.conf",
            "hypr/keybindings-bridge.lua",
            "attune/installation.json",
        ],
    )
    def test_same_bytes_critical_replacement_cannot_refresh(self, roots, unit, critical):
        path = roots[0] / critical
        path.parent.mkdir(exist_ok=True)
        path.write_text("opaque authored bytes\n")
        original = observe(unit, roots)
        replace_bytes(path, path.read_bytes())
        current = observe(unit, roots)
        assert not unit.same_source(original, current)
        with pytest.raises(ValueError, match="changed"):
            unit.prepare_review(original, proposal(unit, original))

    @pytest.mark.parametrize("unit", UNITS)
    @pytest.mark.parametrize("change", ["own-inode", "own-content", "git", "parent"])
    def test_own_source_is_exact(self, roots, tmp_path, unit, change):
        original = observe(unit, roots)
        target = Path(original.resolved_path)
        if change == "own-inode":
            replace_bytes(target, target.read_bytes())
        elif change == "own-content":
            replace_bytes(target, unit.build_text(proposal(unit, original)).encode())
        elif change == "git":
            (roots[0] / ".git").mkdir()
        else:
            parent = target.parent
            parent.rename(tmp_path / "old-hypr")
            parent.mkdir()
            for path in (tmp_path / "old-hypr").iterdir():
                path.rename(parent / path.name)
        current = observe(unit, roots)
        assert not unit.same_source(original, current)
        with pytest.raises(ValueError, match="changed"):
            unit.run_prepare_review(original, proposal(unit, original))

    @pytest.mark.parametrize("unit", UNITS)
    def test_new_alias_after_sibling_save_blocks_fresh_review(self, roots, unit):
        sibling = bindings if unit is device else device
        original = observe(unit, roots)
        first = observe(sibling, roots)
        save(sibling, first, proposal(sibling, first))
        protected = roots[0] / "hypr" / sibling.BASENAME
        protected.unlink()
        protected.symlink_to(original.resolved_path)
        with pytest.raises(ValueError, match="collid|alias"):
            unit.prepare_review(original, proposal(unit, original))

    @pytest.mark.parametrize("unit", UNITS)
    @pytest.mark.parametrize(
        "when", ["before-save", "under-lock", "before-publish", "after-publish"]
    )
    def test_review_publication_never_refreshes_siblings(self, roots, unit, when, monkeypatch):
        baseline = observe(unit, roots)
        retained = proposal(unit, baseline)
        review = unit.prepare_review(baseline, retained)
        sibling = bindings if unit is device else device
        target = Path(baseline.resolved_path)
        protected = roots[0] / "hypr" / sibling.BASENAME

        def change():
            replace_bytes(protected, protected.read_bytes())

        if when == "before-save":
            change()
        elif when == "under-lock":
            flock = owned_output.fcntl.flock

            def acquire(*args):
                flock(*args)
                change()

            monkeypatch.setattr(owned_output.fcntl, "flock", acquire)
        else:
            atomic = persistence._atomic_write

            def write(path, content, **kwargs):
                if path == target and when == "before-publish":
                    change()
                atomic(path, content, **kwargs)
                if path == target and when == "after-publish":
                    change()

            monkeypatch.setattr(persistence, "_atomic_write", write)
        result = unit.persist_reviewed(review, retained)
        assert result.outcome == "failed" and result.baseline is None
        assert result.may_have_written is (when == "after-publish")
        if when != "after-publish":
            assert target.read_text() == baseline.text

    def test_offline_source_installed_route_stays_exact(self, roots, tmp_path):
        selected = tmp_path / source.BASENAME
        selected.write_bytes(BUNDLE.read_bytes())
        original = source.observe(selected, roots[1], config_root=roots[0])
        installed = roots[0] / "hypr" / source.BASENAME
        replace_bytes(installed, installed.read_bytes())
        current = source.observe(selected, roots[1], config_root=roots[0])
        assert original.proof == current.proof
        assert not source.same_source(original, current)
        with pytest.raises(ValueError, match="changed"):
            source.prepare_review(original, source_proposal(original))


class TestProtectionComparison:
    @pytest.mark.parametrize(
        "basename",
        [
            "attune.lua",
            "attune-appearance.lua",
            "attune-displays.lua",
            "attune-bindings.lua",
            "attune-input.lua",
            "keybindings.tsv",
        ],
    )
    def test_known_leaf_changes_only(self, tmp_path, basename):
        path = tmp_path / basename
        absent = (route_approval._resolve(path, absent=True),)
        path.write_text("opaque sibling data")
        present = (route_approval._resolve(path),)
        assert owned_output.same_protection(absent, present)
        replace_bytes(path, b"other sibling data")
        replaced = (route_approval._resolve(path),)
        assert owned_output.same_protection(present, replaced)
        assert owned_output.same_protection(replaced, absent)

    @pytest.mark.parametrize(
        "change",
        ["new-ancestor", "symlink-inode", "symlink-target", "mode", "hardlink", "directory"],
    )
    def test_non_leaf_or_unsafe_leaf_changes_refuse(self, tmp_path, change):
        path = tmp_path / device.BASENAME
        if change == "new-ancestor":
            path = tmp_path / "new-parent" / device.BASENAME
        elif change.startswith("symlink"):
            destination = tmp_path / "destination"
            destination.write_text("opaque")
            path.symlink_to(destination)
        else:
            path.write_text("opaque")
        before = (route_approval._resolve(path, absent=True),)
        if change == "new-ancestor":
            path.parent.mkdir()
            path.write_text("opaque")
        elif change.startswith("symlink"):
            old = tmp_path / "old-link"
            path.rename(old)
            destination = tmp_path / ("destination" if change == "symlink-inode" else "other")
            if change == "symlink-target":
                destination.write_text("opaque")
            path.symlink_to(destination)
        elif change == "mode":
            path.chmod(0o700)
        elif change == "hardlink":
            os.link(path, tmp_path / "alias")
        else:
            path.unlink()
            path.mkdir()
        after = (route_approval._resolve(path, absent=True),)
        assert not owned_output.same_protection(before, after)

    def test_lexical_main_name_not_resolved_sibling_name(self, tmp_path):
        target = tmp_path / device.BASENAME
        target.write_text("opaque")
        main = tmp_path / "hyprland.lua"
        main.symlink_to(target)
        before = (route_approval._resolve(main),)
        replace_bytes(target, b"opaque")
        after = (route_approval._resolve(main),)
        assert not owned_output.same_protection(before, after)

    @pytest.mark.parametrize("unit", [device, bindings])
    def test_protected_dto_is_strict_immutable_and_context_bound(self, roots, unit):
        baseline = observe(unit, roots)
        assert type(baseline.protected) is tuple
        assert not any(
            fact.path == proof.resolved_path
            for proof in baseline.protected
            for fact in baseline.proof.facts
        )
        for invalid in (list(baseline.protected), (), baseline.protected[::-1]):
            with pytest.raises(ValueError):
                replace(baseline, protected=invalid)
        data = asdict(baseline)
        data["protected"] = {}
        with pytest.raises(ValueError):
            type(baseline).from_json(route_approval._json(data))

    @pytest.mark.parametrize("unit", UNITS)
    def test_worker_echo_and_same_source_are_pure(self, roots, unit, monkeypatch):
        original = observe(unit, roots)
        sibling = bindings if unit is device else device
        first = observe(sibling, roots)
        save(sibling, first, proposal(sibling, first))
        current = observe(unit, roots)
        retained = proposal(unit, original)

        def refuse(*args, **kwargs):
            pytest.fail("Parent must not re-observe during child response echo")

        monkeypatch.setattr(unit, "observe", refuse)
        assert unit.same_source(original, current)
        review = unit.run_prepare_review(original, retained)
        assert review.baseline == current

    @pytest.mark.parametrize("unit", UNITS)
    @pytest.mark.parametrize("change", ["own-inode", "critical-protection"])
    def test_worker_echo_refuses_changed_own_or_critical_evidence(
        self, roots, unit, change, monkeypatch
    ):
        main = roots[0] / "hypr/hyprland.lua"
        main.write_text("authored bytes\n")
        original = observe(unit, roots)
        retained = proposal(unit, original)
        path = Path(original.resolved_path) if change == "own-inode" else main
        replace_bytes(path, path.read_bytes())
        current = observe(unit, roots)
        different_review = unit.prepare_review(current, retained)
        monkeypatch.setattr(
            unit.health,
            "run_bounded",
            lambda *a, **k: subprocess.CompletedProcess([], 0, different_review.to_json(), ""),
        )

        def refuse(*args, **kwargs):
            pytest.fail("Worker echo must compare evidence without filesystem observation")

        monkeypatch.setattr(unit, "observe", refuse)
        with pytest.raises(ValueError, match="different review request"):
            unit.run_prepare_review(original, retained)
