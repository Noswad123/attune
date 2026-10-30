"""Canonical restore observations use isolated temporary installations only."""

import hashlib
import json
import os
import socket
import subprocess
import threading
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
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
