"""Explicit private stores exclusively inside pytest temporary directories."""

import fcntl
import hashlib
import json
import os
import stat
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from hyprmod.core import route_approval, scoped_review
from hyprmod.core import transaction_store as store
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import Phase, canonical_json
from tests.test_scoped_review import appearance, displays, snapshot
from tests.test_scoped_review import evidence as evidence


@pytest.fixture
def plan(evidence):
    state = Path(evidence.state_root)
    state.mkdir(mode=0o755)
    store.initialize_store(state)
    fresh = route_approval.inspect_installation(
        Path(evidence.registry.path.lexical_path),
        config_root=Path(evidence.config_root),
        state_root=state,
    )
    return scoped_review.build_review(fresh, {Scope.APPEARANCE: appearance("7")})


def prepare(plan, **kwargs):
    return store.prepare_transaction(plan, state_root=Path(plan.evidence.state_root), **kwargs)


def root_for(plan):
    return Path(plan.evidence.state_root) / "attune"


class TestPrivateStore:
    def test_readonly_pending_scan_no_lock_or_provisioning(self, plan, monkeypatch):
        state = Path(plan.evidence.state_root)

        def forbidden(*args, **kwargs):
            pytest.fail("Read-only pending check attempted mutation")

        monkeypatch.setattr(store, "exclusive_store_session", forbidden)
        monkeypatch.setattr(store, "initialize_store", forbidden)
        assert store.refuse_pending_readonly(state) == ()
        assert not (root_for(plan) / "persistence.lock").exists()

    def test_readonly_pending_scan_verifies_selected_and_terminal(self, plan):
        bundle = prepare(plan)
        assert bundle is not None
        state = Path(plan.evidence.state_root)
        with pytest.raises(ValueError, match="Unresolved"):
            store.refuse_pending_readonly(state)
        with store.exclusive_store_session(state) as session:
            session.refuse_other_pending(bundle.intent.transaction_id)
            session.checkpoint(
                bundle,
                replace(bundle.intent, phase=Phase.ABORTED),
                fingerprint=store.verified_fingerprint(bundle),
            )
        assert store.refuse_pending_readonly(state) == (bundle.intent.transaction_id,)
        path = root_for(plan) / "transactions" / bundle.intent.transaction_id / "intent.json"
        path.write_text("{}")
        with pytest.raises(ValueError):
            store.refuse_pending_readonly(state)

    @pytest.mark.parametrize("changed", [(Scope.APPEARANCE,), (Scope.DISPLAYS,), tuple(Scope)])
    def test_prepare_load_isolation_and_pending(self, plan, changed):
        before = snapshot(plan.evidence)
        plan = scoped_review.build_review(
            plan.evidence,
            {
                s: appearance("7") if s is Scope.APPEARANCE else displays("HDMI-A-8")
                for s in changed
            },
        )
        prepared = prepare(plan)
        assert prepared is not None
        assert prepared.intent.phase is Phase.PREPARED
        assert prepared.intent.progress == ()
        assert prepared.intent.changed_scopes == changed
        assert prepared.snapshot.plan == plan
        assert (
            store.load_transaction(Path(plan.evidence.state_root), prepared.intent.transaction_id)
            == prepared
        )
        assert len(prepared.blobs) == 2 + len(changed)
        assert snapshot(plan.evidence) == before
        for path in root_for(plan).rglob("*"):
            assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
        with pytest.raises(ValueError, match="Unresolved"):
            prepare(plan)

    def test_noop_does_not_initialize_or_lock(self, evidence):
        plan = scoped_review.build_review(evidence, {})
        before = snapshot(evidence)
        assert prepare(plan) is None
        assert not Path(evidence.state_root).exists()
        assert snapshot(evidence) == before

    def test_initialized_noop_no_writes(self, plan):
        noop = scoped_review.build_review(plan.evidence, {})
        before = {p: p.stat() for p in root_for(plan).rglob("*")}
        assert prepare(noop) is None
        assert not (root_for(plan) / "persistence.lock").exists()
        assert before == {p: p.stat() for p in root_for(plan).rglob("*")}

    def test_missing_store_and_initialization_stales_review(self, evidence):
        plan = scoped_review.build_review(evidence, {Scope.APPEARANCE: appearance("7")})
        state = Path(evidence.state_root)
        state.mkdir()
        with pytest.raises(ValueError, match="Missing private store"):
            prepare(plan)
        store.initialize_store(state)
        with pytest.raises(ValueError, match="changed"):
            prepare(plan)
        assert list((state / "attune/blobs").iterdir()) == []

    @pytest.mark.parametrize(
        "which", ["attune", "attune/blobs", "attune/snapshots", "attune/transactions"]
    )
    @pytest.mark.parametrize("mode", [0o755, 0o770, 0o600, 0o1700])
    def test_unsafe_directories_never_chmodded(self, plan, which, mode):
        path = Path(plan.evidence.state_root) / which
        previous = stat.S_IMODE(path.stat().st_mode)
        path.chmod(mode)
        try:
            with pytest.raises(ValueError):
                prepare(plan)
            assert stat.S_IMODE(path.stat().st_mode) == mode
        finally:
            path.chmod(previous)

    @pytest.mark.parametrize("mode", [0o777, 0o775, 0o555, 0o600, 0o1700])
    def test_state_root_requirements(self, tmp_path, mode):
        state = tmp_path / "state"
        state.mkdir(mode=mode)
        state.chmod(mode)
        try:
            with pytest.raises(ValueError):
                store.initialize_store(state)
            assert not (state / "attune").exists()
        finally:
            state.chmod(0o700)

    @pytest.mark.parametrize("kind", ["file", "directory", "dangling"])
    def test_git_markers_fail_before_creation(self, tmp_path, kind):
        state = tmp_path / "state"
        state.mkdir()
        marker = tmp_path / ".git"
        if kind == "file":
            marker.write_text("gitdir: /irrelevant")
        elif kind == "directory":
            marker.mkdir()
        else:
            marker.symlink_to(tmp_path / "absent")
        with pytest.raises(ValueError, match="Git"):
            store.initialize_store(state)
        assert not (state / "attune").exists()

    def test_symlink_component(self, plan, tmp_path):
        root = root_for(plan)
        (root / "blobs").rmdir()
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        (root / "blobs").symlink_to(target)
        with pytest.raises(ValueError):
            prepare(plan)
        assert list(target.iterdir()) == []

    @pytest.mark.parametrize("directory", ["blobs", "snapshots", "transactions"])
    def test_git_inside_private_store_is_refused(self, plan, directory):
        (root_for(plan) / directory / ".git").write_text("gitdir: /irrelevant")
        with pytest.raises(ValueError, match="Git"):
            prepare(plan)
        assert not list((root_for(plan) / "transactions").glob("*/intent.json"))

    def test_owned_root_required(self, plan, monkeypatch):
        monkeypatch.setattr(os, "getuid", lambda: 987654)
        with pytest.raises(ValueError):
            prepare(plan)

    @pytest.mark.parametrize("kind", ["mode", "hardlink", "symlink"])
    def test_unsafe_lock(self, plan, kind, tmp_path):
        path = root_for(plan) / "persistence.lock"
        path.write_bytes(b"")
        path.chmod(0o600)
        if kind == "mode":
            path.chmod(0o644)
        elif kind == "hardlink":
            os.link(path, tmp_path / "lock-link")
        else:
            path.unlink()
            path.symlink_to(tmp_path / "absent")
        with pytest.raises((ValueError, OSError)):
            prepare(plan)
        assert list((root_for(plan) / "blobs").iterdir()) == []

    def test_cancellation_and_finite_lock(self, plan, monkeypatch):
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(InterruptedError):
            prepare(plan, cancel_event=cancel)
        lock_path = root_for(plan) / "persistence.lock"
        assert not lock_path.exists()
        lock_path.touch(mode=0o600)
        with lock_path.open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            monkeypatch.setattr(store, "LOCK_TIMEOUT", 0.01)
            with pytest.raises(TimeoutError):
                prepare(plan)
        assert list((root_for(plan) / "transactions").iterdir()) == []

    @pytest.mark.parametrize("kind", ["registry", "scope", "state", "protected"])
    def test_stale_and_explicit_context(self, plan, kind, tmp_path):
        if kind == "state":
            with pytest.raises(ValueError, match="context"):
                store.prepare_transaction(plan, state_root=tmp_path)
            return
        path = Path(plan.evidence.registry.path.resolved_path)
        if kind == "registry":
            path.write_bytes(path.read_bytes() + b"\n")
        elif kind == "scope":
            Path(plan.scopes[1].resolved_path).write_text("foreign")
        else:
            Path(plan.evidence.config_root, "hypr/hyprland.lua").touch()
        with pytest.raises(ValueError):
            prepare(plan)
        assert list((root_for(plan) / "blobs").iterdir()) == []


