"""Input draft operations never publish, apply or register global options."""

import os
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from gi.repository import GLib

from hyprmod.core import input as backend
from hyprmod.core.input import InputConfig
from hyprmod.core.undo import SavedListSnapshot
from hyprmod.pages.input import InputPage


@pytest.fixture(autouse=True)
def no_input_writers(monkeypatch):
    monkeypatch.setattr(
        backend, "persist_reviewed", Mock(side_effect=AssertionError("No input publishing"))
    )


@pytest.fixture
def page():
    config_root = Path(os.environ["XDG_CONFIG_HOME"])
    (config_root / "hypr").mkdir()
    window = Mock()
    window.editor_edit_allowed.return_value = True
    window.hypr.online = False
    entries = []
    model = InputPage(window, on_dirty_changed=Mock(), push_undo=entries.append)
    model.baseline = backend.observe(config_root, model._state_root)
    window._input_page = model
    return model, window, entries


def seed(model, values):
    config = InputConfig.from_mapping(values)
    if model.baseline is None:
        raise ValueError("Expected loaded fixture")
    Path(model.baseline.lexical_path).write_text(backend.build_text(config))
    model.baseline = backend.observe(model._config_root, model._state_root)
    model._current = model._saved = model.baseline.config
    return config


def drain_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        GLib.MainContext.default().iteration(False)
        time.sleep(0.005)
    assert predicate()


