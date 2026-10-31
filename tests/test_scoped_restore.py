"""Canonical restore observations use isolated temporary installations only."""

import hashlib
import json
import os
import runpy
import socket
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError, asdict, fields, is_dataclass, replace
from pathlib import Path

import pytest

from hyprmod.core import health, persistence, route_approval, scoped_config, scoped_review
from hyprmod.core import scoped_restore as restore
from hyprmod.core import transaction_publication as publication
from hyprmod.core import transaction_store as store
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import MAX_RECORD_BYTES, Phase, canonical_json
from tests.test_scoped_review import appearance, displays, snapshot
from tests.test_scoped_review import evidence as evidence
from tests.test_transaction_store import plan as plan


def roots(plan):
    return Path(plan.evidence.config_root), Path(plan.evidence.state_root)


def terminal(plan, phase=Phase.COMMITTED):
    state = roots(plan)[1]
    bundle = store.prepare_transaction(plan, state_root=state)
    assert bundle is not None
    with store.exclusive_store_session(state) as session:
        return session.checkpoint(
            bundle,
            replace(
                bundle.intent,
                phase=phase,
                progress=bundle.intent.changed_scopes if phase is Phase.COMMITTED else (),
            ),
            fingerprint=store.verified_fingerprint(bundle),
        )


@pytest.fixture
def source(plan):
    return terminal(plan)


def prepare(source, scope=Scope.APPEARANCE, side="proposed"):
    return restore.prepare_restore(
        *roots(source.snapshot.plan), source.intent.transaction_id, scope, side
    )


def change_current(source):
    for route, model in zip(
        source.snapshot.plan.evidence.routes, (appearance("9"), displays("HDMI-A-7")), strict=True
    ):
        Path(route.file.path.resolved_path).write_text(scoped_config.build_text(model))


class TestPreparation:
    @pytest.mark.parametrize("changed", [(Scope.APPEARANCE,), (Scope.DISPLAYS,), tuple(Scope)])
    @pytest.mark.parametrize("phase", [Phase.COMMITTED, Phase.ABORTED])
    @pytest.mark.parametrize("scope", list(Scope))
    @pytest.mark.parametrize("side", ["prior", "proposed"])
    def test_complete_current_to_historical_goal(self, plan, phase, scope, side, changed):
        plan = scoped_review.build_review(
            plan.evidence,
            {
                s: appearance("7") if s is Scope.APPEARANCE else displays("HDMI-A-8")
                for s in changed
            },
        )
        source = terminal(plan, phase)
        change_current(source)
        before = snapshot(plan.evidence)
        draft = prepare(source, scope, side)
        selected = next(r for r in plan.scopes if r.scope is scope)
        text = selected.previous_text if side == "prior" else selected.proposed_text
        assert draft.source_phase is phase
        assert draft.source_snapshot == source.snapshot
        assert draft.source_snapshot_id == source.snapshot.snapshot_id
        model = scoped_config.read_document(text)
        if not isinstance(model, scoped_config.ScopedConfig):
            pytest.fail("Expected canonical scope fixture")
        assert draft.selected_descriptor.content_id == model.content_id
        assert draft.plan.changed_scopes == (scope,)
        for review in draft.plan.scopes:
            assert review.previous_text == Path(review.resolved_path).read_text()
            assert review.proposed_text == (text if review.scope is scope else review.previous_text)
        assert restore.ScopedRestoreDraft.from_json(draft.to_json()) == draft
        assert snapshot(plan.evidence) == before
        with pytest.raises(FrozenInstanceError):
            setattr(draft, "side", "prior")

    @pytest.mark.parametrize("scope", list(Scope))
    @pytest.mark.parametrize("side", ["prior", "proposed"])
    def test_noop_no_new_evidence_or_lock(self, source, scope, side):
        historical = next(r for r in source.snapshot.plan.scopes if r.scope is scope)
        path = Path(historical.resolved_path)
        path.write_text(historical.previous_text if side == "prior" else historical.proposed_text)
        root = roots(source.snapshot.plan)[1] / "attune"
        (root / "persistence.lock").unlink()
        before = {
            p: (p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_mode) for p in root.rglob("*")
        }
        assert prepare(source, scope, side).plan.changed_scopes == ()
        assert before == {
            p: (p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_mode) for p in root.rglob("*")
        }

    def test_old_source_after_later_terminal_both_scope_transaction(self, source):
        plan = source.snapshot.plan
        later = scoped_review.build_review(
            plan.evidence, {Scope.APPEARANCE: appearance("8"), Scope.DISPLAYS: displays("HDMI-A-8")}
        )
        terminal(later)
        change_current(source)
        assert prepare(source).plan.changed_scopes == (Scope.APPEARANCE,)

    @pytest.mark.parametrize("scope", list(Scope))
    @pytest.mark.parametrize("side", ["prior", "proposed"])
    def test_old_source_after_real_two_scope_publications(self, plan, scope, side):
        config_root, state_root = roots(plan)
        registry = Path(plan.evidence.registry.path.lexical_path)
        source_plan = scoped_review.build_review(
            plan.evidence,
            {Scope.APPEARANCE: appearance("7"), Scope.DISPLAYS: displays("HDMI-A-8")},
        )
        published = publication.publish_reviewed(
            source_plan, config_root=config_root, state_root=state_root
        )
        assert published.outcome == "committed", published.error
        if published.transaction_id is None:
            pytest.fail("Publication must return a transaction ID")
        source = store.load_transaction(state_root, published.transaction_id)
        assert source.intent.phase is Phase.COMMITTED
        current = route_approval.inspect_installation(
            registry, config_root=config_root, state_root=state_root
        )
        for review, route in zip(source_plan.scopes, current.routes, strict=True):
            assert Path(review.resolved_path).read_bytes() == review.proposed_text.encode("utf-8")
            assert route.file.source_sha256 == review.proposed_sha256

        later_plan = scoped_review.build_review(
            current,
            {Scope.APPEARANCE: appearance("9"), Scope.DISPLAYS: displays("HDMI-A-7")},
        )
        later = publication.publish_reviewed(
            later_plan, config_root=config_root, state_root=state_root
        )
        assert later.outcome == "committed", later.error
        assert later.transaction_id != published.transaction_id
        current = route_approval.inspect_installation(
            registry, config_root=config_root, state_root=state_root
        )
        before = snapshot(current)
        draft = restore.prepare_restore(
            config_root, state_root, published.transaction_id, scope, side
        )
        assert draft.source_snapshot == source.snapshot
        assert draft.source_phase is Phase.COMMITTED
        assert draft.plan.evidence.evidence_hash == current.evidence_hash
        assert draft.plan.changed_scopes == (scope,)
        for historical, installed, review, route in zip(
            source_plan.scopes, later_plan.scopes, draft.plan.scopes, current.routes, strict=True
        ):
            assert review.previous_text == installed.proposed_text
            assert Path(review.resolved_path).read_bytes() == installed.proposed_text.encode(
                "utf-8"
            )
            assert route.file.source_sha256 == installed.proposed_sha256
            selected = historical.previous_text if side == "prior" else historical.proposed_text
            assert review.proposed_text == (
                selected if review.scope is scope else installed.proposed_text
            )
        assert snapshot(current) == before

    def test_canonical_leaf_replacement_allowed(self, source):
        for route in source.snapshot.plan.evidence.routes:
            path = Path(route.file.path.resolved_path)
            temporary = path.with_suffix(".replacement")
            temporary.write_bytes(path.read_bytes())
            temporary.chmod(path.stat().st_mode)
            temporary.replace(path)
        assert prepare(source).plan.changed_scopes == (Scope.APPEARANCE,)
        listing = restore.list_sources(*roots(source.snapshot.plan))
        assert listing.status == "observed"
        assert listing.transactions[0].eligibility == "reviewable"

    def test_missing_store_not_provisioned(self, evidence):
        state = Path(evidence.state_root)
        state.mkdir()
        with pytest.raises(ValueError, match="Missing private store"):
            restore.prepare_restore(
                Path(evidence.config_root), state, "a" * 32, Scope.APPEARANCE, "prior"
            )
        assert list(state.iterdir()) == []

    @pytest.mark.parametrize("scope", list(Scope))
    @pytest.mark.parametrize("damage", ["foreign", "cross", "unreadable"])
    def test_damaged_current_selected_or_sibling(self, source, scope, damage):
        route = next(r for r in source.snapshot.plan.evidence.routes if r.scope is scope)
        path = Path(route.file.path.resolved_path)
        mode = path.stat().st_mode
        try:
            if damage == "unreadable":
                path.chmod(0o200)
            else:
                path.write_text(
                    "return {}\n"
                    if damage == "foreign"
                    else scoped_config.build_text(
                        displays() if scope is Scope.APPEARANCE else appearance()
                    )
                )
            with pytest.raises(ValueError):
                prepare(source)
        finally:
            path.chmod(mode)

    @pytest.mark.parametrize("drift", ["registry", "ancestor", "symlink", "git", "route"])
    def test_same_install_required(self, source, drift, tmp_path):
        evidence = source.snapshot.plan.evidence
        path = Path(evidence.routes[1].file.path.resolved_path)
        registry = Path(evidence.registry.path.resolved_path)
        if drift == "registry":
            temporary = registry.with_suffix(".replacement")
            temporary.write_bytes(registry.read_bytes())
            temporary.chmod(0o600)
            temporary.replace(registry)
        elif drift == "ancestor":
            old = path.parent.with_name("old")
            path.parent.rename(old)
            path.parent.mkdir()
            path.write_bytes((old / path.name).read_bytes())
        elif drift == "symlink":
            target = tmp_path / path.name
            path.rename(target)
            path.symlink_to(target)
        elif drift == "git":
            (path.parent / ".git").mkdir()
        else:
            path.chmod(0o600)
        if drift == "route":
            # Leaf permissions are intentionally excluded by route_binding().
            assert prepare(source).scope is Scope.APPEARANCE
        else:
            with pytest.raises(ValueError):
                prepare(source)


