"""Frontend service tests use explicit temporary contexts and no application/IPC."""

import json
import os
import subprocess
import threading
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from hyprmod.core import health, persistence, scoped_review
from hyprmod.core import scoped_recovery as service
from hyprmod.core import transaction_publication as publication
from hyprmod.core import transaction_store as store
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import Phase, RollbackOperation
from tests.test_scoped_review import appearance, displays, snapshot
from tests.test_scoped_review import evidence as evidence
from tests.test_transaction_store import plan as plan


@pytest.fixture
def prepared(plan):
    bundle = store.prepare_transaction(plan, state_root=Path(plan.evidence.state_root))
    assert bundle is not None
    return plan, bundle.intent.transaction_id


def roots(plan):
    return Path(plan.evidence.config_root), Path(plan.evidence.state_root)


def draft_for(prepared, action="resume"):
    plan, txid = prepared
    return service.run_prepare_action(*roots(plan), txid, action)


class TestAssessment:
    def test_direct_workers_forbid_mutations_and_main_bytes(self, prepared, monkeypatch):
        plan, txid = prepared
        original_open = os.open
        original_read = persistence.read_stable

        def readonly_open(path, flags, *args, **kwargs):
            assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            return original_open(path, flags, *args, **kwargs)

        def read(path, **kwargs):
            assert Path(path).name not in ("hyprland.lua", "attune.lua", "hyprland.conf")
            return original_read(path, **kwargs)

        monkeypatch.setattr(os, "open", readonly_open)
        monkeypatch.setattr(persistence, "read_stable", read)
        for method in ("mkdir", "chmod", "unlink", "write_bytes", "write_text", "rename"):
            monkeypatch.setattr(
                Path, method, lambda *_a, **_k: pytest.fail("Read-only worker wrote")
            )
        monkeypatch.setattr(
            os, "replace", lambda *_a, **_k: pytest.fail("Read-only worker replaced")
        )
        assert service.assess_layout(*roots(plan)).mode == "scope-recovery-required"
        assert service._prepare(*roots(plan), txid, "resume").plan.review_hash == plan.review_hash

    def test_mixed_is_actual_not_phase(self, plan):
        proposal = scoped_review.build_review(
            plan.evidence, {Scope.APPEARANCE: appearance("9"), Scope.DISPLAYS: displays("HDMI-A-8")}
        )
        bundle = store.prepare_transaction(proposal, state_root=roots(plan)[1])
        assert bundle is not None
        Path(proposal.scopes[0].resolved_path).write_text(proposal.scopes[0].proposed_text)
        row = service.assess_layout(*roots(plan)).transactions[0]
        assert row.phase == "prepared" and row.actual_status == "mixed"
        draft = service.run_prepare_action(*roots(plan), bundle.intent.transaction_id, "resume")
        assert draft.plan.changed_scopes == (Scope.DISPLAYS,)
        assert not draft.plan.scopes[0].diff

    def test_legacy_default_zero_creation(self, tmp_path, monkeypatch):
        config, state = tmp_path / "config", tmp_path / "state"
        before = tuple(tmp_path.rglob("*"))
        monkeypatch.setattr(persistence, "read_stable", lambda *_a, **_k: pytest.fail("No bytes"))
        direct = service.assess_layout(config, state)
        child = service.run_assess(config, state)
        assert direct == child
        assert child.mode == "legacy-clear"
        assert tuple(tmp_path.rglob("*")) == before
        assert service.LayoutAssessment.from_json(child.to_json()) == child

    def test_registry_and_actual_status(self, prepared):
        plan, txid = prepared
        before = snapshot(plan.evidence)
        result = service.run_assess(*roots(plan))
        assert result.mode == "scope-recovery-required"
        assert result.registry_condition == "valid"
        row = result.transactions[0]
        assert row.transaction_id == txid
        assert row.phase == "prepared" and row.actual_status == "all-prior"
        assert row.rollback_direction is False
        assert snapshot(plan.evidence) == before
        Path(plan.scopes[0].resolved_path).write_text(plan.scopes[0].proposed_text)
        result = service.assess_layout(*roots(plan))
        assert result.transactions[0].phase == "prepared"
        assert result.transactions[0].actual_status == "all-proposed"

    def test_terminal_history_without_registry_never_falls_back(self, prepared):
        plan, txid = prepared
        assert service.commit_action(draft_for(prepared, "abandon")).outcome == "aborted"
        Path(plan.evidence.registry.path.resolved_path).unlink()
        result = service.assess_layout(*roots(plan))
        assert result.mode != "legacy-clear"
        assert result.transactions[0].phase == "aborted"
        assert result.transactions[0].actual_status == "conflict"

    @pytest.mark.parametrize("damage", ["unknown", "missing", "malformed", "registry", "symlink"])
    def test_corruption_partial_status(self, prepared, damage):
        plan, txid = prepared
        config, state = roots(plan)
        intent = state / "attune/transactions" / txid / "intent.json"
        if damage == "unknown":
            (intent.parent.parent / "unknown").mkdir()
        elif damage == "missing":
            intent.unlink()
        elif damage == "malformed":
            intent.write_text("{}")
        elif damage == "symlink":
            intent.unlink()
            intent.symlink_to(config / "missing")
        else:
            Path(plan.evidence.registry.path.resolved_path).write_text("{}")
        result = service.assess_layout(config, state)
        assert result.mode == "blocked"
        assert result.registry_condition == (
            "invalid-or-uninspectable" if damage == "registry" else "valid"
        )
        assert service.LayoutAssessment.from_json(result.to_json()) == result

    def test_rollback_direction_is_observed(self, prepared):
        plan, txid = prepared
        config, state = roots(plan)
        Path(plan.scopes[0].resolved_path).write_text(plan.scopes[0].proposed_text)
        review = publication.review_recovery(state, txid, "rollback", config_root=config)
        bundle = store.load_transaction(state, txid)
        operation = RollbackOperation(
            bundle.snapshot.snapshot_id,
            plan.review_hash,
            store.verified_fingerprint_digest(bundle),
            review.plan,
            review.plan.changed_scopes,
        )
        with store.exclusive_store_session(state) as session:
            session.checkpoint(bundle, operation, fingerprint=store.verified_fingerprint(bundle))
        row = service.assess_layout(config, state).transactions[0]
        assert row.rollback_direction is True
        with pytest.raises(ValueError, match="direction"):
            service.run_prepare_action(config, state, txid, "finalize")

    def test_row_cap_and_scan_bound(self, plan, monkeypatch):
        config, state = roots(plan)
        monkeypatch.setattr(service, "MAX_ROWS", 1)
        store.prepare_transaction(plan, state_root=state, transaction_id="a" * 32)
        with store.exclusive_store_session(state) as session:
            bundle = store.load_transaction(state, "a" * 32)
            session.checkpoint(
                bundle,
                replace(bundle.intent, phase=Phase.ABORTED),
                fingerprint=store.verified_fingerprint(bundle),
            )
        store.prepare_transaction(plan, state_root=state, transaction_id="b" * 32)
        result = service.assess_layout(config, state)
        assert result.truncated and result.mode == "blocked"
        assert len(result.transactions) == 1
        monkeypatch.setattr(store, "MAX_JOURNALS", 1)
        assert service.assess_layout(config, state).mode == "blocked"


