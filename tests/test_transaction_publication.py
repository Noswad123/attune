"""Inactive publication and real process-death recovery, exclusively in tmp_path."""

import fcntl
import os
import signal
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from hyprmod.core import installation, persistence, route_approval, scoped_review
from hyprmod.core import transaction_inspection as inspection
from hyprmod.core import transaction_publication as publication
from hyprmod.core import transaction_store as store
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import Phase, RollbackCheckpoint
from tests.test_scoped_review import appearance, displays, snapshot
from tests.test_scoped_review import evidence as evidence
from tests.test_transaction_store import plan as plan


@pytest.fixture
def group(plan):
    return scoped_review.build_review(
        plan.evidence,
        {Scope.APPEARANCE: appearance("7"), Scope.DISPLAYS: displays("HDMI-A-8")},
    )


def publish(plan, **kwargs):
    return publication.publish_reviewed(
        plan,
        state_root=Path(plan.evidence.state_root),
        config_root=Path(plan.evidence.config_root),
        **kwargs,
    )


def prepare(plan):
    bundle = store.prepare_transaction(plan, state_root=Path(plan.evidence.state_root))
    assert bundle is not None
    return bundle


def review(plan, txid, action):
    return publication.review_recovery(
        Path(plan.evidence.state_root), txid, action, config_root=Path(plan.evidence.config_root)
    )


def load(plan, txid):
    return store.load_transaction(Path(plan.evidence.state_root), txid)


def set_actual(plan, proposed):
    for item in plan.scopes:
        if item.scope in proposed:
            Path(item.resolved_path).write_text(item.proposed_text)