class TestPendingAndRaces:
    def test_existing_unrelated_terminal_corrupted_during_review(self, source, monkeypatch):
        state_root = roots(source.snapshot.plan)[1]
        unrelated = terminal(source.snapshot.plan)
        txid = unrelated.intent.transaction_id
        assert txid != source.intent.transaction_id
        ids = store.list_transaction_ids(state_root)
        original_build = scoped_review.build_review
        original_load = store.load_transaction
        corrupted = False
        loads = []

        def load(state, transaction_id):
            loads.append((transaction_id, corrupted))
            return original_load(state, transaction_id)

        def race(*args, **kwargs):
            nonlocal corrupted
            result = original_build(*args, **kwargs)
            path = state_root / "attune/transactions" / txid / "intent.json"
            path.write_text("{}")
            corrupted = True
            return result

        monkeypatch.setattr(store, "load_transaction", load)
        monkeypatch.setattr(scoped_review, "build_review", race)
        with pytest.raises(ValueError, match="Unexpected record fields"):
            prepare(source)
        assert store.list_transaction_ids(state_root) == ids
        assert (txid, False) in loads
        assert (txid, True) in loads

    @pytest.mark.parametrize("kind", ["source-pending", "other-pending", "corrupt", "overflow"])
    def test_refuses_even_noop(self, plan, kind, monkeypatch):
        if kind == "source-pending":
            bundle = store.prepare_transaction(plan, state_root=roots(plan)[1])
            assert bundle is not None
        else:
            bundle = terminal(plan)
            if kind == "other-pending":
                store.prepare_transaction(plan, state_root=roots(plan)[1])
            elif kind == "corrupt":
                directory = roots(plan)[1] / "attune/transactions" / ("f" * 32)
                directory.mkdir(mode=0o700)
                (directory / "intent.json").write_text("{}")
                (directory / "intent.json").chmod(0o600)
            else:
                monkeypatch.setattr(store, "MAX_JOURNALS", 0)
        with pytest.raises(ValueError):
            prepare(bundle, side="prior")

    @pytest.mark.parametrize("target", ["intent", "snapshot", "blob", "new-terminal"])
    def test_same_byte_source_replacement_and_new_journal_during_review(
        self, source, monkeypatch, target
    ):
        original = scoped_review.build_review

        def race(*args, **kwargs):
            result = original(*args, **kwargs)
            root = roots(source.snapshot.plan)[1] / "attune"
            if target != "new-terminal":
                path = {
                    "intent": root / "transactions" / source.intent.transaction_id / "intent.json",
                    "snapshot": root / "snapshots" / (source.snapshot.snapshot_id + ".json"),
                    "blob": root / "blobs" / (source.blobs[0].sha256 + ".lua"),
                }[target]
                temporary = path.with_suffix(".replacement")
                temporary.write_bytes(path.read_bytes())
                temporary.chmod(0o600)
                temporary.replace(path)
            else:
                directory = root / "transactions" / ("e" * 32)
                directory.mkdir(mode=0o700)
                path = directory / "intent.json"
                path.write_text(replace(source.intent, transaction_id="e" * 32).to_json())
                path.chmod(0o600)
            return result

        monkeypatch.setattr(scoped_review, "build_review", race)
        with pytest.raises(ValueError):
            prepare(source)

    @pytest.mark.parametrize("target", ["intent", "snapshot", "unselected-blob"])
    def test_complete_source_required(self, source, target):
        root = roots(source.snapshot.plan)[1] / "attune"
        path = {
            "intent": root / "transactions" / source.intent.transaction_id / "intent.json",
            "snapshot": root / "snapshots" / (source.snapshot.snapshot_id + ".json"),
            "unselected-blob": root / "blobs" / (source.blobs[-1].sha256 + ".lua"),
        }[target]
        path.write_text("damaged")
        with pytest.raises(ValueError):
            prepare(source, side="prior")

    def test_fresh_review_revalidation(self, source, monkeypatch):
        original = store.refuse_pending_readonly
        calls = 0

        def scan(state):
            nonlocal calls
            result = original(state)
            calls += 1
            if calls == 2:
                change_current(source)
            return result

        monkeypatch.setattr(store, "refuse_pending_readonly", scan)
        with pytest.raises(ValueError):
            prepare(source)


