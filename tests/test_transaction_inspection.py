"""Crash-state simulations use explicitly provisioned temporary stores only."""

import builtins
import json
import os
import socket
import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from hyprmod.core import persistence, route_approval, scoped_config, scoped_review
from hyprmod.core import transaction_inspection as inspection
from hyprmod.core import transaction_store as store
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import GroupSnapshot, Phase
from tests.test_scoped_review import appearance, displays, snapshot
from tests.test_scoped_review import evidence as evidence


@pytest.fixture
def make_bundle(evidence):
    state = Path(evidence.state_root)
    state.mkdir(mode=0o755)
    store.initialize_store(state)

    def make(changed=tuple(Scope)):
        fresh = route_approval.inspect_installation(
            Path(evidence.registry.path.lexical_path),
            config_root=Path(evidence.config_root),
            state_root=state,
        )
        plan = scoped_review.build_review(
            fresh,
            {
                scope: appearance("7") if scope is Scope.APPEARANCE else displays("HDMI-A-8")
                for scope in changed
            },
        )
        result = store.prepare_transaction(plan, state_root=state, transaction_id="a" * 32)
        assert result is not None
        return result

    return make


def classify(bundle):
    return inspection.classify_transaction(
        bundle.binding.state_root,
        bundle.intent.transaction_id,
        config_root=Path(bundle.snapshot.plan.evidence.config_root),
    )


def publish(review, proposed=True):
    path = Path(review.resolved_path)
    staged = path.with_suffix(".staged")
    staged.write_text(review.proposed_text if proposed else review.previous_text)
    staged.chmod(0o600)
    staged.replace(path)


def intent_path(bundle):
    return (
        bundle.binding.state_root
        / "attune/transactions"
        / bundle.intent.transaction_id
        / "intent.json"
    )


class TestActualClassification:
    @pytest.mark.parametrize("changed", [(Scope.APPEARANCE,), (Scope.DISPLAYS,), tuple(Scope)])
    @pytest.mark.parametrize("proposed", [(), (Scope.APPEARANCE,), (Scope.DISPLAYS,), tuple(Scope)])
    def test_all_states_and_single_scope_siblings(self, make_bundle, changed, proposed):
        bundle = make_bundle(changed)
        for review in bundle.snapshot.plan.scopes:
            if review.scope in changed and review.scope in proposed:
                publish(review)
        before = snapshot(bundle.snapshot.plan.evidence)
        result = classify(bundle)
        actual = set(changed) & set(proposed)
        expected = (
            "all-prior" if not actual else "all-proposed" if actual == set(changed) else "mixed"
        )
        assert result.status == expected
        assert tuple(s.status for s in result.scopes) == tuple(
            "unchanged" if s not in changed else "proposed" if s in proposed else "prior"
            for s in Scope
        )
        assert snapshot(bundle.snapshot.plan.evidence) == before
        assert result.binding == bundle.binding
        assert result.snapshot_id == bundle.snapshot.snapshot_id
        assert result.review_hash == bundle.snapshot.plan.review_hash
        assert result.prior_evidence_hash == bundle.snapshot.plan.evidence.evidence_hash
        assert len(result.current_evidence_hash or "") == 64
        for observed, review in zip(result.scopes, bundle.snapshot.plan.scopes, strict=True):
            assert observed.prior_sha256 == review.previous_sha256
            assert observed.proposed_sha256 == review.proposed_sha256
            assert observed.current_sha256 in (review.previous_sha256, review.proposed_sha256)
            assert observed.current_content_id in (
                review.previous_content_id,
                review.proposed_content_id,
            )
        with pytest.raises(FrozenInstanceError):
            result.status = inspection.OverallStatus.CONFLICT  # type: ignore[misc]

    @pytest.mark.parametrize("phase", list(Phase))
    @pytest.mark.parametrize("proposed", [False, True])
    def test_advisory_phase_progress_not_history(self, make_bundle, phase, proposed):
        bundle = make_bundle()
        intent = replace(
            bundle.intent,
            phase=phase,
            progress=() if phase is Phase.PREPARED else bundle.intent.changed_scopes,
        )
        intent_path(bundle).write_text(intent.to_json())
        if proposed:
            for review in bundle.snapshot.plan.scopes:
                publish(review)
        assert classify(bundle).status == ("all-proposed" if proposed else "all-prior")

    @pytest.mark.parametrize("proposed", [False, True])
    def test_changed_scope_new_inode_and_safe_mode_allowed(self, make_bundle, proposed):
        bundle = make_bundle((Scope.APPEARANCE,))
        review = bundle.snapshot.plan.scopes[0]
        before = Path(review.resolved_path).stat()
        publish(review, proposed)
        after = Path(review.resolved_path).stat()
        assert after.st_ino != before.st_ino
        assert after.st_mode != before.st_mode
        assert classify(bundle).status == ("all-proposed" if proposed else "all-prior")
        with pytest.raises(route_approval.ApprovalError):
            route_approval.revalidate(bundle.snapshot.plan.evidence)

    @pytest.mark.parametrize("mutation", ["rename", "touch", "mode"])
    def test_unchanged_scope_requires_full_evidence(self, make_bundle, mutation):
        bundle = make_bundle((Scope.APPEARANCE,))
        review = bundle.snapshot.plan.scopes[1]
        path = Path(review.resolved_path)
        if mutation == "rename":
            publish(review, False)
        elif mutation == "touch":
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
        else:
            path.chmod(0o600)
        result = classify(bundle)
        assert result.status == "conflict"
        assert result.scopes[1].status == "conflict"
        assert result.scopes[1].current_sha256 == review.previous_sha256

    def test_noop_never_has_supported_snapshot(self, make_bundle):
        bundle = make_bundle()
        noop = scoped_review.build_review(bundle.snapshot.plan.evidence, {})
        with pytest.raises(ValueError, match="No-op"):
            GroupSnapshot(noop)
        data = json.loads(intent_path(bundle).read_text())
        data["changed_scopes"] = []
        intent_path(bundle).write_text(json.dumps(data))
        assert classify(bundle).status == "conflict"


