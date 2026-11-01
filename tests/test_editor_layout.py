"""Read-only editor entry and review against temporary registered pairs."""

import json
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from hyprmod.core import editor_layout as editor
from hyprmod.core import health, route_approval, scoped_config, scoped_review
from hyprmod.core import transaction_publication as publication
from hyprmod.core import transaction_store as store
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import MAX_RECORD_BYTES, Phase, plan_to_json
from tests.test_scoped_restore import terminal
from tests.test_scoped_review import appearance, displays, snapshot
from tests.test_scoped_review import evidence as evidence
from tests.test_transaction_store import plan as plan


def roots(plan):
    return Path(plan.evidence.config_root), Path(plan.evidence.state_root)


def pair_for(plan):
    entry = editor.inspect_entry(*roots(plan))
    if entry.pair is None:
        pytest.fail(entry.message or "Expected canonical pair")
    return entry.pair


def tree(root):
    return {
        p: (
            p.lstat().st_ino,
            p.lstat().st_mtime_ns,
            p.lstat().st_mode,
            p.read_bytes() if p.is_file() else None,
        )
        for p in root.rglob("*")
    }


class TestEntry:
    def test_initialized_zero_journals_ready_no_effects(self, plan, monkeypatch):
        config, state = roots(plan)
        before = tree(config.parent)

        def forbidden(*args, **kwargs):
            pytest.fail("Entry attempted mutation, compilation or old-goal assessment")

        monkeypatch.setattr(store, "initialize_store", forbidden)
        monkeypatch.setattr(store, "exclusive_store_session", forbidden)
        monkeypatch.setattr(publication, "publish_reviewed", forbidden)
        entry = editor.inspect_entry(config, state)
        assert entry.mode == "pair-ready"
        assert entry.pair is not None
        assert entry.pair.appearance == appearance()
        assert entry.pair.displays == displays()
        assert entry.pair.evidence.evidence_hash == plan.evidence.evidence_hash
        assert editor.EditorEntry.from_json(entry.to_json()) == entry
        assert tree(config.parent) == before

    def test_legacy_metadata_only_no_creation(self, tmp_path, monkeypatch):
        config, state = tmp_path / "missing-config", tmp_path / "missing-state"

        def forbidden(*args, **kwargs):
            pytest.fail("Legacy entry read file content or scoped state")

        monkeypatch.setattr(store, "inspect_store", forbidden)
        monkeypatch.setattr(route_approval, "inspect_installation", forbidden)
        entry = editor.inspect_entry(config, state)
        assert entry == editor.EditorEntry(str(config), str(state), "legacy-clear", None, None)
        assert not config.exists() and not state.exists()

    def test_missing_store_blocks_without_provisioning(self, evidence):
        state = Path(evidence.state_root)
        entry = editor.inspect_entry(Path(evidence.config_root), state)
        assert entry.mode == "blocked"
        assert entry.message and "store" in entry.message and "manual" in entry.message
        assert editor.run_entry(Path(evidence.config_root), state).mode == "blocked"
        assert not state.exists()

    @pytest.mark.parametrize("problem", ["foreign", "missing", "wrong-scope", "registry"])
    def test_invalid_outputs_require_manual_remediation(self, plan, problem):
        pair = pair_for(plan)
        path = Path(pair.evidence.routes[0].file.path.resolved_path)
        if problem == "missing":
            path.unlink()
        elif problem == "registry":
            Path(pair.evidence.registry.path.resolved_path).write_text("{}")
        else:
            path.write_text(
                "-- foreign\n" if problem == "foreign" else scoped_config.build_text(displays())
            )
        entry = editor.inspect_entry(*roots(plan))
        assert entry.mode == "blocked" and entry.pair is None
        assert entry.message and "manual" in entry.message and "appearance" in entry.message
        assert str(Path(pair.evidence.registry.path.lexical_path)) in entry.message
        if problem != "registry":
            assert str(path) in entry.message

    def test_latest_after_two_real_publications(self, plan):
        config, state = roots(plan)
        for border, monitor in (("7", "HDMI-A-8"), ("9", "HDMI-A-7")):
            pair = pair_for(plan)
            review = editor.prepare_review(
                pair, {Scope.APPEARANCE: appearance(border), Scope.DISPLAYS: displays(monitor)}
            )
            result = publication.publish_reviewed(review, config_root=config, state_root=state)
            assert result.outcome == "committed", result.error
        pair = pair_for(plan)
        assert pair.appearance == appearance("9")
        assert pair.displays == displays("HDMI-A-7")
        assert len(store.refuse_pending_readonly(state)) == 2

    @pytest.mark.parametrize("bad", [None, "corrupt", "pending"])
    def test_all_history_beyond_display_cap(self, plan, bad):
        config, state = roots(plan)
        # All terminal historical goals may disagree with the current pair.
        for _ in range(33):
            terminal(plan, Phase.ABORTED)
        ids = store.list_transaction_ids(state)
        last = ids[-1]
        path = state / "attune/transactions" / last / "intent.json"
        if bad == "corrupt":
            path.write_text("{}")
        elif bad == "pending":
            bundle = store.load_transaction(state, last)
            path.write_text(replace(bundle.intent, phase=Phase.PREPARED).to_json())
        entry = editor.inspect_entry(config, state)
        assert entry.mode == ("pair-ready" if bad is None else "blocked")

    def test_unsafe_store_permissions_restored(self, plan):
        config, state = roots(plan)
        path = state / "attune/transactions"
        mode = path.stat().st_mode
        try:
            path.chmod(0o755)
            assert editor.inspect_entry(config, state).mode == "blocked"
        finally:
            path.chmod(mode)

    def test_ids_changed_between_scans_blocks(self, plan, monkeypatch):
        original = store.refuse_pending_readonly
        calls = 0

        def changed(state):
            nonlocal calls
            calls += 1
            result = original(state)
            return result if calls == 1 else ("a" * 32,)

        monkeypatch.setattr(store, "refuse_pending_readonly", changed)
        entry = editor.inspect_entry(*roots(plan))
        assert entry.mode == "blocked" and entry.message and "IDs changed" in entry.message