class TestDraftValidation:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("diff", "forged historical diff\n"),
            ("proposed_sha256", "0" * 64),
            ("previous_content_id", "0" * 64),
            ("added_lines", 99),
        ],
    )
    def test_rehashed_inconsistent_historical_snapshot_refused(self, source, field, value):
        draft = prepare(source)
        historical = draft.source_snapshot.plan
        changes = {field: value}
        if field == "diff":
            changes["diff_sha256"] = scoped_config.byte_hash(value)
        scopes = (replace(historical.scopes[0], **changes), historical.scopes[1])
        review_hash = scoped_review._review_hash(
            historical.evidence, scopes, historical.changed_scopes
        )
        data = json.loads(draft.to_json())
        recorded = data["source_snapshot"]["plan"]
        recorded["scopes"][0].update(changes)
        recorded["review_hash"] = review_hash
        data["source_snapshot_id"] = hashlib.sha256(
            canonical_json(data["source_snapshot"]).encode("ascii")
        ).hexdigest()
        assert data["source_snapshot_id"] != draft.source_snapshot_id
        with pytest.raises(ValueError, match="Recorded scope differs"):
            restore.ScopedRestoreDraft.from_json(canonical_json(data))

    def test_decoded_draft_recursively_immutable(self, source):
        draft = restore.ScopedRestoreDraft.from_json(prepare(source).to_json())

        def immutable(value):
            assert not isinstance(value, (dict, list, set, bytearray))
            if is_dataclass(value) and not isinstance(value, type):
                assert getattr(value, "__dataclass_params__").frozen
                assert hasattr(type(value), "__slots__")
                for field in fields(value):
                    immutable(getattr(value, field.name))
            elif isinstance(value, tuple):
                for item in value:
                    immutable(item)
            else:
                assert isinstance(value, (str, int, type(None)))

        immutable(draft)

    @pytest.mark.parametrize("historical", [False, True])
    @pytest.mark.parametrize(
        "target", ["routes", "protected", "counts", "facts", "identity", "git"]
    )
    def test_direct_nested_mutable_evidence_rejected(self, source, historical, target):
        draft = prepare(source)
        plan = draft.source_snapshot.plan if historical else draft.plan
        evidence = plan.evidence
        registry = evidence.registry
        if target == "routes":
            evidence = replace(evidence, routes=list(evidence.routes))
        elif target == "protected":
            evidence = replace(evidence, protected=list(evidence.protected))
        elif target == "counts":
            route = replace(evidence.routes[0], counts=list(evidence.routes[0].counts))
            evidence = replace(evidence, routes=(route, evidence.routes[1]))
        elif target == "git":
            evidence = replace(
                evidence, registry=replace(registry, git_context=list(registry.git_context))
            )
        else:
            proof = registry.path
            facts = proof.facts
            if target == "identity":
                fact = replace(facts[0], identity=list(facts[0].identity))
                proof = replace(proof, facts=(fact, *facts[1:]))
            else:
                proof = replace(proof, facts=list(facts))
            evidence = replace(evidence, registry=replace(registry, path=proof))
        forged = replace(plan, evidence=evidence)
        assert forged.evidence.evidence_hash == plan.evidence.evidence_hash
        with pytest.raises(ValueError, match="Noncanonical evidence structure"):
            if historical:
                replace(draft, source_snapshot=replace(draft.source_snapshot, plan=forged))
            else:
                replace(draft, plan=forged)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("schema", True),
            ("kind", "other"),
            ("scope", False),
            ("side", "previous"),
            ("source_phase", "publishing"),
            ("source_snapshot_id", "0" * 64),
            ("source_private_digest", "bad"),
            ("transaction_id", "../bad"),
            ("config_root", []),
            ("extra", 1),
        ],
    )
    def test_strict_frame(self, source, field, value):
        data = json.loads(prepare(source).to_json())
        data[field] = value
        with pytest.raises(ValueError):
            restore.ScopedRestoreDraft.from_json(canonical_json(data))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("counts", [99, 0, 0, 0]),
            ("version", True),
            ("size_bytes", True),
            ("content_id", "0" * 64),
            ("sha256", "0" * 64),
            ("scope", "displays"),
        ],
    )
    def test_descriptor_recomputed(self, source, field, value):
        data = json.loads(prepare(source).to_json())
        data["selected_descriptor"][field] = value
        with pytest.raises(ValueError):
            restore.ScopedRestoreDraft.from_json(canonical_json(data))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("diff", "forged"),
            ("added_lines", 12),
            ("removed_lines", True),
            ("proposed_sha256", "0" * 64),
            ("previous_content_id", "0" * 64),
        ],
    )
    def test_rehashed_inconsistent_plan_refused(self, source, field, value):
        draft = prepare(source)
        scopes = (replace(draft.plan.scopes[0], **{field: value}), draft.plan.scopes[1])
        forged = replace(
            draft.plan,
            scopes=scopes,
            review_hash=scoped_review._review_hash(
                draft.plan.evidence, scopes, draft.plan.changed_scopes
            ),
        )
        with pytest.raises(ValueError):
            replace(draft, plan=forged)

    @pytest.mark.parametrize("scope", list(Scope))
    def test_valid_rehashed_wrong_selected_or_sibling_goal(self, source, scope):
        draft = prepare(source)
        forged = scoped_review.build_review(
            draft.plan.evidence,
            {scope: appearance("8") if scope is Scope.APPEARANCE else displays("HDMI-A-8")},
        )
        with pytest.raises(ValueError, match="exact historical"):
            replace(draft, plan=forged)

    @pytest.mark.parametrize(
        "text",
        [
            '{"schema":1,"schema":1}',
            "[" * 25 + "]" * 25,
            '"\\ud800"',
            '{"schema":NaN}',
            "x" * (MAX_RECORD_BYTES + 1),
        ],
    )
    def test_bad_json(self, text):
        with pytest.raises(ValueError):
            restore.ScopedRestoreDraft.from_json(text)

    def test_aggregate_ascii_escaped_limit(self, source):
        data = json.loads(prepare(source).to_json())
        data["plan"]["observed_at"] = "\u2603" * (MAX_RECORD_BYTES // 5)
        text = json.dumps(data, ensure_ascii=False)
        assert len(text.encode("utf-8")) < MAX_RECORD_BYTES
        with pytest.raises(ValueError, match="transport limit"):
            restore.ScopedRestoreDraft.from_json(text)

    @pytest.mark.parametrize("container", ["plan", "source_snapshot", "selected_descriptor"])
    def test_nested_unknown_and_duplicate_fields(self, source, container):
        data = json.loads(prepare(source).to_json())
        data[container]["extra"] = 0
        with pytest.raises(ValueError):
            restore.ScopedRestoreDraft.from_json(canonical_json(data))
        text = prepare(source).to_json().replace('"schema":1', '"schema":1,"schema":1', 1)
        with pytest.raises(ValueError, match="Duplicate"):
            restore.ScopedRestoreDraft.from_json(text)

    def test_pure_validation_without_filesystem(self, source, monkeypatch):
        text = prepare(source).to_json()

        def forbidden(*args, **kwargs):
            pytest.fail("Pure draft validation touched filesystem")

        monkeypatch.setattr(os, "open", forbidden)
        monkeypatch.setattr(Path, "lstat", forbidden)
        assert restore.ScopedRestoreDraft.from_json(text).to_json() == text


class TestWorkerAndSafety:
    @pytest.mark.parametrize(
        "scope,side",
        [
            ("appearance", "prior"),
            (Scope.APPEARANCE, "previous"),
            (Scope.APPEARANCE, True),
            (False, "proposed"),
        ],
    )
    def test_strict_request_before_worker(self, source, monkeypatch, scope, side):
        def forbidden(*args, **kwargs):
            pytest.fail("Invalid request reached worker")

        monkeypatch.setattr(health, "run_bounded", forbidden)
        with pytest.raises(ValueError):
            restore.run_prepare(
                *roots(source.snapshot.plan), source.intent.transaction_id, scope, side
            )

    def test_worker_refusal(self, source, monkeypatch):
        monkeypatch.setattr(
            health,
            "run_bounded",
            lambda *a, **k: subprocess.CompletedProcess([], 1, "", "source refused"),
        )
        with pytest.raises(ValueError, match="source refused"):
            restore.run_prepare(
                *roots(source.snapshot.plan),
                source.intent.transaction_id,
                Scope.APPEARANCE,
                "proposed",
            )

    def test_actual_isolated_worker(self, source):
        draft = restore.run_prepare(
            *roots(source.snapshot.plan), source.intent.transaction_id, Scope.DISPLAYS, "prior"
        )
        assert draft.plan.changed_scopes == ()

    @pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), float("nan")])
    def test_timeout_boundary(self, source, timeout):
        with pytest.raises(ValueError):
            restore.run_prepare(
                *roots(source.snapshot.plan),
                source.intent.transaction_id,
                Scope.APPEARANCE,
                "proposed",
                timeout=timeout,
            )

    def test_cancel_and_timeout(self, source):
        event = threading.Event()
        event.set()
        with pytest.raises(InterruptedError):
            restore.run_prepare(
                *roots(source.snapshot.plan),
                source.intent.transaction_id,
                Scope.APPEARANCE,
                "prior",
                cancel_event=event,
            )
        with pytest.raises(subprocess.TimeoutExpired):
            restore.run_prepare(
                *roots(source.snapshot.plan),
                source.intent.transaction_id,
                Scope.APPEARANCE,
                "prior",
                timeout=0.00001,
            )

    def test_worker_flags_and_strict_echo(self, source, monkeypatch):
        draft = prepare(source)
        event = threading.Event()

        def run(argv, **kwargs):
            assert argv[1:3] == ["-I", "-B"]
            assert argv[5] == "prepare"
            assert kwargs["process_group"] is True
            assert kwargs["max_bytes"] == MAX_RECORD_BYTES
            assert kwargs["cancel_event"] is event
            return subprocess.CompletedProcess(argv, 0, draft.to_json(), "")

        monkeypatch.setattr(health, "run_bounded", run)
        with pytest.raises(ValueError, match="different restore"):
            restore.run_prepare(
                *roots(source.snapshot.plan),
                source.intent.transaction_id,
                Scope.APPEARANCE,
                "prior",
                cancel_event=event,
            )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("config_root", "/elsewhere"),
            ("state_root", "/elsewhere"),
            ("transaction_id", "f" * 32),
            ("scope", Scope.DISPLAYS),
            ("side", "prior"),
        ],
    )
    def test_each_echo_field(self, source, monkeypatch, field, value):
        draft = prepare(source)
        # Echo checking is independent of the DTO's internal semantic validation.
        monkeypatch.setattr(
            restore.ScopedRestoreDraft, "from_json", classmethod(lambda cls, text: draft)
        )
        monkeypatch.setattr(
            health, "run_bounded", lambda *a, **k: subprocess.CompletedProcess([], 0, "{}", "")
        )
        with pytest.raises(ValueError, match="different restore"):
            restore.run_prepare(
                Path(value) if field == "config_root" else Path(draft.config_root),
                Path(value) if field == "state_root" else Path(draft.state_root),
                value if field == "transaction_id" else draft.transaction_id,
                value if field == "scope" else draft.scope,
                value if field == "side" else draft.side,
            )

    @pytest.mark.parametrize("output", ["x" * (MAX_RECORD_BYTES + 1), "{}"])
    def test_worker_oversized_or_malformed_output(self, source, monkeypatch, output):
        monkeypatch.setattr(
            health, "run_bounded", lambda *a, **k: subprocess.CompletedProcess([], 0, output, "")
        )
        with pytest.raises(ValueError):
            restore.run_prepare(
                *roots(source.snapshot.plan),
                source.intent.transaction_id,
                Scope.APPEARANCE,
                "proposed",
            )

    def test_no_writes_compilation_main_lua_or_ipc(self, source, monkeypatch):
        original_open = os.open
        original_read = persistence.read_stable

        def readonly_open(path, flags, *args, **kwargs):
            assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            return original_open(path, flags, *args, **kwargs)

        def read(path, **kwargs):
            assert Path(path).name not in ("hyprland.lua", "attune.lua", "hyprland.conf")
            return original_read(path, **kwargs)

        def forbidden(*args, **kwargs):
            pytest.fail("Read-only restore attempted a side effect")

        monkeypatch.setattr(os, "open", readonly_open)
        monkeypatch.setattr(persistence, "read_stable", read)
        for method in ("mkdir", "write_bytes", "write_text", "chmod", "rename", "unlink"):
            monkeypatch.setattr(Path, method, forbidden)
        for method in ("write", "mkdir", "replace", "rename", "unlink", "chmod"):
            monkeypatch.setattr(os, method, forbidden)
        for method in ("initialize_store", "exclusive_store_session", "prepare_transaction"):
            monkeypatch.setattr(store, method, forbidden)
        monkeypatch.setattr(subprocess, "Popen", forbidden)
        monkeypatch.setattr(socket, "socket", forbidden)
        monkeypatch.setattr(persistence, "validate_lua", forbidden)
        monkeypatch.setattr(persistence, "persist_snapshot", forbidden)
        prepare(source)
        assert restore.list_sources(*roots(source.snapshot.plan)).status == "observed"


