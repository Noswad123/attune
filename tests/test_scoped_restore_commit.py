"""Explicit restore commits and fault boundaries, exclusively in temporary state."""

import fcntl
import os
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest

from hyprmod.core import installation, persistence, route_approval, scoped_review
from hyprmod.core import scoped_restore as restore
from hyprmod.core import transaction_publication as publication
from hyprmod.core import transaction_store as store
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import Phase
from tests.test_scoped_review import appearance, displays, snapshot
from tests.test_scoped_review import evidence as evidence
from tests.test_transaction_store import plan as plan


def current(plan):
    return route_approval.inspect_installation(
        Path(plan.evidence.registry.path.lexical_path),
        config_root=Path(plan.evidence.config_root),
        state_root=Path(plan.evidence.state_root),
    )


def publish(plan):
    return publication.publish_reviewed(
        plan,
        config_root=Path(plan.evidence.config_root),
        state_root=Path(plan.evidence.state_root),
    )


@pytest.fixture
def source(plan, request, monkeypatch):
    if getattr(request, "param", None) == "links":
        routes = []
        for review in plan.scopes:
            lexical = Path(review.lexical_path)
            target = lexical.parent / "stow" / lexical.name
            target.parent.mkdir(exist_ok=True)
            lexical.rename(target)
            lexical.symlink_to(Path("stow") / target.name)
            routes.append(installation.ScopeRoute(review.scope, str(lexical), str(target)))
        Path(plan.evidence.registry.path.resolved_path).write_text(
            installation.InstallationRegistry(*routes).to_json()
        )
    proposal = scoped_review.build_review(
        current(plan),
        {Scope.APPEARANCE: appearance("7"), Scope.DISPLAYS: displays("HDMI-A-8")},
    )
    result = publish(proposal)
    assert result.outcome == "committed", result
    state = Path(plan.evidence.state_root)
    if getattr(request, "param", Phase.COMMITTED) is Phase.ABORTED:
        # A real failed publication, closed by ordinary recovery, supplies ABORTED history.
        proposal = scoped_review.build_review(
            current(plan),
            {Scope.APPEARANCE: appearance("8"), Scope.DISPLAYS: displays("HDMI-A-6")},
        )

        def fail_compile(_text):
            raise ValueError("source compiler failure")

        with monkeypatch.context() as patch:
            patch.setattr(persistence, "validate_lua", fail_compile)
            failed = publish(proposal)
        assert failed.outcome == "failed" and failed.transaction_id is not None
        review = publication.review_recovery(
            state,
            failed.transaction_id,
            "abandon",
            config_root=Path(plan.evidence.config_root),
        )
        result = publication.commit_recovery(review)
        assert result.outcome == "aborted", result
    assert result.transaction_id is not None
    source = store.load_transaction(state, result.transaction_id)
    later = scoped_review.build_review(
        current(plan),
        {Scope.APPEARANCE: appearance("9"), Scope.DISPLAYS: displays("HDMI-A-7")},
    )
    assert publish(later).outcome == "committed"
    return source


def draft(source, scope=Scope.APPEARANCE, side="prior"):
    plan = source.snapshot.plan
    return restore.prepare_restore(
        Path(plan.evidence.config_root),
        Path(plan.evidence.state_root),
        source.intent.transaction_id,
        scope,
        side,
    )


def source_path(source, kind):
    root = Path(source.snapshot.plan.evidence.state_root) / "attune"
    if kind == "intent":
        return root / "transactions" / source.intent.transaction_id / "intent.json"
    if kind == "snapshot":
        return root / "snapshots" / (source.snapshot.snapshot_id + ".json")
    if kind == "selected-blob":
        digest = source.snapshot.plan.scopes[0].previous_sha256
        blob = next(b for b in source.blobs if b.scope is Scope.APPEARANCE and b.sha256 == digest)
    else:
        blob = next(b for b in source.blobs if b.scope is Scope.DISPLAYS)
    return root / "blobs" / (blob.sha256 + ".lua")


def replace_identical(path):
    stage = path.with_suffix(".replacement")
    stage.write_bytes(path.read_bytes())
    stage.chmod(path.stat().st_mode)
    stage.replace(path)


