"""Cursor widgets share Input ownership without preview or publication."""

import locale
import os
import threading
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
from gi.repository import Adw, Gio, Gtk

from hyprmod.core import input as backend
from hyprmod.core.input import persist_reviewed
from hyprmod.ui.options.numeric import PreciseFloatOptionRow, SpinFloatOptionRow
from tests.test_input_page import drain_until, seed
from tests.test_input_page import no_input_writers as no_input_writers
from tests.test_input_page import page as page

pytestmark = pytest.mark.skipif(
    os.environ.get("ATTUNE_GUI_SMOKE") != "1" or os.environ.get("GDK_BACKEND") != "broadway",
    reason="opt-in isolated Broadway widgets",
)


def widgets(parent):
    yield parent
    child = parent.get_first_child()
    while child is not None:
        yield from widgets(child)
        child = child.get_next_sibling()


@pytest.fixture
def built(page, monkeypatch):
    Adw.init()
    monkeypatch.setattr("hyprmod.ui.options.keyboard.get_source_values", lambda _source: [])
    monkeypatch.setattr(Gio.Settings, "new", Mock(side_effect=AssertionError("No GSettings")))
    model, window, entries = page
    input_view = model.build()
    cursor_view = model.build_cursor()
    yield model, window, entries, input_view, cursor_view
    model.close()