class TestDraft:
    def test_private_change_during_review_refused(self, prepared, monkeypatch):
        plan, txid = prepared
        original = publication.review_recovery

        def changed(*args, **kwargs):
            review = original(*args, **kwargs)
            path = roots(plan)[1] / "attune/transactions" / txid / "intent.json"
            path.write_bytes(path.read_bytes() + b" ")
            return review

        monkeypatch.setattr(publication, "review_recovery", changed)
        with pytest.raises(ValueError, match="changed"):
            service._prepare(*roots(plan), txid, "resume")

    def test_forged_in_memory_diff_is_checked_before_delegate(self, prepared, monkeypatch):
        draft = draft_for(prepared)
        object.__setattr__(draft.plan.scopes[0], "diff", "forged")
        monkeypatch.setattr(
            publication, "commit_recovery", lambda *_a, **_k: pytest.fail("delegate")
        )
        result = service.commit_action(draft)
        assert result.outcome == "failed" and result.pending
        assert not result.scope_may_have_changed and not result.journal_may_have_changed

    def test_complete_immutable_readonly_roundtrip(self, prepared, monkeypatch):
        plan, txid = prepared
        before = snapshot(plan.evidence)
        monkeypatch.setattr(publication, "commit_recovery", lambda *_a, **_k: pytest.fail("write"))
        draft = draft_for(prepared)
        assert draft.plan.scopes == plan.scopes
        assert draft.plan.review_hash == plan.review_hash
        assert draft.transaction_id == txid
        assert service.ScopedRecoveryDraft.from_json(draft.to_json()) == draft
        with pytest.raises(FrozenInstanceError):
            setattr(draft.plan.scopes[0], "diff", "forged")
        assert snapshot(plan.evidence) == before
        bundle = store.load_transaction(roots(plan)[1], txid)
        assert draft.private_digest == store.verified_fingerprint_digest(bundle)
        assert "VerifiedTransaction" not in draft.to_json()
        assert not tuple(roots(plan)[1].rglob("*.tmp"))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("diff", "forged"),
            ("previous_text", "legacy full bundle"),
            ("resolved_path", "/tmp/attune-appearance.lua"),
            ("added_lines", True),
            ("proposed_sha256", "0" * 64),
            ("diff", "x" * 262145),
        ],
        ids=["diff", "legacy", "path", "bool", "hash", "oversized-diff"],
    )
    def test_tampered_semantics_rejected_before_display(self, prepared, field, value):
        data = json.loads(draft_for(prepared).to_json())
        data["plan"]["scopes"][0][field] = value
        with pytest.raises(ValueError):
            service.ScopedRecoveryDraft.from_json(json.dumps(data))

    @pytest.mark.parametrize(
        "bad",
        ["{", '{"schema":1,"schema":1}', "[" * 25 + "]" * 25, " " * (8 * 1024 * 1024 + 1)],
        ids=["malformed", "duplicate", "deep", "oversized"],
    )
    def test_strict_json(self, bad):
        with pytest.raises(ValueError):
            service.ScopedRecoveryDraft.from_json(bad)
        with pytest.raises(ValueError):
            service.LayoutAssessment.from_json(bad)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("schema", 2),
            ("kind", "legacy-full-bundle"),
            ("extra", 1),
            ("action", "repair"),
            ("config_root", "/tmp/elsewhere"),
        ],
    )
    def test_unknown_or_wrong_context(self, prepared, field, value):
        data = json.loads(draft_for(prepared).to_json())
        data[field] = value
        with pytest.raises(ValueError):
            service.ScopedRecoveryDraft.from_json(json.dumps(data))

    def test_noop_finalization_plan_transport(self, prepared):
        plan, _ = prepared
        Path(plan.scopes[0].resolved_path).write_text(plan.scopes[0].proposed_text)
        draft = draft_for(prepared, "finalize")
        assert not draft.plan.changed_scopes
        assert service.ScopedRecoveryDraft.from_json(draft.to_json()) == draft
        result = service.commit_action(draft)
        assert result.outcome == "committed" and not result.scope_may_have_changed

    @pytest.mark.parametrize("change", ["scope", "private", "source-id", "digest"])
    def test_stale_refuses_with_clean_flags(self, prepared, change):
        plan, txid = prepared
        draft = draft_for(prepared)
        if change == "scope":
            Path(plan.scopes[0].resolved_path).write_text(plan.scopes[0].proposed_text)
        elif change == "private":
            intent = roots(plan)[1] / "attune/transactions" / txid / "intent.json"
            raw = intent.read_bytes()
            intent.unlink()
            intent.write_bytes(raw)
            intent.chmod(0o600)
        else:
            draft = replace(
                draft, **{("snapshot_id" if change == "source-id" else "private_digest"): "0" * 64}
            )
        result = service.commit_action(draft)
        assert result.outcome == "failed" and result.pending and result.error
        assert not result.scope_may_have_changed and not result.journal_may_have_changed

    def test_direct_commit_preserves_backend_flags(self, prepared, monkeypatch):
        draft = draft_for(prepared)
        uncertain = publication.PublicationResult(
            draft.transaction_id, "failed", True, True, True, "uncertain"
        )
        monkeypatch.setattr(publication, "commit_recovery", lambda *_a, **_k: uncertain)
        assert service.commit_action(draft) is uncertain

    def test_real_non_daemon_commit_and_cancellation(self, prepared):
        draft = draft_for(prepared)
        event = threading.Event()
        event.set()
        assert not service.commit_action(draft, cancel_event=event).scope_may_have_changed
        results = []
        thread = threading.Thread(
            target=lambda: results.append(service.commit_action(draft)), daemon=True
        )
        thread.start()
        thread.join()
        assert results.pop().outcome == "failed"
        thread = threading.Thread(
            target=lambda: results.append(service.commit_action(draft)), daemon=False
        )
        thread.start()
        thread.join()
        assert results.pop().outcome == "committed"