def assert_clean(result):
    assert result.outcome == "failed", result
    assert result.transaction_id is None
    assert not result.pending
    assert not result.scope_may_have_changed
    assert not result.journal_may_have_changed


class TestCommit:
    @pytest.mark.parametrize("noop", [False, True])
    def test_source_hook_owns_lock_before_writes_and_exit(self, source, monkeypatch, noop):
        if noop:
            assert restore.commit_restore(draft(source)).outcome == "committed"
        review = draft(source)
        assert review.plan.changed_scopes == (() if noop else (Scope.APPEARANCE,))
        state = Path(review.state_root)
        lock_path = state / "attune/persistence.lock"
        before = snapshot(review.plan.evidence)
        ids = store.list_transaction_ids(state)
        observations = []
        compilations = []
        original_publish = publication.publish_reviewed
        original_compile = persistence.validate_lua

        def compile(text):
            original_compile(text)
            compilations.append(text)

        def publish_checked(plan, *, expected_source, **kwargs):
            def locked_source():
                with lock_path.open("rb") as independent_lock:
                    with pytest.raises(BlockingIOError):
                        fcntl.flock(independent_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                expected_source()
                phases = {
                    txid: store.load_transaction(state, txid).intent.phase
                    for txid in store.list_transaction_ids(state)
                }
                observations.append((snapshot(plan.evidence), phases, len(compilations)))

            return original_publish(plan, expected_source=locked_source, **kwargs)

        monkeypatch.setattr(publication, "publish_reviewed", publish_checked)
        monkeypatch.setattr(persistence, "validate_lua", compile)
        result = restore.commit_restore(review)
        assert result.outcome == ("no-op" if noop else "committed"), result
        assert len(observations) > 1
        initial_outputs, initial_phases, initial_compiles = observations[0]
        assert initial_outputs == before
        assert tuple(initial_phases) == ids
        assert initial_compiles == 0
        final_outputs, final_phases, final_compiles = observations[-1]
        assert final_outputs == snapshot(review.plan.evidence)
        assert final_compiles == (2 if noop else 4)
        for index, item in enumerate(review.plan.scopes, 1):
            assert final_outputs[index][0] == item.proposed_text.encode()
            if item.scope not in review.plan.changed_scopes:
                assert final_outputs[index] == before[index]
        if noop:
            assert tuple(final_phases) == ids
        else:
            if result.transaction_id is None:
                pytest.fail("Changed restore must return a new transaction ID")
            assert set(final_phases) - set(ids) == {result.transaction_id}
            assert final_phases[result.transaction_id] is Phase.COMMITTED

    @pytest.mark.parametrize(
        "kind", ["source-scopes", "prior-kinds", "source-identity", "descriptor-counts"]
    )
    def test_mutable_history_rejected_before_json_and_delegation(self, source, monkeypatch, kind):
        review = draft(source)
        if kind == "source-scopes":
            object.__setattr__(
                review.source_snapshot.plan, "scopes", list(review.source_snapshot.plan.scopes)
            )
        elif kind == "prior-kinds":
            object.__setattr__(
                review.source_snapshot, "prior_kinds", list(review.source_snapshot.prior_kinds)
            )
        elif kind == "source-identity":
            fact = review.source_snapshot.plan.evidence.routes[0].file.path.facts[0]
            object.__setattr__(fact, "identity", list(fact.identity))
        else:
            object.__setattr__(
                review.selected_descriptor, "counts", list(review.selected_descriptor.counts)
            )
        publisher = Mock(side_effect=AssertionError("Mutable draft reached publisher"))
        serialize = Mock(side_effect=AssertionError("Mutable draft reached JSON normalization"))
        monkeypatch.setattr(publication, "publish_reviewed", publisher)
        monkeypatch.setattr(restore.ScopedRestoreDraft, "to_json", serialize)
        assert_clean(restore.commit_restore(review))
        serialize.assert_not_called()
        publisher.assert_not_called()

    @pytest.mark.parametrize("source", ["links"], indirect=True)
    @pytest.mark.parametrize("scope", list(Scope))
    def test_lexical_symlinks_preserved(self, source, scope):
        review = draft(source, scope)
        links = {
            Path(r.lexical_path): (Path(r.lexical_path).lstat(), os.readlink(r.lexical_path))
            for r in review.plan.scopes
        }
        assert restore.commit_restore(review).outcome == "committed"
        assert links == {p: (p.lstat(), os.readlink(p)) for p in links}

    @pytest.mark.parametrize("source", [Phase.COMMITTED, Phase.ABORTED], indirect=True)
    @pytest.mark.parametrize("scope", list(Scope))
    @pytest.mark.parametrize("side", ["prior", "proposed"])
    def test_new_transaction_scope_isolation_and_reverse(self, source, scope, side):
        review = draft(source, scope, side)
        state = Path(review.state_root)
        fingerprint = store.verified_fingerprint_digest(source)
        before = snapshot(review.plan.evidence)
        result = restore.commit_restore(review)
        assert result.outcome == "committed", result
        assert result.transaction_id not in (None, source.intent.transaction_id)
        assert not result.pending and result.scope_may_have_changed
        assert result.journal_may_have_changed
        after = snapshot(review.plan.evidence)
        for index, item in enumerate(review.plan.scopes, 1):
            assert after[index][0] == item.proposed_text.encode()
            if item.scope is not scope:
                assert after[index] == before[index]
        assert after[0] == before[0]
        assert (
            store.verified_fingerprint_digest(
                store.load_transaction(state, source.intent.transaction_id)
            )
            == fingerprint
        )
        restored = store.load_transaction(state, result.transaction_id)
        reverse = draft(restored, scope, "prior")
        reversed_result = restore.commit_restore(reverse)
        assert reversed_result.outcome == "committed", reversed_result
        assert reversed_result.transaction_id not in (
            result.transaction_id,
            source.intent.transaction_id,
        )
        assert (
            Path(next(r for r in review.plan.scopes if r.scope is scope).resolved_path).read_bytes()
            == before[1 if scope is Scope.APPEARANCE else 2][0]
        )

    def test_noop_has_no_journals_or_stages(self, source):
        first = restore.commit_restore(draft(source))
        assert first.outcome == "committed"
        review = draft(source)
        assert not review.plan.changed_scopes
        root = Path(review.state_root) / "attune"
        before = {
            p: (p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_mode)
            for p in root.rglob("*")
            if p.is_file()
        }
        outputs = snapshot(review.plan.evidence)
        result = restore.commit_restore(review)
        assert result == publication.PublicationResult(None, "no-op", False, False, False)
        assert outputs == snapshot(review.plan.evidence)
        assert before == {
            p: (p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_mode)
            for p in root.rglob("*")
            if p.is_file()
        }

    @pytest.mark.parametrize(
        "kind",
        [
            "intent",
            "snapshot",
            "selected-blob",
            "unselected-blob",
            "registry",
            "selected",
            "sibling",
        ],
    )
    @pytest.mark.parametrize("noop", [False, True])
    def test_same_byte_replacement_refused(self, source, kind, noop):
        if noop:
            assert restore.commit_restore(draft(source)).outcome == "committed"
        review = draft(source)
        if kind in ("intent", "snapshot", "selected-blob", "unselected-blob"):
            path = source_path(source, kind)
        elif kind == "registry":
            path = Path(review.plan.evidence.registry.path.resolved_path)
        else:
            path = Path(review.plan.scopes[0 if kind == "selected" else 1].resolved_path)
        replace_identical(path)
        assert_clean(restore.commit_restore(review))

    @pytest.mark.parametrize(
        "kind", ["type", "mutable", "nested", "route-type", "digest", "roots", "diff", "goal"]
    )
    def test_invalid_original_draft(self, source, kind, tmp_path):
        review = draft(source)
        if kind == "type":
            review = object()
        elif kind == "mutable":
            object.__setattr__(review.plan, "scopes", list(review.plan.scopes))
        elif kind == "nested":
            fact = review.plan.evidence.routes[0].file.path.facts[0]
            object.__setattr__(fact, "identity", list(fact.identity))
        elif kind == "route-type":
            object.__setattr__(review.plan.evidence.routes[0], "scope", "appearance")
        elif kind == "digest":
            review = replace(review, source_private_digest="0" * 64)
        elif kind == "roots":
            object.__setattr__(review, "config_root", str(tmp_path))
        else:
            item = review.plan.scopes[0]
            object.__setattr__(item, "diff" if kind == "diff" else "proposed_text", "forged")
        assert_clean(restore.commit_restore(cast(restore.ScopedRestoreDraft, review)))

    def test_daemon_cancel_and_lock_contention(self, source, monkeypatch):
        review = draft(source)
        results = []
        worker = threading.Thread(
            target=lambda: results.append(restore.commit_restore(review)), daemon=True
        )
        worker.start()
        worker.join()
        assert_clean(results[0])
        event = threading.Event()
        event.set()
        assert_clean(restore.commit_restore(review, cancel_event=event))
        monkeypatch.setattr(store, "LOCK_TIMEOUT", 0.01)
        with (Path(review.state_root) / "attune/persistence.lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert_clean(restore.commit_restore(review))

    @pytest.mark.parametrize("noop", [False, True])
    @pytest.mark.parametrize("kind", ["pending", "corrupt"])
    def test_other_evidence_blocks(self, source, noop, kind):
        if noop:
            assert restore.commit_restore(draft(source)).outcome == "committed"
        review = draft(source)
        if kind == "pending":
            proposal = scoped_review.build_review(
                current(source.snapshot.plan), {Scope.DISPLAYS: displays("HDMI-A-2")}
            )
            assert (
                store.prepare_transaction(proposal, state_root=Path(review.state_root)) is not None
            )
        else:
            (Path(review.state_root) / "attune/transactions" / ("f" * 32)).mkdir(mode=0o700)
        assert_clean(restore.commit_restore(review))

    @pytest.mark.parametrize("noop", [False, True])
    @pytest.mark.parametrize("kind", ["source", "current", "pending"])
    def test_compiler_drift(self, source, monkeypatch, noop, kind):
        if noop:
            assert restore.commit_restore(draft(source)).outcome == "committed"
        review = draft(source)
        injected = False

        def compile(_text):
            nonlocal injected
            if injected:
                return
            injected = True
            if kind == "source":
                replace_identical(source_path(source, "intent"))
            elif kind == "current":
                replace_identical(Path(review.plan.scopes[1].resolved_path))
            else:
                (Path(review.state_root) / "attune/transactions" / ("f" * 32)).mkdir(mode=0o700)

        monkeypatch.setattr(persistence, "validate_lua", compile)
        result = restore.commit_restore(review)
        assert injected and result.outcome == "failed", result
        assert not result.scope_may_have_changed
        assert result.journal_may_have_changed == (not noop)
        assert result.pending == (not noop)

    @pytest.mark.parametrize("point", ["prepare", "sync", "final-read", "rename", "terminal"])
    def test_source_drift_at_writer_boundaries(self, source, monkeypatch, point):
        review = draft(source)
        injected = False

        def tamper():
            nonlocal injected
            if not injected:
                injected = True
                replace_identical(source_path(source, "intent"))

        original_prepare = store.StoreSession.prepare
        original_sync = store.StoreSession.sync_evidence
        original_read = persistence.read_stable
        original_replace = os.replace
        original_checkpoint = store.StoreSession.checkpoint
        reads = 0

        def prepare(session, *args, **kwargs):
            result = original_prepare(session, *args, **kwargs)
            if point == "prepare":
                tamper()
            return result

        def sync(session, bundle):
            result = original_sync(session, bundle)
            if point == "sync":
                tamper()
            return result

        def read(path, **kwargs):
            nonlocal reads
            result = original_read(path, **kwargs)
            if Path(path).name.startswith(".attune-"):
                reads += 1
                if point == "final-read" and reads == 2:
                    tamper()
            return result

        def rename(old, new):
            result = original_replace(old, new)
            if point == "rename" and Path(new) == Path(review.plan.scopes[0].resolved_path):
                tamper()
            return result

        def checkpoint(session, bundle, record, **kwargs):
            result = original_checkpoint(session, bundle, record, **kwargs)
            if point == "terminal" and record.phase is Phase.COMMITTED:
                tamper()
            return result

        monkeypatch.setattr(store.StoreSession, "prepare", prepare)
        monkeypatch.setattr(store.StoreSession, "sync_evidence", sync)
        monkeypatch.setattr(persistence, "read_stable", read)
        monkeypatch.setattr(os, "replace", rename)
        monkeypatch.setattr(store.StoreSession, "checkpoint", checkpoint)
        result = restore.commit_restore(review)
        assert injected and result.outcome == "failed", result
        assert result.transaction_id not in (None, source.intent.transaction_id)
        assert result.pending and result.journal_may_have_changed
        assert result.scope_may_have_changed == (point in ("rename", "terminal"))

    @pytest.mark.parametrize("kind", ["terminal", "prepared", "dangling"])
    def test_generated_collision_is_not_reused(self, source, monkeypatch, kind):
        review = draft(source)
        txid = source.intent.transaction_id
        if kind == "prepared":
            bundle = store.prepare_transaction(review.plan, state_root=Path(review.state_root))
            assert bundle is not None
            txid = bundle.intent.transaction_id
        elif kind == "dangling":
            txid = "e" * 32
            (Path(review.state_root) / "attune/transactions" / txid).symlink_to("absent")
        monkeypatch.setattr(publication.secrets, "token_hex", lambda _: txid)
        assert_clean(restore.commit_restore(review))

    def test_allocation_collision_after_pending_scan_cannot_replay_prepared(
        self, source, monkeypatch
    ):
        review = draft(source)
        txid = "e" * 32
        original = store.StoreSession.refuse_other_pending
        created = None

        def scan(session, selected=None):
            nonlocal created
            original(session, selected)
            if created is None:
                created = session.prepare(review.plan, txid)

        monkeypatch.setattr(store.StoreSession, "refuse_other_pending", scan)
        monkeypatch.setattr(publication.secrets, "token_hex", lambda _: txid)
        assert_clean(restore.commit_restore(review))
        assert created is not None
        assert store.verified_fingerprint_digest(created) == store.verified_fingerprint_digest(
            store.load_transaction(Path(review.state_root), txid)
        )

    def test_original_mutation_after_delegation_cannot_change_consumed_plan(
        self, source, monkeypatch
    ):
        review = draft(source)
        original = publication.publish_reviewed
        expected_text = review.plan.scopes[0].proposed_text
        target = Path(review.plan.scopes[0].resolved_path)

        def publish_checked(plan, **kwargs):
            object.__setattr__(review, "source_private_digest", "0" * 64)
            object.__setattr__(review.plan.scopes[0], "proposed_text", "forged")
            return original(plan, **kwargs)

        monkeypatch.setattr(publication, "publish_reviewed", publish_checked)
        result = restore.commit_restore(review)
        assert result.outcome == "committed", result
        assert target.read_text() == expected_text

    def test_collision_arriving_after_allocation_probe_is_never_replayed(self, source, monkeypatch):
        review = draft(source)
        txid = "e" * 32
        directory = Path(review.state_root) / "attune/transactions" / txid
        original_scan = store.StoreSession.refuse_other_pending
        original_probe = os.path.lexists
        sessions = []
        created = None

        def scan(session, selected=None):
            original_scan(session, selected)
            sessions.append(session)

        def probe(path):
            nonlocal created
            exists = original_probe(path)
            if Path(path) == directory and not exists and created is None:
                created = sessions[0].prepare(review.plan, txid)
            return exists

        monkeypatch.setattr(store.StoreSession, "refuse_other_pending", scan)
        monkeypatch.setattr(os.path, "lexists", probe)
        monkeypatch.setattr(publication.secrets, "token_hex", lambda _: txid)
        result = restore.commit_restore(review)
        assert created is not None
        assert result.outcome == "failed", result
        assert not result.scope_may_have_changed
        assert store.verified_fingerprint_digest(created) == store.verified_fingerprint_digest(
            store.load_transaction(Path(review.state_root), txid)
        )

    def test_delegated_result_and_exception_not_reinterpreted(self, source, monkeypatch):
        review = draft(source)
        result = publication.PublicationResult("a" * 32, "failed", True, True, True, "uncertain")
        monkeypatch.setattr(publication, "publish_reviewed", lambda *args, **kwargs: result)
        assert restore.commit_restore(review) is result

        def fail(*args, **kwargs):
            raise RuntimeError("delegated")

        monkeypatch.setattr(publication, "publish_reviewed", fail)
        with pytest.raises(RuntimeError, match="delegated"):
            restore.commit_restore(review)

    @pytest.mark.parametrize("point", ["compiler", "rename", "after-rename", "fsync", "checkpoint"])
    def test_uncertainty_and_recovery(self, source, monkeypatch, point):
        review = draft(source)
        target = Path(review.plan.scopes[0].resolved_path)
        original_replace = os.replace
        original_sync = os.fsync
        original_checkpoint = store.StoreSession.checkpoint
        renamed = False

        def compile(_text):
            if point == "compiler":
                raise ValueError("compiler failed")

        def rename(old, new):
            nonlocal renamed
            if Path(new) == target and point == "rename":
                raise OSError("rename uncertainty")
            result = original_replace(old, new)
            if Path(new) == target:
                renamed = True
                if point == "after-rename":
                    raise OSError("after rename")
            return result

        def sync(fd):
            if renamed and point == "fsync":
                raise OSError("directory fsync")
            return original_sync(fd)

        def checkpoint(session, bundle, record, **kwargs):
            if renamed and point == "checkpoint":
                raise OSError("progress uncertainty")
            return original_checkpoint(session, bundle, record, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(persistence, "validate_lua", compile)
            patch.setattr(os, "replace", rename)
            patch.setattr(os, "fsync", sync)
            patch.setattr(store.StoreSession, "checkpoint", checkpoint)
            result = restore.commit_restore(review)
        assert result.outcome == "failed", result
        assert result.pending and result.journal_may_have_changed
        assert result.scope_may_have_changed == (point != "compiler")
        assert result.transaction_id not in (None, source.intent.transaction_id)
        assert result.transaction_id is not None
        state = Path(review.state_root)
        recovery = publication.review_recovery(
            state,
            result.transaction_id,
            "finalize" if renamed else "resume",
            config_root=Path(review.config_root),
        )
        assert publication.commit_recovery(recovery).outcome == "committed"
        assert (
            store.load_transaction(state, source.intent.transaction_id).intent.phase
            is source.intent.phase
        )


CRASH_WORKER = """
import os, sys
from pathlib import Path
from hyprmod.core import scoped_restore as restore
state, config, txid = sys.argv[1:]
review = restore.prepare_restore(Path(config), Path(state), txid, restore.Scope.APPEARANCE, 'prior')
original = os.replace
def rename(old, new):
    original(old, new)
    if Path(new) == Path(review.plan.scopes[0].resolved_path):
        os._exit(73)
os.replace = rename
raise RuntimeError(repr(restore.commit_restore(review)))
"""


class TestInterruptedRestore:
    def test_real_exit_after_rename_and_existing_recovery(self, source):
        review = draft(source)
        state = Path(review.state_root)
        before = set(store.list_transaction_ids(state))
        fingerprint = store.verified_fingerprint_digest(source)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                CRASH_WORKER,
                review.state_root,
                review.config_root,
                review.transaction_id,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 73, result.stderr
        added = set(store.list_transaction_ids(state)) - before
        assert len(added) == 1
        txid = added.pop()
        assert txid != review.transaction_id
        pending = store.load_transaction(state, txid)
        assert pending.intent.phase is Phase.PUBLISHING
        assert pending.intent.progress == ()
        recovery = publication.review_recovery(
            state, txid, "finalize", config_root=Path(review.config_root)
        )
        recovered = publication.commit_recovery(recovery)
        assert recovered.outcome == "committed", recovered
        assert (
            store.verified_fingerprint_digest(store.load_transaction(state, review.transaction_id))
            == fingerprint
        )
        with pytest.raises(ValueError, match="Terminal"):
            publication.review_recovery(
                state, review.transaction_id, "resume", config_root=Path(review.config_root)
            )