class TestSourceListing:
    @pytest.mark.parametrize("phase", [Phase.COMMITTED, Phase.ABORTED])
    def test_complete_ordered_sources_and_no_effects(self, plan, phase):
        source = terminal(plan, phase)
        before = snapshot(plan.evidence)
        listing = restore.list_sources(*roots(plan))
        assert listing.status == "observed"
        assert listing.scan_complete and not listing.truncated
        assert listing.notes == ()
        (row,) = listing.transactions
        assert (row.transaction_id, row.validity, row.phase, row.eligibility) == (
            source.intent.transaction_id,
            "verified",
            phase,
            "reviewable",
        )
        assert [(s.scope, s.side) for s in row.sources] == [
            (scope, side) for scope in Scope for side in ("prior", "proposed")
        ]
        for item in row.sources:
            assert item.descriptor == restore._selected(source.snapshot, item.scope, item.side)[1]
        # The unchanged display scope still exposes both choices, without deduplication.
        assert row.sources[2].descriptor == row.sources[3].descriptor
        assert restore.ScopedRestoreListing.from_json(listing.to_json()) == listing
        assert snapshot(plan.evidence) == before
        with pytest.raises(FrozenInstanceError):
            setattr(row, "eligibility", "blocked")

    def test_empty_initialized_store(self, plan):
        listing = restore.list_sources(*roots(plan))
        assert listing.status == "observed" and listing.scan_complete
        assert listing.transactions == ()
        assert not (roots(plan)[1] / "attune/persistence.lock").exists()

    def test_missing_store_not_initialized(self, evidence):
        state = Path(evidence.state_root)
        state.mkdir()
        listing = restore.list_sources(Path(evidence.config_root), state)
        assert listing.status == "blocked" and not listing.scan_complete
        assert listing.transactions == ()
        assert "Missing private store" in listing.notes[0]
        assert list(state.iterdir()) == []

    @pytest.mark.parametrize("damage", ["pending", "corrupt", "unknown", "symlink", "overflow"])
    def test_global_blockers(self, source, damage, monkeypatch):
        config, state = roots(source.snapshot.plan)
        directory = state / "attune/transactions"
        if damage == "pending":
            store.prepare_transaction(source.snapshot.plan, state_root=state)
        elif damage == "corrupt":
            (directory / source.intent.transaction_id / "intent.json").write_text("{}")
        elif damage == "unknown":
            (directory / "not-a-transaction").mkdir(mode=0o700)
        elif damage == "symlink":
            (directory / ("f" * 32)).symlink_to(directory / source.intent.transaction_id)
        else:
            monkeypatch.setattr(store, "MAX_JOURNALS", 0)
        listing = restore.list_sources(config, state)
        assert listing.status == "blocked" and not listing.scan_complete
        assert listing.notes
        assert all(row.eligibility == "blocked" for row in listing.transactions)
        if damage in ("unknown", "symlink", "overflow"):
            assert listing.transactions == ()
        if damage == "corrupt":
            (row,) = listing.transactions
            assert row.validity == "invalid" and row.phase is None and row.sources == ()

    @pytest.mark.parametrize("scope", list(Scope))
    @pytest.mark.parametrize("damage", ["foreign", "cross", "unreadable"])
    def test_current_pair_required(self, source, scope, damage):
        route = next(r for r in source.snapshot.plan.evidence.routes if r.scope is scope)
        path = Path(route.file.path.resolved_path)
        mode = path.stat().st_mode
        try:
            if damage == "unreadable":
                path.chmod(0o200)
            else:
                path.write_text(
                    "return {}\n"
                    if damage == "foreign"
                    else scoped_config.build_text(
                        displays() if scope is Scope.APPEARANCE else appearance()
                    )
                )
            listing = restore.list_sources(*roots(source.snapshot.plan))
            assert listing.status == "blocked" and listing.scan_complete
            assert all(r.eligibility == "blocked" for r in listing.transactions)
        finally:
            path.chmod(mode)

    @pytest.mark.parametrize("drift", ["registry", "ancestor", "git"])
    def test_same_install_mismatch_is_row_local(self, source, drift):
        evidence = source.snapshot.plan.evidence
        path = Path(evidence.routes[1].file.path.resolved_path)
        if drift == "registry":
            path = Path(evidence.registry.path.resolved_path)
            temporary = path.with_suffix(".replacement")
            temporary.write_bytes(path.read_bytes())
            temporary.chmod(path.stat().st_mode)
            temporary.replace(path)
        elif drift == "ancestor":
            old = path.parent.with_name("old")
            path.parent.rename(old)
            path.parent.mkdir()
            path.write_bytes((old / path.name).read_bytes())
        else:
            (path.parent / ".git").mkdir()
        listing = restore.list_sources(*roots(source.snapshot.plan))
        if drift == "git":
            assert listing.status == "blocked" and listing.scan_complete
            assert all(r.eligibility == "blocked" for r in listing.transactions)
            return
        assert listing.status == "observed" and listing.scan_complete
        (row,) = listing.transactions
        assert row.validity == "verified" and row.eligibility == "blocked"
        assert "same installation" in row.notes[0]
        if drift == "registry":
            config, state = roots(source.snapshot.plan)
            current = route_approval.inspect_installation(
                config / "attune/installation.json", config_root=config, state_root=state
            )
            newer = terminal(
                scoped_review.build_review(current, {Scope.APPEARANCE: appearance("8")})
            )
            listing = restore.list_sources(config, state)
            assert listing.status == "observed"
            assert {r.transaction_id: r.eligibility for r in listing.transactions} == {
                source.intent.transaction_id: "blocked",
                newer.intent.transaction_id: "reviewable",
            }

    def test_bounded_global_reason(self, source, monkeypatch):
        def scan(*args):
            raise ValueError("\u2603" * 2000)

        monkeypatch.setattr(store, "refuse_pending_readonly", scan)
        listing = restore.list_sources(*roots(source.snapshot.plan))
        assert listing.status == "blocked" and not listing.scan_complete
        assert len(listing.notes[0].encode("utf-8")) <= 1024
        assert restore.ScopedRestoreListing.from_json(listing.to_json()) == listing

    @pytest.mark.parametrize("hidden", [None, "pending", "corrupt"])
    def test_display_cap_does_not_cap_safety_scan(self, plan, hidden):
        state = roots(plan)[1]
        ids = [f"{n:032x}" for n in range(1, restore.MAX_SOURCE_TRANSACTIONS + 2)]
        for txid in reversed(ids):
            bundle = store.prepare_transaction(plan, state_root=state, transaction_id=txid)
            if bundle is None:
                pytest.fail("Expected changed fixture")
            with store.exclusive_store_session(state) as session:
                session.checkpoint(
                    bundle,
                    replace(bundle.intent, phase=Phase.ABORTED),
                    fingerprint=store.verified_fingerprint(bundle),
                )
        if hidden:
            path = state / "attune/transactions" / ids[-1] / "intent.json"
            if hidden == "corrupt":
                path.write_text("{}")
            else:
                bundle = store.load_transaction(state, ids[-1])
                path.write_text(replace(bundle.intent, phase=Phase.PREPARED).to_json())
        listing = restore.list_sources(*roots(plan))
        assert listing.truncated
        assert [r.transaction_id for r in listing.transactions] == ids[:32]
        assert len(listing.transactions) == restore.MAX_SOURCE_TRANSACTIONS
        assert sum(len(r.sources) for r in listing.transactions) == 128
        assert listing.status == ("blocked" if hidden else "observed")
        assert listing.scan_complete is (hidden is None)
        assert all(
            r.eligibility == ("blocked" if hidden else "reviewable") for r in listing.transactions
        )

    def test_old_terminal_after_actual_later_publications(self, plan):
        config, state = roots(plan)
        plan = scoped_review.build_review(
            plan.evidence, {Scope.APPEARANCE: appearance("7"), Scope.DISPLAYS: displays("HDMI-A-8")}
        )
        first = publication.publish_reviewed(plan, config_root=config, state_root=state)
        assert first.outcome == "committed", first.error
        current = route_approval.inspect_installation(
            config / "attune/installation.json", config_root=config, state_root=state
        )
        later = scoped_review.build_review(
            current, {Scope.APPEARANCE: appearance("9"), Scope.DISPLAYS: displays("HDMI-A-7")}
        )
        second = publication.publish_reviewed(later, config_root=config, state_root=state)
        assert second.outcome == "committed", second.error
        listing = restore.list_sources(config, state)
        assert listing.status == "observed" and len(listing.transactions) == 2
        assert all(row.eligibility == "reviewable" for row in listing.transactions)