class TestModels:
    def test_utf8_models_preserved_exactly(self, plan):
        model = scoped_config.ScopedConfig(
            Scope.DISPLAYS, {"monitors": ["monitor = desc:Caf\u00e9, preferred, auto, 1"]}
        )
        Path(plan.evidence.routes[1].file.path.resolved_path).write_text(
            scoped_config.build_text(model), encoding="utf-8"
        )
        pair = pair_for(plan)
        decoded = editor.CanonicalPairLayout.from_json(pair.to_json())
        assert decoded.displays == model
        assert decoded.displays.monitors == model.monitors
        review = editor.run_prepare_review(pair, {Scope.APPEARANCE: appearance("7")})
        assert review.scopes[1].previous_text == scoped_config.build_text(model)
        assert review.scopes[1].proposed_text == review.scopes[1].previous_text

    def test_pair_projection_frozen_and_exact(self, plan):
        pair = pair_for(plan)
        assert editor.CanonicalPairLayout.from_json(pair.to_json()) == pair
        with pytest.raises(FrozenInstanceError):
            setattr(pair, "appearance", appearance("7"))
        with pytest.raises(ValueError, match="differs"):
            replace(pair, appearance=appearance("7"))
        route = pair.evidence.routes[0]
        for wrong in (replace(route, counts=(0, 0, 0, 0)), replace(route, content_id="0" * 64)):
            with pytest.raises(ValueError):
                replace(
                    pair, evidence=replace(pair.evidence, routes=(wrong, pair.evidence.routes[1]))
                )

    @pytest.mark.parametrize("field", ["routes", "identity", "scope", "values", "value-pair"])
    def test_original_types_cannot_be_normalized(self, plan, field):
        pair = pair_for(plan)
        if field == "routes":
            object.__setattr__(pair.evidence, "routes", list(pair.evidence.routes))
        elif field == "identity":
            fact = pair.evidence.routes[0].file.path.facts[-1]
            object.__setattr__(fact, "identity", list(fact.identity))
        elif field == "scope":
            object.__setattr__(pair.appearance, "scope", "appearance")
        elif field == "values":
            object.__setattr__(pair.appearance, "values", list(pair.appearance.values))
        else:
            object.__setattr__(
                pair.appearance, "values", tuple(list(p) for p in pair.appearance.values)
            )
        with pytest.raises(ValueError):
            pair.to_json()

    @pytest.mark.parametrize(
        "change",
        [
            {"schema": True},
            {"schema": 2},
            {"extra": 1},
            {"mode": "ready"},
            {"mode": "blocked", "message": None},
            {"message": "unexpected"},
            {"state_root": "/different"},
            {"pair": None},
        ],
    )
    def test_strict_entry_codec(self, plan, change):
        data = json.loads(editor.inspect_entry(*roots(plan)).to_json())
        data.update(change)
        with pytest.raises(ValueError):
            editor.EditorEntry.from_json(json.dumps(data))

    @pytest.mark.parametrize(
        "text",
        [
            '{"schema":1,"schema":1}',
            "[" * 25 + "]" * 25,
            " " * (MAX_RECORD_BYTES + 1),
            '{"schema":NaN}',
        ],
    )
    def test_invalid_transport(self, text):
        for model in (editor.CanonicalPairLayout, editor.EditorEntry):
            with pytest.raises(ValueError):
                model.from_json(text)