class TestCursorWidgets:
    def test_separate_views_one_empty_owner_and_closed_rows(self, built):
        model, window, entries, input_view, cursor_view = built
        assert input_view is not cursor_view
        assert set(model._rows) == backend.INPUT_KEYS
        assert len(model._rows) == 23
        assert len({id(row) for row in model._rows.values()}) == 22
        assert len({id(row) for key, row in model._rows.items() if key.startswith("input:")}) == 14
        assert {key for key in model._rows if key.startswith("cursor:")} == backend.CURSOR_KEYS
        assert {
            key for key, option in model._options.items() if option.get("preserve_precision")
        } == {
            "cursor:zoom_factor",
            "cursor:inactive_timeout",
        }
        for key, lower, upper in (
            ("cursor:zoom_factor", 1.0, 10.0),
            ("cursor:inactive_timeout", 0.0, 20.0),
        ):
            row = model._rows[key]
            assert isinstance(row, PreciseFloatOptionRow)
            assert (row.option["min"], row.option["max"]) == (lower, upper)
            assert row.option["step"] == 0.1
        assert model.get_config() == backend.InputConfig() and entries == []
        assert not Path(model.baseline.lexical_path).exists()
        assert window.hypr.mock_calls == []
        window.app_state.register.assert_not_called()

    @pytest.mark.parametrize("first", ["input", "cursor"])
    def test_either_view_maps_to_single_loading_slot_and_status(self, page, monkeypatch, first):
        Adw.init()
        monkeypatch.setattr("hyprmod.ui.options.keyboard.get_source_values", lambda _source: [])
        model, window, entries = page
        builders = {"input": model.build, "cursor": model.build_cursor}
        views = [builders[first](), builders["cursor" if first == "input" else "input"]()]
        observer = Mock(wraps=backend.run_observe)
        monkeypatch.setattr(backend, "run_observe", observer)
        model.baseline = None
        parents = []
        for view in views:
            parent = Adw.Window()
            parent.set_content(view)
            parent.present()
            parents.append(parent)
        assert model._status.get_title() == model._cursor_status.get_title() == "Loading input..."
        drain_until(lambda: not model._loading)
        assert observer.call_count == 1
        assert model._status.get_title() == model._cursor_status.get_title() == "Input draft"
        assert model._status.get_subtitle() == model._cursor_status.get_subtitle()
        model.invalidate("Shared input uncertainty")
        assert model._status.get_title() == model._cursor_status.get_title() == "Input locked"
        assert all(not row.row.get_sensitive() for row in model._rows.values())
        assert entries == [] and window.hypr.mock_calls == []
        model.close()
        for parent in parents:
            parent.destroy()

    def test_runtime_false_numbers_none_and_owned_precedence(self, built):
        model, window, entries, *_views = built
        seed(model, {"cursor:no_warps": False, "cursor:zoom_factor": 1.0})
        runtime = {
            "cursor:no_warps": True,
            "cursor:zoom_factor": 2.0,
            "cursor:hide_on_touch": False,
            "cursor:inactive_timeout": 0.0,
            "cursor:hide_on_tablet": None,
        }
        window.hypr.online = True
        main = threading.get_ident()

        def get_live(key, default):
            assert threading.get_ident() != main
            return runtime.get(key, default), key in runtime

        window.hypr.get_live.side_effect = get_live
        model.ensure_loaded()
        drain_until(lambda: not model._loading)
        assert model._state.get("cursor:no_warps").live_value is False
        assert model._state.get("cursor:zoom_factor").live_value == 1.0
        assert model._state.get("cursor:hide_on_touch").live_value is False
        assert "cursor:hide_on_tablet" not in model._hints
        assert model._origin_labels["cursor:no_warps"].get_label() == "Saved override"
        assert (
            model._origin_labels["cursor:hide_on_touch"].get_label() == "Current runtime snapshot"
        )
        assert (
            model._origin_labels["cursor:inactive_timeout"].get_label()
            == "Current runtime snapshot"
        )
        assert model._origin_labels["cursor:hide_on_tablet"].get_label() == "Default, not observed"
        assert not model.is_dirty() and entries == []
        assert {call[0] for call in window.hypr.mock_calls} == {"get_live"}

    def test_cross_view_edits_and_undo_redo_preserve_unapplied_buffer(self, built):
        model, window, entries, *_views = built
        raw = model._rows["input:kb_options"].row
        assert isinstance(raw, Adw.EntryRow)
        raw.set_text("caps:escape")
        model.set_keyboard_sources("no", "")
        model._rows["cursor:no_warps"].row.set_property("active", True)
        zoom = model._rows["cursor:zoom_factor"]
        assert isinstance(zoom, PreciseFloatOptionRow)
        zoom.row.set_text(locale.localize("1.5"))
        zoom.row.emit("apply")
        assert raw.get_text() == "caps:escape"
        assert "input:kb_options" not in dict(model.get_config().values)
        assert all(entry.page_attr == "_input_page" for entry in entries)
        assert [change.navigate_to for change in model.iter_pending_changes()].count("cursor") == 2
        assert {change.category for change in model.iter_pending_changes()} == {"Input", "Cursor"}
        assert model.pending_change_count() == 4
        entries[-1].apply(window, undo=True)
        assert raw.get_text() == "caps:escape"
        assert (
            "Unapplied text (not in draft)" in model._origin_labels["input:kb_options"].get_label()
        )
        assert "cursor:zoom_factor" not in dict(model.get_config().values)
        entries[-1].apply(window, undo=False)
        assert raw.get_text() == "caps:escape"
        assert (
            "Unapplied text (not in draft)" in model._origin_labels["input:kb_options"].get_label()
        )
        assert dict(model.get_config().values)["cursor:zoom_factor"] == 1.5
        model.discard()
        assert raw.get_text() == ""
        assert model.get_config() == backend.InputConfig()
        assert window.hypr.mock_calls == []

    @pytest.mark.parametrize("key", ["cursor:zoom_factor", "input:kb_layout"])
    def test_unrelated_snapshot_undo_redo_preserves_buffer(self, built, key):
        model, window, entries, *_views = built
        model.set_value(key, 2.35 if key.startswith("cursor:") else "no")
        raw = model._rows["input:kb_options"].row
        assert isinstance(raw, Adw.EntryRow)
        raw.set_text("caps:escape")
        for undo in (True, False):
            entries[-1].apply(window, undo=undo)
            assert raw.get_text() == "caps:escape"
            assert "input:kb_options" not in dict(model.get_config().values)
            assert (
                "Unapplied text (not in draft)"
                in model._origin_labels["input:kb_options"].get_label()
            )

    @pytest.mark.parametrize(
        ("key", "value", "owned"),
        [
            ("cursor:zoom_factor", 2.35, True),
            ("cursor:inactive_timeout", 0.25, True),
            ("cursor:zoom_factor", 1.00000000001, True),
            ("cursor:zoom_factor", 1.2345678901234567, False),
            ("cursor:inactive_timeout", 1e-20, False),
        ],
    )
    def test_precise_float_display_and_noop_update(self, built, key, value, owned):
        model, window, entries, *_views = built
        if owned:
            seed(model, {key: value})
        else:
            # These are admitted drafts; the library's separate emission proof rejects saving.
            model.set_value(key, value)
            entries.clear()
        model._refresh()
        row = model._rows[key]
        assert isinstance(row, PreciseFloatOptionRow)
        assert locale.atof(row.row.get_text()) == value
        row.row.set_text("0")
        row.set_value_silent(value)
        assert locale.atof(row.row.get_text()) == value
        draft = model.get_config()
        dirty = model.is_dirty()
        model._on_dirty_changed.reset_mock()
        row.row.emit("apply")
        assert model.get_config() == draft and model.is_dirty() == dirty
        assert locale.atof(row.row.get_text()) == value
        assert entries == []
        model._on_dirty_changed.assert_not_called()
        assert window.hypr.mock_calls == []

    @pytest.mark.parametrize("value", [2.35, 0.25, 1.2345678901234567, 1e-20])
    def test_precision_row_initial_output_and_unchanged_commit(self, value):
        Adw.init()
        changed = Mock()
        row = PreciseFloatOptionRow(
            {
                "key": "cursor:inactive_timeout",
                "default": 0.0,
                "min": 0.0,
                "max": 20.0,
                "step": 0.1,
                "preserve_precision": True,
            },
            value,
            changed,
            Mock(),
        )
        assert locale.atof(row.row.get_text()) == value
        row.row.emit("apply")
        assert locale.atof(row.row.get_text()) == value
        changed.assert_not_called()

    def test_existing_float_row_still_rounds_to_step_digits(self):
        Adw.init()
        changed = Mock()
        row = SpinFloatOptionRow(
            {"key": "input:scroll_factor", "min": 0.1, "max": 2.0, "step": 0.1},
            1.0,
            changed,
            Mock(),
        )
        row._spin.set_value(1.25)
        changed.assert_called_once_with("input:scroll_factor", 1.2)

    def test_precise_text_edit_and_step_policy(self, built):
        model, window, entries, *_views = built
        seed(model, {"cursor:zoom_factor": 2.35})
        model._refresh()
        row = model._rows["cursor:zoom_factor"]
        assert isinstance(row, PreciseFloatOptionRow)
        row.row.set_text(locale.localize("2.45"))
        row.row.emit("apply")
        assert dict(model.get_config().values)["cursor:zoom_factor"] == 2.45
        assert locale.atof(row.row.get_text()) == 2.45
        assert len(entries) == 1
        button = next(
            w
            for w in widgets(row.row)
            if isinstance(w, Gtk.Button) and w.get_icon_name() == "list-add-symbolic"
        )
        button.emit("clicked")
        assert dict(model.get_config().values)["cursor:zoom_factor"] == 2.55
        assert row.option["step"] == 0.1
        assert window.hypr.mock_calls == []

    @pytest.mark.parametrize(
        ("key", "initial"),
        [
            ("cursor:zoom_factor", None),
            ("cursor:inactive_timeout", None),
            ("cursor:zoom_factor", 2.35),
            ("cursor:inactive_timeout", 0.25),
        ],
    )
    @pytest.mark.parametrize("increments", [2, 3, 10])
    def test_arrow_steps_review_and_really_save_temporary_output(
        self, built, key, initial, increments
    ):
        model, window, entries, *_views = built
        model._state_root.mkdir(parents=True)
        model.baseline = backend.observe(model._config_root, model._state_root)
        if initial is not None:
            seed(model, {key: initial})
            model._refresh()
        row = model._rows[key]
        assert isinstance(row, PreciseFloatOptionRow)
        start = backend.DEFAULTS[key] if initial is None else initial
        button = next(
            w
            for w in widgets(row.row)
            if isinstance(w, Gtk.Button) and w.get_icon_name() == "list-add-symbolic"
        )
        for _ in range(increments):
            button.emit("clicked")
        expected = float(Decimal(str(start)) + increments * Decimal("0.1"))
        assert dict(model.get_config().values)[key] == expected
        review = backend.prepare_review(model.baseline, model.get_config())
        result = persist_reviewed(review, model.get_config())
        assert result.outcome == "saved", result.error
        model.adopt_saved(result.baseline)
        assert not model.is_dirty()
        assert (
            backend.read_text(Path(model.baseline.lexical_path).read_text()) == model.get_config()
        )
        assert window.hypr.mock_calls == []

    def test_typed_commit_below_gtk_epsilon_reviews_and_saves(self, built):
        model, window, entries, *_views = built
        model._state_root.mkdir(parents=True)
        model.baseline = backend.observe(model._config_root, model._state_root)
        row = model._rows["cursor:zoom_factor"]
        assert isinstance(row, PreciseFloatOptionRow)
        row.row.set_text(locale.localize("1.00000000001"))
        row.row.emit("apply")
        assert dict(model.get_config().values)["cursor:zoom_factor"] == 1.00000000001
        assert locale.atof(row.row.get_text()) == 1.00000000001
        assert len(entries) == 1
        review = backend.prepare_review(model.baseline, model.get_config())
        result = persist_reviewed(review, model.get_config())
        assert result.outcome == "saved", result.error
        model.adopt_saved(result.baseline)
        assert not model.is_dirty()
        assert window.hypr.mock_calls == []

    @pytest.mark.parametrize("text", ["nan", "inf", "-inf", "0.9", "10.1", "bad"])
    def test_invalid_typed_float_is_refused_without_clamping(self, built, text):
        model, window, entries, *_views = built
        row = model._rows["cursor:zoom_factor"]
        assert isinstance(row, PreciseFloatOptionRow)
        before = model.get_config()
        row.row.set_text(locale.localize(text))
        row.row.emit("apply")
        assert model.get_config() == before and entries == []
        assert row.row.get_text() == locale.localize(text)
        assert row.row.has_css_class("option-error")
        assert "Not applied" in (row.row.get_tooltip_text() or "")
        assert window.hypr.mock_calls == []

    def test_cursor_only_view_search_and_pending_revert(self, page):
        Adw.init()
        model, window, entries = page
        model.build_cursor()
        assert set(model._rows) == backend.CURSOR_KEYS
        model.set_value("cursor:warp_on_change_workspace", 2)
        model.set_value("cursor:inactive_timeout", 0.15)
        changes = list(model.iter_pending_changes())
        assert all(
            change.category == "Cursor" and change.navigate_to == "cursor" for change in changes
        )
        assert {
            entry["key"] for entry in model.get_search_entries() if entry["_group_id"] == "cursor"
        } == backend.CURSOR_KEYS
        for change in changes:
            change.revert()
        assert not model.is_dirty() and len(entries) == 4
        assert window.hypr.mock_calls == []
        model.close()