class TestListingRaces:
    @pytest.mark.parametrize(
        "target", ["registry", "intent", "snapshot", "blob", "lost", "new", "pending", "current"]
    )
    def test_changes_between_scans_block(self, source, monkeypatch, target):
        config, state = roots(source.snapshot.plan)
        original = store.refuse_pending_readonly
        calls = 0

        def scan(root):
            nonlocal calls
            ids = original(root)
            calls += 1
            if calls == 2:
                if target == "current":
                    change_current(source)
                elif target == "new":
                    terminal(source.snapshot.plan)
                    return original(root)
                elif target == "pending":
                    store.prepare_transaction(source.snapshot.plan, state_root=state)
                    return original(root)
                else:
                    path = {
                        "registry": config / "attune/installation.json",
                        "intent": state
                        / "attune/transactions"
                        / source.intent.transaction_id
                        / "intent.json",
                        "snapshot": state
                        / "attune/snapshots"
                        / (source.snapshot.snapshot_id + ".json"),
                        "blob": state / "attune/blobs" / (source.blobs[0].sha256 + ".lua"),
                        "lost": state / "attune/blobs" / (source.blobs[0].sha256 + ".lua"),
                    }[target]
                    if target == "lost":
                        path.unlink()
                    else:
                        temporary = path.with_suffix(".replacement")
                        temporary.write_bytes(path.read_bytes())
                        temporary.chmod(path.stat().st_mode)
                        temporary.replace(path)
            return ids

        monkeypatch.setattr(store, "refuse_pending_readonly", scan)
        listing = restore.list_sources(config, state)
        assert calls == 2
        assert listing.status == "blocked"
        assert all(r.eligibility == "blocked" for r in listing.transactions)