class TestPublication:
    @pytest.mark.parametrize("link_kind", ["file", "parent"])
    @pytest.mark.parametrize("retarget", [False, True])
    def test_stow_preservation_and_same_bytes_retarget(self, plan, tmp_path, link_kind, retarget):
        lexical = Path(plan.scopes[0].resolved_path)
        source = tmp_path / "stow"
        source.mkdir()
        target = source / lexical.name
        lexical.rename(target)
        if link_kind == "file":
            lexical.symlink_to(target)
        else:
            lexical.parent.rmdir()
            lexical.parent.symlink_to(source, target_is_directory=True)
        registry = Path(plan.evidence.registry.path.resolved_path)
        registry.write_text(
            installation.InstallationRegistry(
                installation.ScopeRoute(Scope.APPEARANCE, str(lexical), str(target)),
                installation.ScopeRoute(
                    Scope.DISPLAYS, plan.scopes[1].lexical_path, plan.scopes[1].resolved_path
                ),
            ).to_json()
        )
        current = route_approval.inspect_installation(
            registry,
            config_root=Path(plan.evidence.config_root),
            state_root=Path(plan.evidence.state_root),
        )
        proposal = scoped_review.build_review(current, {Scope.APPEARANCE: appearance("7")})
        bundle = prepare(proposal)
        approval = review(proposal, bundle.intent.transaction_id, "resume")
        link = lexical if link_kind == "file" else lexical.parent
        original_link = link.lstat()
        before = snapshot(current)
        if retarget:
            alternate = tmp_path / "other-stow"
            alternate.mkdir()
            (alternate / lexical.name).write_bytes(target.read_bytes())
            original_target = os.readlink(link)
            link.unlink()
            link.symlink_to(alternate / lexical.name if link_kind == "file" else alternate)
            assert publication.commit_recovery(approval).outcome == "failed"
            link.unlink()
            link.symlink_to(original_target)
            assert (
                publish(proposal, transaction_id=bundle.intent.transaction_id).outcome == "failed"
            )
        else:
            assert publication.commit_recovery(approval).outcome == "committed"
            assert link.lstat() == original_link
            assert target.read_text() == proposal.scopes[0].proposed_text
            assert snapshot(current)[2] == before[2]

    @pytest.mark.parametrize("changed", [(), (Scope.APPEARANCE,), (Scope.DISPLAYS,), tuple(Scope)])
    def test_publish_scope_isolation_noop_and_terminal(self, plan, changed):
        plan = scoped_review.build_review(
            plan.evidence,
            {
                s: appearance("7") if s is Scope.APPEARANCE else displays("HDMI-A-8")
                for s in changed
            },
        )
        before = snapshot(plan.evidence)
        result = publish(plan)
        assert result.error is None
        assert result.outcome == ("committed" if changed else "no-op")
        assert not result.pending
        assert result.scope_may_have_changed == bool(changed)
        after = snapshot(plan.evidence)
        for index, item in enumerate(plan.scopes, 1):
            assert after[index][0] == item.proposed_text.encode()
            if item.scope not in changed:
                assert after[index] == before[index]
        assert after[0] == before[0]
        if result.transaction_id:
            bundle = load(plan, result.transaction_id)
            assert bundle.intent.phase is Phase.COMMITTED
            assert bundle.intent.progress == changed
            for blob in bundle.blobs:
                original = next(r for r in plan.scopes if r.scope is blob.scope)
                assert blob.raw in (
                    original.previous_text.encode(),
                    original.proposed_text.encode(),
                )
            with pytest.raises(ValueError, match="Terminal"):
                review(plan, result.transaction_id, "rollback")

    def test_select_prepared_requires_exact_review(self, group):
        bundle = prepare(group)
        result = publish(group, transaction_id=bundle.intent.transaction_id)
        assert result.outcome == "committed", result.error

    @pytest.mark.parametrize("failure", ["missing", "invalid", "timeout"])
    def test_compile_preflight_before_any_replacement(self, group, monkeypatch, failure):
        before = snapshot(group.evidence)
        calls = []
        if failure == "missing":
            monkeypatch.setattr(persistence.shutil, "which", lambda _: None)
        else:

            def fail(text):
                calls.append(text)
                if len(calls) == 4:
                    raise ValueError(failure)

            monkeypatch.setattr(persistence, "validate_lua", fail)
        result = publish(group)
        assert result.outcome == "failed"
        assert result.journal_may_have_changed
        assert not result.scope_may_have_changed
        assert snapshot(group.evidence) == before
        assert load(group, result.transaction_id).intent.phase is Phase.PREPARED

    def test_compile_all_current_and_desired_before_stage(self, group, monkeypatch):
        calls = []
        original_open = os.open
        monkeypatch.setattr(persistence, "validate_lua", calls.append)

        def observe(path, flags, *args, **kwargs):
            if Path(path).name.startswith(".attune-"):
                assert calls == [
                    text for r in group.scopes for text in (r.previous_text, r.proposed_text)
                ]
            return original_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", observe)
        assert publish(group).outcome == "committed"

    def test_abandon_remains_available_after_compiler_preflight_failure(self, group, monkeypatch):
        before = snapshot(group.evidence)

        def unavailable(_text):
            raise ValueError("Lua compiler unavailable")

        monkeypatch.setattr(persistence, "validate_lua", unavailable)
        failed = publish(group)
        assert failed.outcome == "failed" and not failed.scope_may_have_changed
        assert failed.transaction_id is not None
        approval = review(group, failed.transaction_id, "abandon")
        result = publication.commit_recovery(approval)
        assert result.outcome == "aborted", result.error
        assert not result.pending and not result.scope_may_have_changed
        assert snapshot(group.evidence) == before

    @pytest.mark.parametrize("which", ["state", "config", "diff", "hash", "changed", "proposal"])
    def test_forged_or_wrong_context(self, group, tmp_path, which):
        before = snapshot(group.evidence)
        kwargs = {
            "state_root": Path(group.evidence.state_root),
            "config_root": Path(group.evidence.config_root),
        }
        if which in ("state", "config"):
            kwargs[which + "_root"] = tmp_path
        elif which == "hash":
            group = replace(group, review_hash="0" * 64)
        elif which == "changed":
            group = replace(group, changed_scopes=(Scope.APPEARANCE,))
        else:
            item = replace(
                group.scopes[0], **{"diff" if which == "diff" else "proposed_text": "forged"}
            )
            group = replace(group, scopes=(item, group.scopes[1]))
        result = publication.publish_reviewed(
            group, state_root=kwargs["state_root"], config_root=kwargs["config_root"]
        )
        assert result.outcome == "failed"
        assert not result.scope_may_have_changed
        assert not result.journal_may_have_changed
        assert snapshot(group.evidence) == before

    @pytest.mark.parametrize(
        "kind",
        [
            "registry",
            "source",
            "parent",
            "git",
            "protected",
            "blob",
            "snapshot",
            "private-mode",
            "private-identity",
        ],
    )
    @pytest.mark.parametrize("boundary", [1, 2])
    def test_drift_before_each_replace(self, group, monkeypatch, kind, boundary):
        before = snapshot(group.evidence)
        original_check = store.StoreSession.checkpoint
        injected = False

        def drift(session, bundle, record, **kwargs):
            nonlocal injected
            result = original_check(session, bundle, record, **kwargs)
            if (
                not injected
                and getattr(record, "phase", None) is Phase.PUBLISHING
                and len(record.progress) == boundary - 1
            ):
                injected = True
                root = Path(group.evidence.state_root) / "attune"
                if kind == "registry":
                    path = Path(group.evidence.registry.path.resolved_path)
                    path.write_bytes(path.read_bytes() + b"\n")
                elif kind == "source":
                    Path(group.scopes[boundary - 1].resolved_path).write_text("foreign")
                elif kind == "parent":
                    Path(group.scopes[boundary - 1].resolved_path).parent.chmod(0o750)
                elif kind == "git":
                    Path(group.scopes[1].resolved_path).parent.joinpath(".git").write_text(
                        "gitdir: irrelevant"
                    )
                elif kind == "protected":
                    Path(group.evidence.config_root, "hypr/hyprland.lua").write_text("authored")
                else:
                    path = root / "blobs" / (group.scopes[0].previous_sha256 + ".lua")
                    if kind == "snapshot":
                        path = root / "snapshots" / (bundle.snapshot.snapshot_id + ".json")
                    if kind == "private-mode":
                        path.chmod(0o640)
                    elif kind == "private-identity":
                        raw = path.read_bytes()
                        path.unlink()
                        path.write_bytes(raw)
                        path.chmod(0o600)
                    else:
                        path.write_bytes(b"corrupt")
            return result

        monkeypatch.setattr(store.StoreSession, "checkpoint", drift)
        try:
            result = publish(group)
            assert injected
            assert result.outcome == "failed", result
            assert result.scope_may_have_changed == (boundary == 2)
            if kind != "source":
                expected = group.scopes[boundary - 1].previous_text.encode()
                assert Path(group.scopes[boundary - 1].resolved_path).read_bytes() == expected
            assert (
                snapshot(group.evidence)[1][0]
                == (group.scopes[0].proposed_text.encode() if boundary == 2 else before[1][0])
                or kind == "source"
            )
        finally:
            for item in group.scopes:
                Path(item.resolved_path).parent.chmod(0o755)

    @pytest.mark.parametrize("boundary", [1, 2])
    @pytest.mark.parametrize(
        "operation", ["stage", "replace", "replace-after", "output-sync", "progress", "terminal"]
    )
    def test_failure_boundaries_leave_honest_flags(self, group, monkeypatch, operation, boundary):
        original_replace = os.replace
        original_sync = os.fsync
        original_checkpoint = store.StoreSession.checkpoint
        original_open = os.open
        count = 0
        replacements = 0

        def rename(source, target):
            nonlocal replacements
            if Path(target).name in ("attune-appearance.lua", "attune-displays.lua"):
                replacements += 1
                if operation == "replace" and replacements == boundary:
                    raise OSError("injected replace")
                if operation == "replace-after" and replacements == boundary:
                    original_replace(source, target)
                    raise OSError("injected error after rename")
            return original_replace(source, target)

        def sync(fd):
            path = Path(os.readlink(f"/proc/self/fd/{fd}"))
            if (
                operation == "output-sync"
                and replacements == boundary
                and path in {Path(r.resolved_path).parent for r in group.scopes}
            ):
                raise OSError("injected output sync")
            return original_sync(fd)

        def checkpoint(session, bundle, record, **kwargs):
            if (
                operation == "progress"
                and getattr(record, "phase", None) is Phase.PUBLISHING
                and len(record.progress) == boundary
            ):
                raise OSError("injected progress")
            if operation == "terminal" and getattr(record, "phase", None) is Phase.COMMITTED:
                raise OSError("injected terminal")
            return original_checkpoint(session, bundle, record, **kwargs)

        def opening(path, flags, *args, **kwargs):
            nonlocal count
            if Path(path).name.startswith(".attune-") and flags & os.O_CREAT:
                count += 1
                if operation == "stage" and count == boundary:
                    raise OSError("injected stage")
            return original_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "replace", rename)
        monkeypatch.setattr(os, "fsync", sync)
        monkeypatch.setattr(os, "open", opening)
        monkeypatch.setattr(store.StoreSession, "checkpoint", checkpoint)
        result = publish(group)
        assert result.outcome == "failed", result
        assert result.pending and result.journal_may_have_changed
        assert result.scope_may_have_changed == (operation != "stage")
        assert load(group, result.transaction_id).intent.phase in (Phase.PREPARED, Phase.PUBLISHING)

    def test_lock_timeout_and_cancellation(self, group, monkeypatch):
        root = Path(group.evidence.state_root) / "attune"
        path = root / "persistence.lock"
        path.touch(mode=0o600)
        before = snapshot(group.evidence)
        with path.open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            monkeypatch.setattr(store, "LOCK_TIMEOUT", 0.01)
            result = publish(group)
            assert result.outcome == "failed" and "timed out" in (result.error or "")
        event = threading.Event()
        event.set()
        result = publish(group, cancel_event=event)
        assert result.outcome == "failed" and not result.scope_may_have_changed
        assert snapshot(group.evidence) == before

    def test_cancel_after_first_replace_and_post_terminal(self, group, monkeypatch):
        event = threading.Event()
        original = store.StoreSession.checkpoint

        def cancel(session, bundle, record, **kwargs):
            result = original(session, bundle, record, **kwargs)
            if record.phase is Phase.PUBLISHING and record.progress:
                event.set()
            return result

        monkeypatch.setattr(store.StoreSession, "checkpoint", cancel)
        result = publish(group, cancel_event=event)
        assert result.outcome == "failed" and result.scope_may_have_changed
        if result.transaction_id is None:
            pytest.fail("Missing pending transaction")
        assert (
            inspection.classify_transaction(
                Path(group.evidence.state_root),
                result.transaction_id,
                config_root=Path(group.evidence.config_root),
            ).status
            is inspection.OverallStatus.MIXED
        )
        event.clear()

        def terminal_cancel(session, bundle, record, **kwargs):
            result = original(session, bundle, record, **kwargs)
            if record.phase is Phase.COMMITTED:
                event.set()
            return result

        monkeypatch.setattr(store.StoreSession, "checkpoint", terminal_cancel)
        recovered = publication.commit_recovery(
            review(group, result.transaction_id, "resume"), cancel_event=event
        )
        assert recovered.outcome == "committed" and not recovered.pending