class TestReview:
    @pytest.mark.parametrize("selected", [(), (Scope.APPEARANCE,), (Scope.DISPLAYS,), tuple(Scope)])
    def test_exact_goals_and_omitted_sibling_no_effects(self, plan, selected):
        pair = pair_for(plan)
        before = tree(Path(pair.evidence.config_root).parent)
        proposals = {
            s: appearance("7") if s is Scope.APPEARANCE else displays("HDMI-A-8") for s in selected
        }
        review = editor.prepare_review(pair, proposals)
        assert review.changed_scopes == selected
        for item in review.scopes:
            assert item.proposed_text == (
                scoped_config.build_text(proposals[item.scope])
                if item.scope in proposals
                else item.previous_text
            )
        assert tree(Path(pair.evidence.config_root).parent) == before

    @pytest.mark.parametrize("identical", [True, False])
    def test_external_replacement_never_adopted(self, plan, identical):
        pair = pair_for(plan)
        path = Path(pair.evidence.routes[0].file.path.resolved_path)
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(
            path.read_bytes() if identical else scoped_config.build_text(appearance("9")).encode()
        )
        replacement.chmod(0o644)
        replacement.replace(path)
        for prepare in (editor.prepare_review, editor.run_prepare_review):
            with pytest.raises(ValueError, match="changed"):
                prepare(pair, {Scope.APPEARANCE: appearance("7")})

    def test_pending_after_build_refused(self, plan, monkeypatch):
        pair = pair_for(plan)
        original = scoped_review.build_review

        def pending(evidence, proposals):
            result = original(evidence, proposals)
            monkeypatch.setattr(scoped_review, "build_review", original)
            store.prepare_transaction(plan, state_root=roots(plan)[1])
            return result

        monkeypatch.setattr(scoped_review, "build_review", pending)
        with pytest.raises(ValueError, match="Unresolved"):
            editor.prepare_review(pair, {})

    @pytest.mark.parametrize(
        "proposals", [{"appearance": appearance()}, {Scope.DISPLAYS: appearance()}, []]
    )
    def test_invalid_requests(self, plan, proposals):
        with pytest.raises(ValueError):
            editor.prepare_review(pair_for(plan), proposals)