class TestInputDraft:
    def test_lazy_constructor_and_search_allowlist(self):
        window = Mock()
        model = InputPage(window)
        assert model.baseline is None and model.load_error is None
        assert not model.is_dirty() and not model.locked
        assert model.get_config() == InputConfig()
        assert {entry["key"] for entry in model.get_search_entries()} == backend.INPUT_KEYS
        assert all(entry["_group_id"] == "input" for entry in model.get_search_entries())
        assert window.mock_calls == []

    def test_preserves_raw_owned_values_after_unrelated_edit(self, page):
        model, window, entries = page
        before = seed(
            model,
            {
                "input:kb_layout": "no,us",
                "input:kb_variant": "unknown_variant,",
                "input:kb_options": "custom:unknown,grp:alt_shift_toggle",
                "input:sensitivity": 0.0,
                "input:left_handed": False,
            },
        )
        model._hints = {"input:kb_layout": "de", "input:sensitivity": 0.9}
        assert model._state.get("input:kb_layout").live_value == "no,us"
        assert model._state.get("input:sensitivity").live_value == 0.0
        model.set_value("input:sensitivity", 0.25)
        expected = dict(before.values) | {"input:sensitivity": 0.25}
        assert dict(model.get_config().values) == expected
        assert len(entries) == 1 and isinstance(entries[0], SavedListSnapshot)
        assert entries[0].page_attr == "_input_page"
        entries[0].apply(window, undo=True)
        assert model.get_config() == before and not model.is_dirty()
        entries[0].apply(window, undo=False)
        assert dict(model.get_config().values) == expected
        model.discard()
        assert model.get_config() == before and not model.is_dirty()
        assert window.hypr.mock_calls == []
        window.app_state.assert_not_called()

    @pytest.mark.parametrize(
        "values",
        [
            {},
            {"input:kb_layout": "no"},
            {"input:kb_layout": "no", "input:kb_variant": ""},
            {"input:kb_layout": "no,us", "input:kb_variant": "nodeadkeys,"},
        ],
    )
    def test_sources_reset_discard_are_atomic_and_idempotent(self, page, values):
        model, window, entries = page
        before = seed(model, values)
        model.set_keyboard_sources("us,de", ",neo")
        changed = model.get_config()
        assert len(entries) == 1
        entries[0].apply(window, undo=True)
        assert model.get_config() == before
        entries[0].apply(window, undo=False)
        assert model.get_config() == changed
        model.remove_override("input:kb_variant")
        count = len(entries)
        model.remove_override("input:kb_layout")
        assert len(entries) == count
        assert not (dict(model.get_config().values).keys() & set(values))
        model.discard_option("input:kb_variant")
        count = len(entries)
        model.discard_option("input:kb_layout")
        assert len(entries) == count
        assert model.get_config() == before
        model.set_keyboard_sources("no", "")
        assert dict(model.get_config().values)["input:kb_variant"] == ""
        model.set_keyboard_sources("", "")
        assert model.get_config() == InputConfig()

    def test_hints_do_not_own_values_and_reset_restores_hint(self, page):
        model, _window, _entries = page
        model._hints = {"input:sensitivity": 0.3, "input:kb_layout": "no"}
        assert model._state.get("input:sensitivity").live_value == 0.3
        assert not model._state.get("input:sensitivity").managed
        model.set_value("input:sensitivity", 0.0)
        assert dict(model.get_config().values) == {"input:sensitivity": 0.0}
        model.remove_override("input:sensitivity")
        assert model._state.get("input:sensitivity").live_value == 0.3
        assert not model.is_dirty()

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("input:left_handed", False),
            ("input:repeat_rate", 0),
            ("input:sensitivity", 0.0),
            ("input:kb_options", ""),
        ],
    )
    def test_value_origin_uses_membership_not_truthiness(self, page, key, value):
        model, _window, _entries = page
        assert model._value_origin(key) == "Default, not observed"
        model._hints[key] = value
        assert model._value_origin(key) == "Current runtime snapshot"
        model.set_value(key, value)
        assert model._value_origin(key) == "Draft override"
        model.remove_override(key)
        assert model._value_origin(key) == "Current runtime snapshot"
        seed(model, {key: value})
        assert model._value_origin(key) == "Saved override"

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("input:scroll_factor", 2.1),
            ("input:scroll_factor", 0.0),
            ("input:touchpad:scroll_factor", 10.0),
            ("input:sensitivity", float("nan")),
            ("input:sensitivity", float("inf")),
            ("input:repeat_rate", True),
            ("input:repeat_rate", 25.0),
            ("input:left_handed", "no"),
            ("input:follow_mouse", 1),
            ("input:touchpad:tap_to_click", False),
        ],
    )
    def test_invalid_typed_values_are_atomic(self, page, key, value):
        model, _window, entries = page
        with pytest.raises(ValueError):
            model.set_value(key, value)
        assert not model.is_dirty() and entries == []

    def test_pending_and_baseline_equivalence(self, page):
        model, window, entries = page
        seed(model, {"input:left_handed": False})
        model.remove_override("input:left_handed")
        model.set_value("input:sensitivity", 0.0)
        pending = list(model.iter_pending_changes())
        assert len(pending) == model.pending_change_count() == 2
        assert {p.kind for p in pending} == {"added", "removed"}
        assert all(p.category == "Input" and p.navigate_to == "input" for p in pending)
        with pytest.raises(ValueError, match="baseline"):
            model.restore_snapshot([], [])
        with pytest.raises(ValueError, match="verified"):
            model.mark_saved()
        entry = entries[-1]
        seed(model, {"input:left_handed": True})
        with pytest.raises(ValueError, match="baseline"):
            entry.apply(window, undo=True)

    def test_adopt_only_exact_owned_route_and_config(self, page, tmp_path):
        model, window, _entries = page
        model.set_value("input:sensitivity", 0.25)
        before = model.baseline
        with pytest.raises(ValueError):
            model.adopt_saved(before)
        other_root = tmp_path / "other"
        (other_root / "hypr").mkdir(parents=True)
        (other_root / "hypr" / backend.BASENAME).write_text(backend.build_text(model.get_config()))
        with pytest.raises(ValueError):
            model.adopt_saved(backend.observe(other_root, model._state_root))
        Path(before.lexical_path).write_text(backend.build_text(model.get_config()))
        verified = backend.observe(model._config_root, model._state_root)
        model.adopt_saved(verified)
        assert model.baseline == verified and not model.is_dirty()
        window.app_state.mark_saved.assert_not_called()

    def test_lock_retains_draft_and_blocks_callbacks_and_undo(self, page):
        model, window, entries = page
        model.set_keyboard_sources("no", "")
        draft = model.get_config()
        window.editor_edit_allowed.return_value = False
        model._on_sources([("input:kb_layout", "de"), ("input:kb_variant", "")])
        model._on_change("input:left_handed", True)
        model._on_reset("input:kb_layout", "us")
        model._on_discard("input:kb_layout")
        assert model.get_config() == draft and len(entries) == 1
        model.invalidate("Input publication uncertain")
        window.editor_edit_allowed.return_value = True
        with pytest.raises(ValueError):
            entries[0].apply(window, undo=True)
        assert model.get_config() == draft and model.is_dirty()
        assert model.locked and model.load_error == "Input publication uncertain"
        window.app_state.mark_saved.assert_not_called()