class TestRecovery:
    @pytest.mark.parametrize("proposed", [(), (Scope.APPEARANCE,), (Scope.DISPLAYS,), tuple(Scope)])
    @pytest.mark.parametrize("action", ["resume", "rollback", "finalize", "abandon"])
    def test_actual_mixtures_actions_and_no_rewrites(self, group, monkeypatch, proposed, action):
        bundle = prepare(group)
        txid = bundle.intent.transaction_id
        set_actual(group, proposed)
        allowed = (
            action == "resume"
            and len(proposed) < 2
            or action == "rollback"
            and bool(proposed)
            or action == "finalize"
            and len(proposed) == 2
            or action == "abandon"
            and not proposed
        )
        if not allowed:
            with pytest.raises(ValueError):
                review(group, txid, action)
            return
        before = snapshot(group.evidence)
        approval = review(group, txid, action)
        for item in approval.plan.scopes:
            assert item.previous_text.encode() == Path(item.resolved_path).read_bytes()
        original = os.replace
        written = []

        def observe(source, target):
            if Path(target).name.startswith("attune-"):
                written.append(Path(target))
            return original(source, target)

        monkeypatch.setattr(os, "replace", observe)
        result = publication.commit_recovery(approval)
        assert result.error is None, result
        assert not result.pending
        assert result.outcome == ("aborted" if action in ("rollback", "abandon") else "committed")
        assert written == [
            Path(r.resolved_path)
            for r in approval.plan.scopes
            if r.scope in approval.plan.changed_scopes
        ]
        after = snapshot(group.evidence)
        for index, item in enumerate(approval.plan.scopes, 1):
            assert after[index][0] == item.proposed_text.encode()
            if item.scope not in approval.plan.changed_scopes:
                assert after[index] == before[index]
        assert publication.commit_recovery(approval).outcome == "failed"

    @pytest.mark.parametrize(
        "kind",
        ["scope", "mode", "registry", "journal", "private", "diff", "hash", "context", "action"],
    )
    def test_stale_or_forged_recovery(self, group, kind, tmp_path):
        bundle = prepare(group)
        approval = review(group, bundle.intent.transaction_id, "resume")
        if kind == "scope":
            Path(group.scopes[0].resolved_path).write_text(group.scopes[0].previous_text)
        elif kind == "mode":
            Path(group.scopes[1].resolved_path).chmod(0o640)
        elif kind == "registry":
            path = Path(group.evidence.registry.path.resolved_path)
            path.write_bytes(path.read_bytes())
        elif kind in ("journal", "private"):
            root = Path(group.evidence.state_root) / "attune"
            path = (
                root / "transactions" / bundle.intent.transaction_id / "intent.json"
                if kind == "journal"
                else root / "blobs" / (group.scopes[0].previous_sha256 + ".lua")
            )
            path.write_bytes(path.read_bytes())
        elif kind == "context":
            approval = replace(approval, config_root=tmp_path)
        elif kind == "action":
            approval = replace(approval, action="finalize")
        elif kind == "hash":
            approval = replace(approval, plan=replace(approval.plan, review_hash="0" * 64))
        else:
            item = replace(approval.plan.scopes[0], diff="forged")
            approval = replace(
                approval, plan=replace(approval.plan, scopes=(item, approval.plan.scopes[1]))
            )
        before = snapshot(group.evidence)
        result = publication.commit_recovery(approval)
        assert result.outcome == "failed"
        assert not result.scope_may_have_changed
        assert not result.journal_may_have_changed
        assert snapshot(group.evidence) == before

    @pytest.mark.parametrize("kind", ["pending", "empty", "unknown", "corrupt"])
    def test_other_transactions_block_selected(self, group, kind):
        bundle = prepare(group)
        root = Path(group.evidence.state_root) / "attune/transactions"
        other = root / ("b" * 32 if kind != "unknown" else "unknown")
        other.mkdir(mode=0o700)
        if kind in ("pending", "corrupt"):
            record = replace(bundle.intent, transaction_id="b" * 32)
            path = other / "intent.json"
            path.write_text(record.to_json() if kind == "pending" else "{}")
            path.chmod(0o600)
        result = publication.commit_recovery(review(group, bundle.intent.transaction_id, "resume"))
        assert result.outcome == "failed" and not result.scope_may_have_changed

    @pytest.mark.parametrize("stop", ["operation", "first-restore", "complete"])
    def test_rollback_direction_lock_and_explicit_finish(self, group, monkeypatch, stop):
        bundle = prepare(group)
        txid = bundle.intent.transaction_id
        set_actual(group, tuple(Scope))
        original = store.StoreSession.checkpoint

        def fail(session, bundle, record, **kwargs):
            result = original(session, bundle, record, **kwargs)
            if (
                stop == "operation"
                and result.rollback is not None
                and result.rollback_checkpoint is None
            ):
                raise OSError("after operation")
            if isinstance(record, RollbackCheckpoint) and (
                stop == "first-restore"
                and len(record.progress) == 1
                or stop == "complete"
                and record.complete
            ):
                raise OSError("after reverse checkpoint")
            return result

        monkeypatch.setattr(store.StoreSession, "checkpoint", fail)
        approval = review(group, txid, "rollback")
        result = publication.commit_recovery(approval)
        assert result.outcome == "failed" and result.journal_may_have_changed
        assert load(group, txid).rollback is not None
        for action in ("resume", "finalize", "abandon"):
            with pytest.raises(ValueError, match="locked"):
                review(group, txid, action)
        assert publication.commit_recovery(approval).outcome == "failed"
        monkeypatch.setattr(store.StoreSession, "checkpoint", original)
        before = snapshot(group.evidence)
        fresh = review(group, txid, "rollback")
        assert publication.commit_recovery(fresh).outcome == "aborted"
        after = snapshot(group.evidence)
        for index, item in enumerate(fresh.plan.scopes, 1):
            if item.scope not in fresh.plan.changed_scopes:
                assert after[index] == before[index]

    def test_unchanged_sibling_full_identity_blocks_recovery(self, plan):
        bundle = prepare(plan)
        path = Path(plan.scopes[1].resolved_path)
        path.write_bytes(path.read_bytes())
        with pytest.raises(ValueError, match="conflict"):
            review(plan, bundle.intent.transaction_id, "resume")

    def test_reverse_progress_does_not_override_fresh_actual_known_states(self, group, monkeypatch):
        bundle = prepare(group)
        txid = bundle.intent.transaction_id
        set_actual(group, tuple(Scope))
        original = store.StoreSession.checkpoint

        def stop_before_complete(session, bundle, record, **kwargs):
            if isinstance(record, RollbackCheckpoint) and record.complete:
                raise OSError("before completion")
            return original(session, bundle, record, **kwargs)

        monkeypatch.setattr(store.StoreSession, "checkpoint", stop_before_complete)
        assert publication.commit_recovery(review(group, txid, "rollback")).outcome == "failed"
        pending = load(group, txid)
        if pending.rollback_checkpoint is None:
            pytest.fail("Missing rollback progress")
        assert pending.rollback_checkpoint.progress == tuple(Scope)
        set_actual(group, tuple(Scope))
        monkeypatch.setattr(store.StoreSession, "checkpoint", original)
        assert publication.commit_recovery(review(group, txid, "rollback")).outcome == "aborted"

    @pytest.mark.parametrize("scope", list(Scope))
    def test_rollback_only_initial_changed_proposed_scopes(self, group, scope):
        bundle = prepare(group)
        set_actual(group, (scope,))
        approval = review(group, bundle.intent.transaction_id, "rollback")
        assert approval.plan.changed_scopes == (scope,)
        before = snapshot(group.evidence)
        assert publication.commit_recovery(approval).outcome == "aborted"
        loaded = load(group, bundle.intent.transaction_id)
        if loaded.rollback is None:
            pytest.fail("Missing rollback operation")
        assert loaded.rollback.restore_scopes == (scope,)
        assert loaded.rollback.initial_review == approval.plan
        after = snapshot(group.evidence)
        other = 2 if scope is Scope.APPEARANCE else 1
        assert before[other] == after[other]