class TestListingValidation:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("schema", True),
            ("kind", "other"),
            ("config_root", []),
            ("state_root", "relative"),
            ("status", "ready"),
            ("scan_complete", 1),
            ("truncated", 0),
            ("extra", 0),
            ("transactions", {}),
            ("notes", "bad"),
            ("notes", ["x"] * 17),
            ("notes", ["\u2603" * 342]),
            ("notes", ["\ud800"]),
        ],
    )
    def test_strict_listing_frame(self, source, field, value):
        data = json.loads(restore.list_sources(*roots(source.snapshot.plan)).to_json())
        data[field] = value
        with pytest.raises(ValueError):
            restore.ScopedRestoreListing.from_json(canonical_json(data))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("transaction_id", "../bad"),
            ("validity", "unknown"),
            ("phase", True),
            ("phase", "prepared"),
            ("eligibility", "ready"),
            ("sources", []),
            ("notes", ["x"] * 17),
            ("extra", 0),
        ],
    )
    def test_strict_transaction_frame(self, source, field, value):
        data = json.loads(restore.list_sources(*roots(source.snapshot.plan)).to_json())
        data["transactions"][0][field] = value
        with pytest.raises(ValueError):
            restore.ScopedRestoreListing.from_json(canonical_json(data))

    @pytest.mark.parametrize("target", ["source", "descriptor"])
    def test_nested_unknown_duplicate_fields(self, source, target):
        listing = restore.list_sources(*roots(source.snapshot.plan))
        data = json.loads(listing.to_json())
        item = data["transactions"][0]["sources"][0]
        if target == "descriptor":
            item = item["descriptor"]
        item["extra"] = 0
        with pytest.raises(ValueError):
            restore.ScopedRestoreListing.from_json(canonical_json(data))
        text = listing.to_json().replace('"side":"prior"', '"side":"prior","side":"prior"', 1)
        with pytest.raises(ValueError, match="Duplicate"):
            restore.ScopedRestoreListing.from_json(text)

    @pytest.mark.parametrize("damage", ["scope", "side", "counts", "version", "kind", "order"])
    def test_strict_sources(self, source, damage):
        data = json.loads(restore.list_sources(*roots(source.snapshot.plan)).to_json())
        sources = data["transactions"][0]["sources"]
        if damage == "order":
            sources.reverse()
        elif damage in ("scope", "side"):
            sources[0][damage] = "displays" if damage == "scope" else "previous"
        else:
            sources[0]["descriptor"][damage] = {
                "counts": [True, 0, 0, 0],
                "version": True,
                "kind": "legacy-full-bundle",
            }[damage]
        with pytest.raises(ValueError):
            restore.ScopedRestoreListing.from_json(canonical_json(data))

    @pytest.mark.parametrize(
        "damage",
        [
            "rows-list",
            "sources-list",
            "notes-list",
            "duplicate",
            "unsorted",
            "too-many",
            "blocked",
            "incomplete",
            "invalid",
        ],
    )
    def test_direct_structural_invariants(self, source, damage):
        listing = restore.list_sources(*roots(source.snapshot.plan))
        (row,) = listing.transactions
        with pytest.raises(ValueError):
            if damage == "rows-list":
                replace(listing, transactions=list(listing.transactions))
            elif damage == "sources-list":
                replace(row, sources=list(row.sources))
            elif damage == "notes-list":
                replace(row, notes=[])
            elif damage == "duplicate":
                replace(listing, transactions=(row, row))
            elif damage == "unsorted":
                replace(
                    listing,
                    transactions=(
                        replace(row, transaction_id="f" * 32),
                        replace(row, transaction_id="0" * 32),
                    ),
                )
            elif damage == "too-many":
                replace(
                    listing,
                    transactions=tuple(replace(row, transaction_id=f"{n:032x}") for n in range(33)),
                )
            elif damage == "blocked":
                replace(listing, status="blocked", notes=("blocked",))
            elif damage == "incomplete":
                replace(listing, scan_complete=False)
            else:
                replace(row, validity="invalid")

    @pytest.mark.parametrize(
        "text",
        [
            '{"schema":1,"schema":1}',
            "[" * 25 + "]" * 25,
            '"\\ud800"',
            '{"schema":NaN}',
            "x" * (restore.MAX_LIST_BYTES + 1),
        ],
    )
    def test_bad_json(self, text):
        with pytest.raises(ValueError):
            restore.ScopedRestoreListing.from_json(text)

    def test_canonical_ascii_transport_cap(self, source):
        listing = restore.list_sources(*roots(source.snapshot.plan))
        (row,) = listing.transactions
        rows = tuple(
            replace(row, transaction_id=f"{n:032x}", notes=("\u0080" * 512,) * 16)
            for n in range(restore.MAX_SOURCE_TRANSACTIONS)
        )
        data = json.loads(listing.to_json())
        data["transactions"] = [asdict(r) for r in rows]
        text = json.dumps(data, ensure_ascii=False)
        assert len(text.encode("utf-8")) < restore.MAX_LIST_BYTES
        with pytest.raises(ValueError, match="transport limit"):
            restore.ScopedRestoreListing.from_json(text)
        with pytest.raises(ValueError, match="transport limit"):
            replace(listing, transactions=rows)

    def test_pure_deeply_immutable_roundtrip(self, source, monkeypatch):
        listing = restore.list_sources(*roots(source.snapshot.plan))
        text = listing.to_json()

        def forbidden(*args, **kwargs):
            pytest.fail("Pure listing validation touched filesystem")

        monkeypatch.setattr(os, "open", forbidden)
        monkeypatch.setattr(Path, "lstat", forbidden)
        decoded = restore.ScopedRestoreListing.from_json(text)
        assert decoded == listing
        assert type(decoded.transactions) is tuple
        for row in decoded.transactions:
            assert type(row.sources) is tuple and type(row.notes) is tuple
            for item in row.sources:
                assert type(item.descriptor.counts) is tuple
                with pytest.raises(FrozenInstanceError):
                    setattr(item, "side", "proposed")