class TestWorkers:
    def test_large_actual_review_request_not_argv(self, plan):
        pair = pair_for(plan)
        model = scoped_config.ScopedConfig(
            Scope.APPEARANCE,
            {
                "values": {"general:border_size": "7"},
                "beziers": [f"bezier = long_named_curve_{i}, 0, 0, 1, 1" for i in range(1700)],
                "animations": [],
            },
        )
        assert len(scoped_config.build_text(model).encode()) > 128 * 1024
        result = editor.run_prepare_review(pair, {Scope.APPEARANCE: model})
        assert result.scopes[0].proposed_text == scoped_config.build_text(model)

    @pytest.mark.parametrize(
        "input_text",
        [
            '{"schema":1,"schema":1}',
            '{"schema":true,"kind":"editor-review-request","pair":null,"proposals":{}}',
            '{"schema":1,"kind":"editor-review-request","pair":null,"proposals":{}}',
            "[" * 25 + "]" * 25,
        ],
    )
    def test_actual_review_worker_refuses_invalid_input(self, input_text):
        result = health.run_bounded(
            [sys.executable, "-I", "-B", "-m", "hyprmod.core.editor_layout", "review"],
            input_text=input_text,
            timeout=10,
            max_bytes=MAX_RECORD_BYTES,
            process_group=True,
        )
        assert result.returncode == 1
        assert not result.stdout and result.stderr
        assert len(result.stderr.encode()) <= 4097

    def test_no_parent_filesystem_reread(self, plan, monkeypatch):
        pair = pair_for(plan)

        def forbidden(*args, **kwargs):
            pytest.fail("Parent performed filesystem revalidation")

        monkeypatch.setattr(route_approval, "revalidate", forbidden)
        monkeypatch.setattr(route_approval, "inspect_installation", forbidden)
        monkeypatch.setattr(store, "refuse_pending_readonly", forbidden)
        assert editor.run_entry(*roots(plan)).mode == "pair-ready"
        assert editor.run_prepare_review(pair, {}).changed_scopes == ()

    def test_actual_worker_timeout_raises_not_blocked(self, plan):
        with pytest.raises(subprocess.TimeoutExpired):
            editor.run_entry(*roots(plan), timeout=0.000001)

    def test_actual_entry_and_review_stdin(self, plan):
        entry = editor.run_entry(*roots(plan))
        assert entry.mode == "pair-ready" and entry.pair is not None
        before = snapshot(entry.pair.evidence)
        result = editor.run_prepare_review(entry.pair, {Scope.APPEARANCE: appearance("7")})
        assert result.changed_scopes == (Scope.APPEARANCE,)
        assert result.scopes[1].proposed_text == result.scopes[1].previous_text
        assert snapshot(entry.pair.evidence) == before

    @pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), float("nan"), "30"])
    def test_invalid_timeout(self, plan, timeout):
        with pytest.raises(ValueError, match="timeout"):
            editor.run_entry(*roots(plan), timeout=timeout)
        with pytest.raises(ValueError, match="timeout"):
            editor.run_prepare_review(pair_for(plan), {}, timeout=timeout)

    def test_precancelled(self, plan):
        event = threading.Event()
        event.set()
        with pytest.raises(InterruptedError):
            editor.run_entry(*roots(plan), cancel_event=event)
        with pytest.raises(InterruptedError):
            editor.run_prepare_review(pair_for(plan), {}, cancel_event=event)

    def test_parent_rejects_different_roots(self, plan, monkeypatch):
        entry = editor.EditorEntry("/elsewhere", "/state", "legacy-clear", None, None)
        monkeypatch.setattr(
            health,
            "run_bounded",
            lambda *a, **k: subprocess.CompletedProcess([], 0, entry.to_json(), ""),
        )
        with pytest.raises(ValueError, match="different editor roots"):
            editor.run_entry(*roots(plan))

    @pytest.mark.parametrize("wrong", ["goal", "sibling", "baseline"])
    def test_parent_semantically_checks_complete_plan(self, plan, monkeypatch, wrong):
        pair = pair_for(plan)
        proposals = {Scope.APPEARANCE: appearance("8" if wrong == "goal" else "7")}
        if wrong == "sibling":
            proposals[Scope.DISPLAYS] = displays("HDMI-A-8")
        if wrong == "baseline":
            Path(pair.evidence.routes[0].file.path.resolved_path).write_text(
                scoped_config.build_text(appearance("9"))
            )
            current = route_approval.inspect_installation(
                Path(pair.evidence.registry.path.lexical_path),
                config_root=roots(plan)[0],
                state_root=roots(plan)[1],
            )
        else:
            current = pair.evidence
        wrong_plan = scoped_review.build_review(current, proposals)
        monkeypatch.setattr(
            health,
            "run_bounded",
            lambda *a, **k: subprocess.CompletedProcess([], 0, plan_to_json(wrong_plan), ""),
        )
        with pytest.raises(ValueError, match="different original pair|proposal goals"):
            editor.run_prepare_review(pair, {Scope.APPEARANCE: appearance("7")})