CRASH_WORKER = """
import os, signal, sys
from pathlib import Path
from hyprmod.core import transaction_store as store
from hyprmod.core import transaction_publication as publication
state, config, txid, point, death = sys.argv[1:]
state, config = Path(state), Path(config)
real_replace, real_fsync = os.replace, os.fsync
writes = 0
def die():
    if death == 'kill':
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(73)
def rename(source, target):
    global writes
    real_replace(source, target)
    if Path(target).name in ('attune-appearance.lua', 'attune-displays.lua'):
        writes += 1
        if point in ('forward', 'rollback'):
            die()
def sync(fd):
    real_fsync(fd)
    name = Path(os.readlink('/proc/self/fd/' + str(fd))).name
    if point == 'scratch' and name.startswith('.intent.json.'):
        die()
    if point == 'progress-scratch' and writes == 1 and name.startswith('.intent.json.'):
        die()
    if (point == 'rollback-scratch' and writes == 1
            and name.startswith('.rollback-checkpoint.json.')):
        die()
os.replace, os.fsync = rename, sync
if point in ('rollback', 'rollback-scratch'):
    review = publication.review_recovery(state, txid, 'rollback', config_root=config)
    result = publication.commit_recovery(review)
else:
    plan = store.load_transaction(state, txid).snapshot.plan
    result = publication.publish_reviewed(
        plan, state_root=state, config_root=config, transaction_id=txid)
raise RuntimeError(repr(result))
"""