class TestWorkers:
    @pytest.mark.parametrize("operation", ["assess", "prepare"])
    def test_worker_context_echo_is_mandatory(self, prepared, monkeypatch, operation):
        plan, _ = prepared
        if operation == "assess":
            valid = service.assess_layout(*roots(plan))
            text = replace(valid, config_root="/tmp/wrong-context").to_json()
        else:
            data = json.loads(draft_for(prepared).to_json())
            data["transaction_id"] = "0" * 32
            text = json.dumps(data)
        monkeypatch.setattr(
            health, "run_bounded", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, text, "")
        )
        with pytest.raises(ValueError, match="different"):
            if operation == "assess":
                service.run_assess(*roots(plan))
            else:
                draft_for(prepared)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("schema", True),
            ("kind", "v1-health"),
            ("extra", None),
            ("truncated", 1),
            ("mode", "healthy"),
        ],
    )
    def test_assessment_frames_are_strict(self, tmp_path, field, value):
        data = json.loads(service.assess_layout(tmp_path / "config", tmp_path / "state").to_json())
        data[field] = value
        with pytest.raises(ValueError):
            service.LayoutAssessment.from_json(json.dumps(data))

    @pytest.mark.parametrize("operation", ["assess", "prepare"])
    def test_cancel_timeout_malformed_and_context(self, prepared, monkeypatch, operation):
        plan, txid = prepared
        config, state = roots(plan)

        def run(**kwargs):
            return (
                service.run_assess(config, state, **kwargs)
                if operation == "assess"
                else service.run_prepare_action(config, state, txid, "resume", **kwargs)
            )

        event = threading.Event()
        event.set()
        with pytest.raises(InterruptedError):
            run(cancel_event=event)
        with pytest.raises(subprocess.TimeoutExpired):
            run(timeout=0.000001)

        def malformed(command, **kwargs):
            assert command[1:4] == ["-I", "-B", "-m"]
            assert kwargs["process_group"]
            assert kwargs["max_bytes"] == (
                service.MAX_ASSESS_BYTES if operation == "assess" else 8 * 1024 * 1024
            )
            return subprocess.CompletedProcess(command, 0, "{}", "")

        monkeypatch.setattr(health, "run_bounded", malformed)
        with pytest.raises(ValueError):
            run()

    def test_invalid_arguments_and_no_commit_cli(self, prepared):
        plan, txid = prepared
        for action in ("repair", "activate", "restore"):
            with pytest.raises(ValueError):
                service.run_prepare_action(*roots(plan), txid, action)
        with pytest.raises(ValueError):
            service.run_prepare_action(*roots(plan), "../escape", "resume")
        with pytest.raises(ValueError, match="worker refused"):
            service._run(*roots(plan), "commit", [], None, 10, 1024)

    def test_complete_two_scope_diff(self, plan):
        proposal = scoped_review.build_review(
            plan.evidence, {Scope.APPEARANCE: appearance("9"), Scope.DISPLAYS: displays("HDMI-A-8")}
        )
        bundle = store.prepare_transaction(proposal, state_root=roots(plan)[1])
        assert bundle is not None
        draft = service.run_prepare_action(*roots(plan), bundle.intent.transaction_id, "resume")
        assert draft.plan.scopes == proposal.scopes
        assert all(item.diff and item.diff_sha256 for item in draft.plan.scopes)