class TestInputLoading:
    def test_offline_load_is_readonly_and_single_slot(self, page, monkeypatch):
        model, window, entries = page
        model.baseline = None
        observer = Mock(wraps=backend.run_observe)
        monkeypatch.setattr(backend, "run_observe", observer)
        model.ensure_loaded()
        model.ensure_loaded()
        drain_until(lambda: not model._loading)
        assert model.baseline is not None, model.load_error
        assert observer.call_count == 1
        assert not model.is_dirty() and entries == []
        assert "defaults" in model._hint_status
        window.hypr.get_live.assert_not_called()
        assert not Path(model.baseline.lexical_path).exists()
        assert not model._state_root.exists()

    def test_runtime_reads_off_main_thread_preserve_owned(self, page):
        model, window, _entries = page
        seed(model, {"input:left_handed": False, "input:sensitivity": 0.0})
        window.hypr.online = True
        main = threading.get_ident()

        def get_live(key, default):
            assert threading.get_ident() != main
            if key == "input:kb_options":
                raise OSError("No runtime")
            return (True if key == "input:left_handed" else default), True

        window.hypr.get_live.side_effect = get_live
        model.ensure_loaded()
        drain_until(lambda: not model._loading)
        assert window.hypr.get_live.call_count == 15
        assert model._state.get("input:left_handed").live_value is False
        assert dict(model.get_config().values)["input:sensitivity"] == 0.0
        assert not model.is_dirty() and "incomplete" in model._hint_status
        assert {call[0] for call in window.hypr.mock_calls} <= {"get_live"}

    @pytest.mark.parametrize("failure", ["foreign", "missing-parent", "wrong-context"])
    def test_load_error_locks_only_input(self, page, monkeypatch, failure, tmp_path):
        model, window, entries = page
        if failure == "foreign":
            Path(model.baseline.lexical_path).write_text("-- foreign input\n")
        elif failure == "missing-parent":
            (model._config_root / "hypr").rmdir()
        else:
            root = tmp_path / "other"
            (root / "hypr").mkdir(parents=True)
            wrong = backend.observe(root, model._state_root)
            monkeypatch.setattr(backend, "run_observe", Mock(return_value=wrong))
        model.baseline = None
        model.ensure_loaded()
        drain_until(lambda: not model._loading)
        assert model.locked and model.load_error
        assert not model.is_dirty() and entries == []
        window.app_state.mark_saved.assert_not_called()
        window._lock_legacy_editor.assert_not_called()

    @pytest.mark.parametrize("action", ["close", "invalidate"])
    def test_late_completion_does_not_replace_draft(self, page, monkeypatch, action):
        model, _window, _entries = page
        model.set_value("input:left_handed", True)
        draft, baseline = model.get_config(), model.baseline
        entered, release = threading.Event(), threading.Event()

        def observe(*_args, **_kwargs):
            entered.set()
            release.wait(5)
            return baseline

        monkeypatch.setattr(backend, "run_observe", observe)
        model.ensure_loaded()
        assert entered.wait(2)
        try:
            if action == "close":
                model.close()
            else:
                model.invalidate("Uncertain input")
        finally:
            release.set()
        drain_until(lambda: not model._loading)
        assert model.get_config() == draft and model.is_dirty()
