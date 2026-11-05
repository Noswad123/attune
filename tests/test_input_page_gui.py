"""Opt-in real input rows with mocked picker data, compositor and publishers."""

import os

import pytest
from gi.repository import Adw, Gtk

from hyprmod.core import input as backend
from hyprmod.ui.keyboard_layouts_dialog import (
    KeyboardLayoutsDialog,
    LayoutPickerDialog,
    VariantPickerDialog,
)
from hyprmod.ui.options import KeyboardLayoutsOptionRow
from hyprmod.ui.options.numeric import SpinFloatOptionRow, SpinIntOptionRow
from hyprmod.ui.options.text import EntryOptionRow
from tests.test_input_page import drain_until, seed
from tests.test_input_page import no_input_writers as no_input_writers
from tests.test_input_page import page as page

pytestmark = pytest.mark.skipif(
    os.environ.get("ATTUNE_GUI_SMOKE") != "1" or os.environ.get("GDK_BACKEND") != "broadway",
    reason="opt-in isolated Broadway widgets",
)


@pytest.fixture
def built(page, monkeypatch):
    Adw.init()
    monkeypatch.setattr(
        "hyprmod.ui.options.keyboard.get_source_values",
        lambda _source: [
            {"layout": "us", "variant": "", "name": "English (US)", "id": "us", "label": "US"},
            {"layout": "no", "variant": "", "name": "Norwegian", "id": "no", "label": "NO"},
            {"layout": "de", "variant": "", "name": "German", "id": "de", "label": "DE"},
            {"layout": "de", "variant": "neo", "name": "Neo", "id": "de+neo", "label": "Neo"},
        ],
    )
    model, window, entries = page
    toolbar = model.build()
    yield model, window, entries, toolbar
    dialog = KeyboardLayoutsDialog.current()
    if dialog is not None:
        dialog.close()
    model.close()