class TestHardCrashes:
    @pytest.mark.parametrize(
        "point,death",
        [
            ("forward", "exit"),
            ("forward", "kill"),
            ("scratch", "kill"),
            ("progress-scratch", "kill"),
            ("rollback", "kill"),
            ("rollback-scratch", "kill"),
        ],
    )
    def test_actual_process_death_and_fresh_recovery(self, group, point, death):
        bundle = prepare(group)
        txid = bundle.intent.transaction_id
        reverse = point in ("rollback", "rollback-scratch")
        if reverse:
            set_actual(group, tuple(Scope))
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                CRASH_WORKER,
                group.evidence.state_root,
                group.evidence.config_root,
                txid,
                point,
                death,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == (-signal.SIGKILL if death == "kill" else 73), result.stderr
        loaded = load(group, txid)
        observation = inspection.classify_transaction(
            Path(group.evidence.state_root), txid, config_root=Path(group.evidence.config_root)
        )
        assert observation.status is (
            inspection.OverallStatus.ALL_PRIOR
            if point == "scratch"
            else inspection.OverallStatus.MIXED
        )
        directory = Path(group.evidence.state_root) / "attune/transactions" / txid
        scratch = tuple(directory.glob(".*.json.*.tmp"))
        if point == "scratch":
            assert scratch
            assert loaded.intent.phase is Phase.PREPARED
        elif point in ("forward", "progress-scratch"):
            assert loaded.intent.phase is Phase.PUBLISHING and loaded.intent.progress == ()
        else:
            if loaded.rollback_checkpoint is None:
                pytest.fail("Missing rollback checkpoint")
            assert loaded.rollback is not None and loaded.rollback_checkpoint.progress == ()
        if point.endswith("scratch"):
            assert scratch
        approval = review(group, txid, "rollback" if reverse else "resume")
        before = snapshot(group.evidence)
        recovered = publication.commit_recovery(approval)
        assert recovered.outcome == ("aborted" if reverse else "committed"), recovered.error
        assert not recovered.pending
        after = snapshot(group.evidence)
        for index, item in enumerate(approval.plan.scopes, 1):
            if item.scope not in approval.plan.changed_scopes:
                assert before[index] == after[index]
        assert all(path.exists() for path in scratch)