class TestConflicts:
    @pytest.mark.parametrize(
        "mutation",
        [
            "foreign",
            "missing",
            "wrong-scope",
            "unknown-canonical",
            "tampered-key",
            "mode",
            "hardlink",
            "parent-mode",
            "protected",
            "registry-whitespace",
            "registry-rename",
            "registry-mode",
            "git",
            "state-mode",
            "root-replaced",
        ],
    )
    def test_scope_security_and_context(self, make_bundle, mutation, tmp_path):
        bundle = make_bundle((Scope.APPEARANCE,))
        evidence = bundle.snapshot.plan.evidence
        path = Path(bundle.snapshot.plan.scopes[0].resolved_path)
        registry = Path(evidence.registry.path.resolved_path)
        if mutation == "foreign":
            path.write_text("-- user owned\n")
        elif mutation == "missing":
            path.unlink()
        elif mutation == "wrong-scope":
            path.write_text(scoped_config.build_text(displays()))
        elif mutation == "unknown-canonical":
            path.write_text(scoped_config.build_text(appearance("9")))
        elif mutation == "tampered-key":
            text = path.read_text()
            tampered = text.replace("border_size", "layout")
            assert tampered != text
            path.write_text(tampered)
        elif mutation == "mode":
            path.chmod(0o666)
        elif mutation == "hardlink":
            os.link(path, tmp_path / "alias")
        elif mutation == "parent-mode":
            path.parent.chmod(0o700)
        elif mutation == "protected":
            (Path(evidence.config_root) / "hypr/hyprland.lua").write_text("-- baseline")
        elif mutation == "registry-whitespace":
            registry.write_bytes(registry.read_bytes() + b"\n")
        elif mutation == "registry-rename":
            staged = registry.with_suffix(".staged")
            staged.write_bytes(registry.read_bytes())
            staged.chmod(0o600)
            staged.replace(registry)
        elif mutation == "registry-mode":
            registry.chmod(0o644)
        elif mutation == "git":
            (path.parent / ".git").mkdir()
        elif mutation == "state-mode":
            bundle.binding.state_root.chmod(0o700)
        else:
            root = bundle.binding.state_root / "attune"
            moved = root.with_name("old-attune")
            root.rename(moved)
            root.mkdir(mode=0o700)
            for child in moved.iterdir():
                child.rename(root / child.name)
        assert classify(bundle).status == "conflict"

    @pytest.mark.parametrize("kind", ["file", "parent"])
    @pytest.mark.parametrize("retarget", [False, True])
    def test_symlink_bindings(self, make_bundle, evidence, kind, retarget):
        path = Path(evidence.routes[0].file.path.resolved_path)
        if kind == "file":
            target = path.parent / "target" / path.name
            target.parent.mkdir()
            path.rename(target)
            path.symlink_to(target)
            link = path
        else:
            parent = path.parent
            target = parent.with_name("stow")
            parent.rename(target)
            parent.symlink_to(target, target_is_directory=True)
            link = parent
        registry = Path(evidence.registry.path.resolved_path)
        data = json.loads(registry.read_text())
        data["routes"]["appearance"]["approved_resolved_path"] = str(path.resolve())
        registry.write_text(json.dumps(data))
        bundle = make_bundle()
        publish(bundle.snapshot.plan.scopes[0])
        if retarget:
            original_target = os.readlink(link)
            link.unlink()
            # A different link object and spelling resolves to the very same inode.
            link.symlink_to(str(Path(original_target).parent) + "/./" + Path(original_target).name)
        assert classify(bundle).status == ("conflict" if retarget else "mixed")

    def test_changed_display_parent_identity_cannot_be_refreshed(self, make_bundle):
        bundle = make_bundle()
        review = bundle.snapshot.plan.scopes[1]
        path = Path(review.resolved_path)
        parent = path.parent
        moved = parent.with_name("old-parent")
        parent.rename(moved)
        parent.mkdir()
        (moved / path.name).rename(path)
        assert path.read_text() == review.previous_text
        assert classify(bundle).status == "conflict"

    def test_existing_appearance_git_metadata_change(self, make_bundle, evidence):
        path = Path(evidence.routes[0].file.path.resolved_path)
        marker = path.parent / ".git"
        marker.mkdir()
        bundle = make_bundle()
        assert classify(bundle).status == "all-prior"
        marker.chmod(0o700)
        assert classify(bundle).status == "conflict"

    @pytest.mark.parametrize("context", ["config", "state", "id"])
    def test_explicit_authority_before_output_reads(
        self, make_bundle, tmp_path, monkeypatch, context
    ):
        bundle = make_bundle()

        def forbidden(*args, **kwargs):
            pytest.fail("Mismatching explicit context directed an output read")

        monkeypatch.setattr(route_approval, "inspect_installation", forbidden)
        result = inspection.classify_transaction(
            tmp_path if context == "state" else bundle.binding.state_root,
            "../escape" if context == "id" else bundle.intent.transaction_id,
            config_root=(
                tmp_path if context == "config" else Path(bundle.snapshot.plan.evidence.config_root)
            ),
        )
        assert result.status == "conflict"

    @pytest.mark.parametrize(
        "damage", ["blob", "snapshot", "intent", "missing-blob", "incomplete", "schema", "root"]
    )
    def test_private_failures_never_direct_output_reads(self, make_bundle, monkeypatch, damage):
        bundle = make_bundle()
        root = bundle.binding.state_root / "attune"
        if damage == "blob":
            (root / "blobs" / (bundle.blobs[0].sha256 + ".lua")).write_text("corrupt")
        elif damage == "snapshot":
            (root / "snapshots" / (bundle.snapshot.snapshot_id + ".json")).write_text("{}")
        elif damage == "intent":
            intent_path(bundle).write_text("{}")
        elif damage == "missing-blob":
            (root / "blobs" / (bundle.blobs[0].sha256 + ".lua")).unlink()
        elif damage == "incomplete":
            intent_path(bundle).unlink()
        elif damage == "schema":
            data = json.loads(intent_path(bundle).read_text())
            data["schema"] = 99
            intent_path(bundle).write_text(json.dumps(data))
        else:
            root.rename(root.with_name("missing"))

        def forbidden(*args, **kwargs):
            pytest.fail("Bad private evidence directed an output read")

        monkeypatch.setattr(route_approval, "inspect_installation", forbidden)
        result = classify(bundle)
        assert result.status == "conflict"
        assert all(s.status == "conflict" for s in result.scopes)
        assert result.current_evidence_hash is None

    @pytest.mark.parametrize("mutation", ["current", "intent", "intent-same", "blob-same", "root"])
    def test_mutation_between_observations(self, make_bundle, monkeypatch, mutation):
        bundle = make_bundle()
        original = route_approval.inspect_installation
        calls = 0

        def racing(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                if mutation == "current":
                    publish(bundle.snapshot.plan.scopes[0])
                elif mutation == "intent":
                    intent_path(bundle).write_text(
                        replace(bundle.intent, phase=Phase.PUBLISHING).to_json()
                    )
                elif mutation in ("intent-same", "blob-same"):
                    path = intent_path(bundle)
                    if mutation == "blob-same":
                        path = (
                            bundle.binding.state_root
                            / "attune/blobs"
                            / (bundle.blobs[0].sha256 + ".lua")
                        )
                    staged = path.with_suffix(".staged")
                    staged.write_bytes(path.read_bytes())
                    staged.chmod(0o600)
                    staged.replace(path)
                else:
                    root = bundle.binding.state_root / "attune/blobs"
                    moved = root.with_name("old-blobs")
                    root.rename(moved)
                    root.mkdir(mode=0o700)
                    for child in moved.iterdir():
                        child.rename(root / child.name)
            return original(*args, **kwargs)

        monkeypatch.setattr(route_approval, "inspect_installation", racing)
        result = classify(bundle)
        assert result.status == "conflict"
        assert all(s.status == "conflict" for s in result.scopes)

    def test_errors_bounded(self, make_bundle, monkeypatch):
        bundle = make_bundle()

        def fail(*args, **kwargs):
            raise ValueError("x" * 5000)

        monkeypatch.setattr(store, "load_transaction", fail)
        result = classify(bundle)
        assert result.status == "conflict"
        assert len(result.notes[-1].encode()) <= 1024


class TestReadOnlyBoundary:
    def test_no_mutation_compile_ipc_or_processes(self, make_bundle, monkeypatch):
        bundle = make_bundle((Scope.APPEARANCE,))
        publish(bundle.snapshot.plan.scopes[0])
        before = snapshot(bundle.snapshot.plan.evidence)
        paths = tuple(bundle.binding.state_root.rglob("*"))
        metadata = tuple(
            (info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            for info in (path.lstat() for path in paths)
        )
        real_open = os.open
        real_builtin_open = builtins.open

        def readonly(path, flags, *args, **kwargs):
            assert not flags & (os.O_CREAT | os.O_RDWR | os.O_WRONLY | os.O_TRUNC | os.O_APPEND)
            return real_open(path, flags, *args, **kwargs)

        def readonly_builtin(file, mode="r", *args, **kwargs):
            assert not any(flag in mode for flag in "wax+")
            return real_builtin_open(file, mode, *args, **kwargs)

        def forbidden(*args, **kwargs):
            pytest.fail("Classifier attempted write, compile, IPC, or subprocess")

        monkeypatch.setattr(os, "open", readonly)
        monkeypatch.setattr(builtins, "open", readonly_builtin)
        for name in ("mkdir", "chmod", "unlink", "rename", "replace", "write_text", "write_bytes"):
            monkeypatch.setattr(Path, name, forbidden)
        monkeypatch.setattr(os, "fsync", forbidden)
        monkeypatch.setattr(subprocess, "Popen", forbidden)
        monkeypatch.setattr(socket, "socket", forbidden)
        for name in ("validate_lua", "persist_reviewed", "persist_snapshot", "persist_recovery"):
            monkeypatch.setattr(persistence, name, forbidden)
        monkeypatch.setattr(store, "initialize_store", forbidden)
        monkeypatch.setattr(store, "prepare_transaction", forbidden)
        assert classify(bundle).status == "all-proposed"
        assert snapshot(bundle.snapshot.plan.evidence) == before
        assert metadata == tuple(
            (info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            for info in (path.lstat() for path in paths)
        )