class TestEvidenceFailures:
    @pytest.mark.parametrize("identical", [False, True])
    def test_checkpoint_never_reuses_or_consumes_existing_scratch(
        self, plan, monkeypatch, identical
    ):
        prepared = prepare(plan)
        assert prepared is not None
        record = replace(prepared.intent, phase=Phase.PUBLISHING)
        token = "b" * 32
        directory = root_for(plan) / "transactions" / prepared.intent.transaction_id
        scratch = directory / f".intent.json.{token}.tmp"
        raw = record.to_json().encode("ascii") if identical else b"unpublished bytes"
        scratch.write_bytes(raw)
        scratch.chmod(0o600)
        inode = scratch.stat().st_ino
        monkeypatch.setattr(store.secrets, "token_hex", lambda _size: token)
        with store.exclusive_store_session(Path(plan.evidence.state_root)) as session:
            with pytest.raises(FileExistsError, match="scratch already exists"):
                session.checkpoint(
                    prepared, record, fingerprint=store.verified_fingerprint(prepared)
                )
        assert scratch.stat().st_ino == inode
        assert scratch.read_bytes() == raw
        assert stat.S_IMODE(scratch.stat().st_mode) == 0o600
        assert (
            store.load_transaction(
                Path(plan.evidence.state_root), prepared.intent.transaction_id
            ).intent.phase
            is Phase.PREPARED
        )

    @pytest.mark.parametrize("name", ["intent", "rollback", "rollback-checkpoint"])
    def test_checkpoint_scratch_is_unpublished_not_authority(self, plan, name):
        prepared = prepare(plan)
        assert prepared is not None
        fingerprint = store.verified_fingerprint(prepared)
        path = (
            root_for(plan)
            / "transactions"
            / prepared.intent.transaction_id
            / ("." + name + ".json." + "c" * 32 + ".tmp")
        )
        path.write_bytes(b"not JSON: unpublished")
        path.chmod(0o600)
        loaded = store.load_transaction(
            Path(plan.evidence.state_root), prepared.intent.transaction_id
        )
        assert loaded == prepared
        assert store.verified_fingerprint(loaded) == fingerprint
        path.write_bytes(b"different unpublished bytes")
        assert store.verified_fingerprint(prepared) == fingerprint
        assert path.read_bytes() == b"different unpublished bytes"

    @pytest.mark.parametrize(
        "kind", ["mode", "hardlink", "symlink", "oversize", "unknown", "orphan-checkpoint"]
    )
    def test_unsafe_or_unknown_scratch_still_conflicts(self, plan, tmp_path, kind):
        prepared = prepare(plan)
        assert prepared is not None
        directory = root_for(plan) / "transactions" / prepared.intent.transaction_id
        path = directory / (".intent.json." + "c" * 32 + ".tmp")
        if kind == "unknown":
            path = directory / ".intent.json.not-reserved.tmp"
        elif kind == "orphan-checkpoint":
            path = directory / "rollback-checkpoint.json"
        path.write_bytes(b"unpublished")
        path.chmod(0o600)
        if kind == "mode":
            path.chmod(0o644)
        elif kind == "hardlink":
            os.link(path, tmp_path / "scratch-hardlink")
        elif kind == "symlink":
            path.unlink()
            path.symlink_to(tmp_path / "absent")
        elif kind == "oversize":
            with path.open("r+b") as stream:
                stream.truncate(store.MAX_RECORD_BYTES + 1)
        with pytest.raises((OSError, ValueError)):
            store.load_transaction(Path(plan.evidence.state_root), prepared.intent.transaction_id)
        assert path.is_symlink() or path.exists()

    @pytest.mark.parametrize("kind", ["partial", "unknown", "extra", "scan-limit"])
    def test_conflicting_journal_entries(self, plan, kind, monkeypatch):
        transactions = root_for(plan) / "transactions"
        if kind == "scan-limit":
            monkeypatch.setattr(store, "MAX_JOURNALS", 0)
        directory = transactions / ("a" * 32 if kind != "unknown" else "unknown")
        directory.mkdir(mode=0o700)
        if kind == "extra":
            (directory / "extra").touch(mode=0o600)
        with pytest.raises(ValueError):
            prepare(plan)
        assert list((root_for(plan) / "blobs").iterdir()) == []

    @pytest.mark.parametrize("kind", ["corrupt", "hardlink", "symlink", "mode", "cross-scope"])
    def test_blob_collision(self, plan, kind, tmp_path):
        review = plan.scopes[0]
        path = root_for(plan) / "blobs" / (review.previous_sha256 + ".lua")
        path.write_bytes(review.previous_text.encode())
        path.chmod(0o600)
        if kind == "corrupt":
            path.write_bytes(b"corrupt")
        elif kind == "hardlink":
            os.link(path, tmp_path / "hardlink")
        elif kind == "symlink":
            path.unlink()
            path.symlink_to(tmp_path / "absent")
        elif kind == "mode":
            path.chmod(0o644)
        else:
            path.write_bytes(plan.scopes[1].previous_text.encode())
        with pytest.raises((ValueError, OSError)):
            prepare(plan)
        assert list((root_for(plan) / "transactions").iterdir()) == []

    def test_identical_blob_reuse(self, plan):
        path = root_for(plan) / "blobs" / (plan.scopes[0].previous_sha256 + ".lua")
        path.write_bytes(plan.scopes[0].previous_text.encode())
        path.chmod(0o600)
        inode = path.stat().st_ino
        assert prepare(plan) is not None
        assert path.stat().st_ino == inode

    @pytest.mark.parametrize(
        "kind", ["blob", "snapshot", "intent", "missing-blob", "missing-snapshot", "missing-intent"]
    )
    def test_readonly_load_rejects_damage(self, plan, kind):
        prepared = prepare(plan)
        assert prepared is not None
        root = root_for(plan)
        paths = {
            "blob": root / "blobs" / (prepared.blobs[0].sha256 + ".lua"),
            "snapshot": root / "snapshots" / (prepared.snapshot.snapshot_id + ".json"),
            "intent": root / "transactions" / prepared.intent.transaction_id / "intent.json",
        }
        path = paths[kind.removeprefix("missing-")]
        if kind.startswith("missing-"):
            path.unlink()
        else:
            path.write_bytes(b"{}")
        before = snapshot(plan.evidence)
        with pytest.raises((ValueError, OSError)):
            store.load_transaction(Path(plan.evidence.state_root), prepared.intent.transaction_id)
        assert snapshot(plan.evidence) == before

    @pytest.mark.parametrize("txid", ["../escape", "A" * 32, "a" * 31, "", "/absolute"])
    def test_transaction_id_paths(self, plan, txid):
        with pytest.raises(ValueError):
            prepare(plan, transaction_id=txid)
        with pytest.raises(ValueError):
            store.load_transaction(Path(plan.evidence.state_root), txid)

    @pytest.mark.parametrize("failure_at", range(1, 18))
    def test_fsync_failure_never_claims_rollback(self, plan, monkeypatch, failure_at):
        before = snapshot(plan.evidence)
        original = os.fsync
        calls = 0

        def fail(fd):
            nonlocal calls
            calls += 1
            if calls == failure_at:
                raise OSError("injected fsync failure")
            original(fd)

        monkeypatch.setattr(os, "fsync", fail)
        with pytest.raises(OSError, match="injected"):
            prepare(plan)
        assert list((root_for(plan) / "blobs").iterdir())
        if failure_at <= 14:
            assert not list((root_for(plan) / "transactions").glob("*/intent.json"))
        else:
            assert list((root_for(plan) / "transactions").glob("*/intent.json"))
        assert snapshot(plan.evidence) == before

    def test_all_evidence_durable_before_intent(self, plan, monkeypatch):
        original = os.fsync
        synced = set()

        def observe(fd):
            path = Path(os.readlink(f"/proc/self/fd/{fd}"))
            if path.name == "intent.json":
                expected = {
                    root_for(plan) / "blobs" / (digest + ".lua")
                    for r in plan.scopes
                    for digest in (r.previous_sha256, r.proposed_sha256)
                }
                assert expected <= synced
                assert root_for(plan) / "blobs" in synced
                assert root_for(plan) / "snapshots" in synced
                assert root_for(plan) / "transactions" in synced
                assert path.parent in synced
            original(fd)
            synced.add(path)

        monkeypatch.setattr(os, "fsync", observe)
        assert prepare(plan) is not None

    def test_drift_before_intent_leaves_orphans_not_intent(self, plan, monkeypatch):
        original = scoped_review.revalidate_review
        calls = 0

        def drift(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                Path(plan.scopes[1].resolved_path).chmod(0o640)
            return original(value)

        monkeypatch.setattr(scoped_review, "revalidate_review", drift)
        with pytest.raises(ValueError):
            prepare(plan)
        assert list((root_for(plan) / "snapshots").iterdir())
        assert not list((root_for(plan) / "transactions").glob("*/intent.json"))

    def test_future_phase_load_is_historical_not_progress_proof(self, plan):
        prepared = prepare(plan)
        assert prepared is not None
        intent = replace(
            prepared.intent, phase=Phase.COMMITTED, progress=prepared.intent.changed_scopes
        )
        path = root_for(plan) / "transactions" / intent.transaction_id / "intent.json"
        path.write_text(intent.to_json())
        loaded = store.load_transaction(Path(plan.evidence.state_root), intent.transaction_id)
        assert loaded.intent.phase is Phase.COMMITTED
        assert Path(plan.scopes[0].resolved_path).read_text() == plan.scopes[0].previous_text
        assert loaded.snapshot.snapshot_id == prepared.snapshot.snapshot_id

    def test_snapshot_filename_hash_checked_even_for_valid_json(self, plan):
        prepared = prepare(plan)
        assert prepared is not None
        path = root_for(plan) / "snapshots" / (prepared.snapshot.snapshot_id + ".json")
        data = json.loads(path.read_text())
        data["plan"]["observed_at"] = "2000-01-01T00:00:00+00:00"
        raw = canonical_json(data).encode()
        assert hashlib.sha256(raw).hexdigest() != prepared.snapshot.snapshot_id
        path.write_bytes(raw)
        with pytest.raises(ValueError, match="filename hash"):
            store.load_transaction(Path(plan.evidence.state_root), prepared.intent.transaction_id)

    def test_load_is_readonly_and_accepts_historical_plan(self, plan, monkeypatch):
        prepared = prepare(plan)
        assert prepared is not None
        Path(plan.scopes[0].resolved_path).write_text(plan.scopes[0].proposed_text)
        original_open = os.open

        def readonly(path, flags, *args, **kwargs):
            assert not flags & (os.O_CREAT | os.O_RDWR | os.O_WRONLY | os.O_TRUNC | os.O_APPEND)
            return original_open(path, flags, *args, **kwargs)

        def forbidden(*args, **kwargs):
            pytest.fail("Read-only load attempted mutation or current-output validation")

        monkeypatch.setattr(os, "open", readonly)
        monkeypatch.setattr(os, "fsync", forbidden)
        monkeypatch.setattr(Path, "mkdir", forbidden)
        monkeypatch.setattr(scoped_review, "revalidate_review", forbidden)
        monkeypatch.setattr(route_approval, "revalidate", forbidden)
        assert (
            store.load_transaction(Path(plan.evidence.state_root), prepared.intent.transaction_id)
            == prepared
        )

    def test_stable_root_binding_ignores_child_activity_not_identity(self, plan):
        state = Path(plan.evidence.state_root)
        binding = store.inspect_store(state)
        (root_for(plan) / "blobs/unreferenced").touch(mode=0o600)
        store.revalidate_store(binding)
        old = state.with_name("old-state")
        state.rename(old)
        state.mkdir(mode=0o755)
        (old / "attune").rename(state / "attune")
        with pytest.raises(ValueError, match="identity"):
            store.revalidate_store(binding)

    def test_cancel_after_snapshot_retains_orphans(self, plan, monkeypatch):
        cancel = threading.Event()
        original = os.fsync

        def cancel_after_snapshot(fd):
            original(fd)
            path = Path(os.readlink(f"/proc/self/fd/{fd}"))
            if path == root_for(plan) / "snapshots":
                cancel.set()

        monkeypatch.setattr(os, "fsync", cancel_after_snapshot)
        with pytest.raises(InterruptedError):
            prepare(plan, cancel_event=cancel)
        assert list((root_for(plan) / "snapshots").iterdir())
        assert not list((root_for(plan) / "transactions").glob("*/intent.json"))

    def test_blob_permission_race_is_rejected(self, plan, monkeypatch):
        original = store.persistence.read_stable

        def change_mode(path, **kwargs):
            raw = original(path, **kwargs)
            if path.parent == root_for(plan) / "blobs":
                path.chmod(0o644)
            return raw

        monkeypatch.setattr(store.persistence, "read_stable", change_mode)
        with pytest.raises(ValueError):
            prepare(plan)
        assert not list((root_for(plan) / "transactions").glob("*/intent.json"))