class TestInputWidgets:
    def test_real_rows_domains_and_no_global_registration(self, built):
        model, window, entries, _toolbar = built
        assert set(model._rows) == backend.INPUT_KEYS
        assert len({id(row) for row in model._rows.values()}) == 14
        assert isinstance(model._rows["input:kb_layout"], KeyboardLayoutsOptionRow)
        assert model._rows["input:kb_layout"] is model._rows["input:kb_variant"]
        assert isinstance(model._rows["input:kb_options"], EntryOptionRow)
        for key in ("input:scroll_factor", "input:touchpad:scroll_factor"):
            row = model._rows[key]
            assert isinstance(row, SpinFloatOptionRow)
            adjustment = row._spin.get_adjustment()
            assert adjustment.get_lower() == 0.1 and adjustment.get_upper() == 2.0
            assert adjustment.get_step_increment() == 0.1
        for key in ("input:repeat_rate", "input:repeat_delay"):
            assert isinstance(model._rows[key], SpinIntOptionRow)
        for key, spec in backend.OPTION_SPECS.items():
            if spec.minimum is not None:
                row = model._rows[key]
                assert isinstance(row, (SpinFloatOptionRow, SpinIntOptionRow))
                adjustment = row._spin.get_adjustment()
                assert adjustment.get_lower() == spec.minimum
                assert adjustment.get_upper() == spec.maximum
        assert not model.is_dirty() and entries == []

    def test_async_baseline_silently_populates_existing_rows(self, built):
        model, window, entries, _toolbar = built
        values = dict(backend.DEFAULTS) | {
            "input:kb_layout": "no,us",
            "input:kb_variant": "unknown_variant,",
            "input:kb_options": "custom:unknown",
            "input:scroll_factor": 2.0,
            "input:touchpad:scroll_factor": 0.1,
        }
        expected = seed(model, values)
        model.baseline = None
        model._current = model._saved = backend.InputConfig()
        model._refresh()
        assert all(not row.row.get_sensitive() for row in model._rows.values())
        model.ensure_loaded()
        drain_until(lambda: not model._loading)
        assert model.get_config() == expected
        assert all(row.row.get_sensitive() for row in model._rows.values())
        assert model._rows["input:kb_layout"]._sources == [("no", "unknown_variant"), ("us", "")]
        assert not model.is_dirty() and entries == []
        window.hypr.get_live.assert_not_called()
        window.app_state.register.assert_not_called()
        assert window.hypr.mock_calls == []

    def test_initial_waiting_and_authoritative_owned_push_is_silent(self, built):
        model, _window, entries, _toolbar = built
        baseline = model.baseline
        model.baseline = None
        model._refresh()
        assert all(not row.row.get_sensitive() for row in model._rows.values())
        model.baseline = baseline
        seed(
            model,
            {
                "input:kb_layout": "no",
                "input:kb_variant": "",
                "input:kb_options": "unknown:raw,grp:alt_shift_toggle",
                "input:left_handed": False,
                "input:sensitivity": 0.0,
            },
        )
        model._refresh()
        assert all(row.row.get_sensitive() for row in model._rows.values())
        assert model._rows["input:kb_layout"]._sources == [("no", "")]
        row = model._rows["input:kb_options"].row
        assert isinstance(row, Adw.EntryRow)
        assert row.get_text() == "unknown:raw,grp:alt_shift_toggle"
        assert not model.is_dirty() and entries == []

    @pytest.mark.parametrize(
        "values",
        [
            {},
            {"input:kb_layout": "no"},
            {"input:kb_layout": "no", "input:kb_variant": ""},
            {"input:kb_layout": "no,us", "input:kb_variant": "unknown_variant,"},
        ],
    )
    def test_picker_pair_reset_discard_and_undo_redo(self, built, values):
        model, window, entries, _toolbar = built
        before = seed(model, values)
        model._refresh()
        row = model._rows["input:kb_layout"]
        assert isinstance(row, KeyboardLayoutsOptionRow)
        original_sources = list(row._sources)
        row._apply_sources([("us", ""), ("de", "neo")])
        assert len(entries) == 1
        changed = model.get_config()
        assert row._sources == [("us", ""), ("de", "neo")]
        entries[0].apply(window, undo=True)
        assert model.get_config() == before and row._sources == original_sources
        entries[0].apply(window, undo=False)
        assert model.get_config() == changed
        row._do_reset()
        assert len(entries) == 2
        assert model.get_config() == backend.InputConfig()
        row._do_discard()
        assert len(entries) == (3 if values else 2) and model.get_config() == before
        row._apply_sources([])
        assert model.get_config() == backend.InputConfig()
        assert window.hypr.mock_calls == []

    def test_real_dialog_picker_and_open_dialog_undo_lock(self, built):
        model, window, entries, toolbar = built
        before = seed(model, {"input:kb_layout": "no", "input:kb_variant": ""})
        model._started = True
        model._refresh()
        parent = Adw.Window()
        parent.set_content(toolbar)
        parent.present()
        row = model._rows["input:kb_layout"]
        assert isinstance(row, KeyboardLayoutsOptionRow)
        try:
            row.row.emit("activated")
            dialog = KeyboardLayoutsDialog.current()
            assert isinstance(dialog, KeyboardLayoutsDialog)
            dialog._on_add_clicked(None)
            layout_picker = LayoutPickerDialog.current()
            assert isinstance(layout_picker, LayoutPickerDialog)
            layout_picker._activate("de")
            variant_picker = VariantPickerDialog.current()
            assert isinstance(variant_picker, VariantPickerDialog)
            variant_picker._activate("neo")
            assert row._sources == [("no", ""), ("de", "neo")]
            assert len(entries) == 1
            entries[0].apply(window, undo=True)
            assert model.get_config() == before and dialog._sources == [("no", "")]
            entries[0].apply(window, undo=False)
            assert dialog._sources == [("no", ""), ("de", "neo")]
            window.editor_edit_allowed.return_value = False
            dialog._move(0, 1)
            assert dialog._sources == [("no", ""), ("de", "neo")]
            assert len(entries) == 1
            assert window.hypr.mock_calls == []
        finally:
            for kind in (VariantPickerDialog, LayoutPickerDialog, KeyboardLayoutsDialog):
                current = kind.current()
                if current is not None:
                    current.close()
            parent.destroy()

    def test_raw_unknown_options_survive_real_sensitivity_edit(self, built):
        model, _window, _entries, _toolbar = built
        seed(model, {"input:kb_options": "vendor:unknown,grp:alt_shift_toggle"})
        model._refresh()
        sensitivity = model._rows["input:sensitivity"]
        assert isinstance(sensitivity, SpinFloatOptionRow)
        sensitivity._spin.set_value(0.25)
        assert dict(model.get_config().values) == {
            "input:kb_options": "vendor:unknown,grp:alt_shift_toggle",
            "input:sensitivity": 0.25,
        }
        raw = model._rows["input:kb_options"].row
        assert isinstance(raw, Adw.EntryRow)
        raw.set_text("custom:preserved")
        raw.emit("apply")
        assert dict(model.get_config().values)["input:kb_options"] == "custom:preserved"

    @pytest.mark.parametrize("buffer", ["caps:escape", "invalid token"])
    def test_unapplied_options_survive_unrelated_edits_without_bypassing_apply(self, built, buffer):
        model, window, entries, _toolbar = built
        row = model._rows["input:kb_options"].row
        assert isinstance(row, Adw.EntryRow)
        row.set_text(buffer)
        assert (
            "Unapplied text (not in draft)" in model._origin_labels["input:kb_options"].get_label()
        )
        left_handed = model._rows["input:left_handed"].row
        assert isinstance(left_handed, Adw.SwitchRow)
        left_handed.set_active(True)
        assert row.get_text() == buffer
        model.set_keyboard_sources("no", "")
        assert row.get_text() == buffer
        model.remove_override("input:left_handed")
        assert row.get_text() == buffer
        model.discard_option("input:kb_layout")
        assert row.get_text() == buffer
        assert "input:kb_options" not in dict(model.get_config().values)
        count = len(entries)
        row.emit("apply")
        if buffer == "caps:escape":
            assert dict(model.get_config().values)["input:kb_options"] == buffer
            assert len(entries) == count + 1
            assert model._origin_labels["input:kb_options"].get_label() == "Draft override"
        else:
            assert "input:kb_options" not in dict(model.get_config().values)
            assert len(entries) == count
            window.show_toast.assert_called_once()
            assert row.get_text() == ""
        assert window.hypr.mock_calls == []

    @pytest.mark.parametrize("action", ["discard-option", "discard-all", "undo", "baseline"])
    def test_authoritative_operations_replace_unapplied_options(self, built, action):
        model, window, entries, _toolbar = built
        seed(model, {"input:kb_options": "custom:saved"})
        model._refresh()
        model.set_value("input:left_handed", True)
        row = model._rows["input:kb_options"].row
        assert isinstance(row, Adw.EntryRow)
        row.set_text("caps:escape")
        if action == "discard-option":
            model.discard_option("input:kb_options")
        elif action == "discard-all":
            model.discard()
        elif action == "undo":
            entries[-1].apply(window, undo=True)
        else:
            # A post-verified baseline replacement is authoritative, not an ordinary edit.
            model.discard()
            row.set_text("caps:escape")
            model.adopt_saved(model.baseline)
        assert row.get_text() == "custom:saved"
        assert model._origin_labels["input:kb_options"].get_label() == "Saved override"
        assert window.hypr.mock_calls == []

    def test_per_row_origins_distinguish_mixed_observation_and_ownership(self, built):
        model, window, entries, _toolbar = built
        saved = {"input:kb_layout": "no", "input:left_handed": False, "input:sensitivity": 0.0}
        seed(model, saved)
        runtime = {
            "input:kb_layout": "us",
            "input:kb_variant": "",
            "input:kb_options": "",
            "input:natural_scroll": False,
            "input:repeat_rate": 0,
            "input:touchpad:natural_scroll": None,
        }
        window.hypr.online = True
        window.hypr.get_live.side_effect = lambda key, default: (
            runtime.get(key, default),
            key in runtime,
        )
        model.ensure_loaded()
        drain_until(lambda: not model._loading)
        assert not model.is_dirty() and entries == []
        assert "input:touchpad:natural_scroll" not in model._hints
        for key, label in model._origin_labels.items():
            expected = (
                "Layout: Saved override\nVariant: Current runtime snapshot"
                if key == "input:kb_layout"
                else "Saved override"
                if key in saved
                else "Current runtime snapshot"
                if key in model._hints
                else "Default, not observed"
            )
            assert label.get_label() == expected
            assert label.get_visible()
            assert expected in (model._rows[key].row.get_tooltip_text() or "")
        assert model._rows["input:natural_scroll"].row.get_property("active") is False
        assert model._rows["input:touchpad:natural_scroll"].row.get_property("active") is False
        model.set_value("input:left_handed", True)
        assert model._origin_labels["input:left_handed"].get_label() == "Draft override"
        entries[-1].apply(window, undo=True)
        assert model._origin_labels["input:left_handed"].get_label() == "Saved override"
        model.remove_override("input:left_handed")
        assert model._origin_labels["input:left_handed"].get_label() == "Default, not observed"
        model.discard_option("input:left_handed")
        assert model._origin_labels["input:left_handed"].get_label() == "Saved override"
        model.set_keyboard_sources("no", "")
        assert model._origin_labels["input:kb_layout"].get_label() == (
            "Layout: Saved override\nVariant: Draft override"
        )
        model.set_keyboard_sources("de", "neo")
        assert model._origin_labels["input:kb_layout"].get_label() == (
            "Layout: Draft override\nVariant: Draft override"
        )
        model.remove_override("input:kb_layout")
        assert model._origin_labels["input:kb_layout"].get_label() == (
            "Layout: Current runtime snapshot\nVariant: Current runtime snapshot"
        )
        assert {call[0] for call in window.hypr.mock_calls} == {"get_live"}

    def test_picker_callback_after_edit_lock_restores_presentation(self, built):
        model, window, entries, _toolbar = built
        seed(model, {"input:kb_layout": "no", "input:kb_variant": ""})
        model._refresh()
        row = model._rows["input:kb_layout"]
        assert isinstance(row, KeyboardLayoutsOptionRow)
        window.editor_edit_allowed.return_value = False
        row._apply_sources([("de", "neo")])
        assert row._sources == [("no", "")]
        assert not model.is_dirty() and entries == []
        row._do_reset()
        row._do_discard()
        assert not model.is_dirty() and entries == []
        assert window.hypr.mock_calls == []

    def test_guidance_and_group_titles(self, built):
        model, _window, _entries, toolbar = built

        def widgets(parent):
            yield parent
            child = parent.get_first_child()
            while child is not None:
                yield from widgets(child)
                child = child.get_next_sibling()

        labels = [w.get_text() for w in widgets(toolbar) if isinstance(w, Gtk.Label)]
        text = " ".join(labels)
        assert "Draft only" in text and "No input preview or reload" in text
        assert "attune-input.lua" in text and "manually" in text
        assert {label for label, _options in model._sections} == {"Keyboard", "Mouse", "Touchpad"}