class TestListingWorker:
    def test_actual_isolated_listing_worker(self, source):
        before = snapshot(source.snapshot.plan.evidence)
        expected = restore.list_sources(*roots(source.snapshot.plan))
        assert expected.status == "observed" and expected.scan_complete
        assert restore.run_list(*roots(source.snapshot.plan)) == expected
        assert snapshot(source.snapshot.plan.evidence) == before

    @pytest.mark.parametrize(
        "selection",
        [
            ["list", "--txid", "a" * 32],
            ["list", "--scope", "appearance"],
            ["list", "--side", "prior"],
            ["prepare"],
            ["prepare", "--txid", "a" * 32, "--scope", "unknown", "--side", "prior"],
        ],
    )
    def test_cli_rejects_invalid_modes_or_selections(self, monkeypatch, selection):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "scoped_restore",
                *selection,
                "--config-root",
                "/unused-config",
                "--state-root",
                "/unused-state",
            ],
        )
        with pytest.raises(SystemExit) as result:
            runpy.run_path(str(Path(restore.__file__)), run_name="__main__")
        assert result.value.code == 2

    def test_worker_flags_and_echo(self, source, monkeypatch):
        listing = restore.list_sources(*roots(source.snapshot.plan))
        event = threading.Event()

        def run(argv, **kwargs):
            assert argv[1:6] == ["-I", "-B", "-m", "hyprmod.core.scoped_restore", "list"]
            assert "--txid" not in argv and "--scope" not in argv and "--side" not in argv
            assert kwargs["max_bytes"] == restore.MAX_LIST_BYTES
            assert kwargs["process_group"] is True
            assert kwargs["cancel_event"] is event and kwargs["timeout"] == 30
            return subprocess.CompletedProcess(argv, 0, listing.to_json(), "")

        monkeypatch.setattr(health, "run_bounded", run)
        assert restore.run_list(*roots(source.snapshot.plan), cancel_event=event) == listing
        for config, state in (
            (Path("/elsewhere"), Path(listing.state_root)),
            (Path(listing.config_root), Path("/elsewhere")),
        ):
            with pytest.raises(ValueError, match="different listing context"):
                restore.run_list(config, state, cancel_event=event)

    @pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), float("nan")])
    def test_invalid_timeout_before_worker(self, source, monkeypatch, timeout):
        def forbidden(*args, **kwargs):
            pytest.fail("Invalid request reached worker")

        monkeypatch.setattr(health, "run_bounded", forbidden)
        with pytest.raises(ValueError):
            restore.run_list(*roots(source.snapshot.plan), timeout=timeout)

    @pytest.mark.parametrize("root", ["relative", "string", "dotdot"])
    def test_invalid_context_before_worker(self, source, monkeypatch, root):
        def forbidden(*args, **kwargs):
            pytest.fail("Invalid request reached worker")

        monkeypatch.setattr(health, "run_bounded", forbidden)
        config, state = roots(source.snapshot.plan)
        config = {"relative": Path("relative"), "string": str(config), "dotdot": config / ".."}[
            root
        ]
        with pytest.raises(ValueError):
            restore.run_list(config, state)
        with pytest.raises(ValueError):
            restore.list_sources(config, state)

    @pytest.mark.parametrize("error", [InterruptedError(), subprocess.TimeoutExpired("worker", 1)])
    def test_cancel_timeout_propagated(self, source, monkeypatch, error):
        def run(*args, **kwargs):
            raise error

        monkeypatch.setattr(health, "run_bounded", run)
        with pytest.raises(type(error)):
            restore.run_list(*roots(source.snapshot.plan))

    @pytest.mark.parametrize(
        "code,output", [(1, ""), (0, "{}"), (0, "x" * (restore.MAX_LIST_BYTES + 1))]
    )
    def test_bad_worker_output(self, source, monkeypatch, code, output):
        monkeypatch.setattr(
            health,
            "run_bounded",
            lambda *a, **k: subprocess.CompletedProcess([], code, output, "refused"),
        )
        with pytest.raises(ValueError):
            restore.run_list(*roots(source.snapshot.plan))