class TestEverySyncBoundary:
    @pytest.mark.parametrize("syscall", ["stage", "replace"])
    @pytest.mark.parametrize(
        "action,name,position",
        [
            *(("publish", "intent.json", n) for n in range(1, 5)),
            ("rollback", "rollback.json", 1),
            *(("rollback", "rollback-checkpoint.json", n) for n in range(1, 5)),
            ("rollback", "intent.json", 1),
        ],
    )
    def test_each_atomic_metadata_boundary(
        self, group, monkeypatch, syscall, action, name, position
    ):
        bundle = prepare(group)
        txid = bundle.intent.transaction_id
        if action == "rollback":
            set_actual(group, tuple(Scope))
        original_open, original_replace = os.open, os.replace
        count = 0

        def opening(path, flags, *args, **kwargs):
            nonlocal count
            if (
                syscall == "stage"
                and flags & os.O_CREAT
                and Path(path).name.startswith("." + name + ".")
            ):
                count += 1
                if count == position:
                    raise OSError("injected metadata stage")
            return original_open(path, flags, *args, **kwargs)

        def rename(source, target):
            nonlocal count
            if syscall == "replace" and Path(target).name == name:
                count += 1
                if count == position:
                    raise OSError("injected metadata replacement")
            return original_replace(source, target)

        monkeypatch.setattr(os, "open", opening)
        monkeypatch.setattr(os, "replace", rename)
        approval = review(group, txid, "rollback" if action == "rollback" else "resume")
        result = publication.commit_recovery(approval)
        assert count == position
        assert result.outcome == "failed" and result.journal_may_have_changed
        assert load(group, txid).intent.phase in (Phase.PREPARED, Phase.PUBLISHING)
        monkeypatch.setattr(os, "open", original_open)
        monkeypatch.setattr(os, "replace", original_replace)
        status = inspection.classify_transaction(
            Path(group.evidence.state_root), txid, config_root=Path(group.evidence.config_root)
        ).status
        next_action = (
            "rollback"
            if action == "rollback"
            else "finalize"
            if status is inspection.OverallStatus.ALL_PROPOSED
            else "resume"
        )
        fresh = review(group, txid, next_action)
        assert publication.commit_recovery(fresh).error is None

    @pytest.mark.parametrize("action", ["publish", "rollback"])
    @pytest.mark.parametrize("failure_at", range(61))
    def test_fsync_uncertainty_at_every_call(self, group, monkeypatch, action, failure_at):
        approval = None
        if action == "rollback":
            bundle = prepare(group)
            set_actual(group, tuple(Scope))
            approval = review(group, bundle.intent.transaction_id, "rollback")
        original = os.fsync
        count = 0

        def sync(fd):
            nonlocal count
            count += 1
            if count == failure_at:
                raise OSError("injected fsync boundary")
            return original(fd)

        monkeypatch.setattr(os, "fsync", sync)
        result = publish(group) if approval is None else publication.commit_recovery(approval)
        if not failure_at or count < failure_at:
            assert result.error is None, result
            assert count <= 60, "Increase boundary enumeration to cover all fsync calls"
        else:
            assert result.outcome == "failed", (failure_at, result)
            assert result.pending and result.journal_may_have_changed
        for item in group.scopes:
            assert Path(item.resolved_path).read_text() in (item.previous_text, item.proposed_text)
