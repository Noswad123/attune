"""Opt-in isolated binding widgets; no compositor access or binding writers."""

import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock, call

import pytest
from gi.repository import Adw, Gdk, GLib, Gtk
from hyprland_socket import MOD_BITS, Bind

from hyprmod.binds import DISPATCHER_CATEGORIES
from hyprmod.binds.dialog import BindEditDialog
from hyprmod.core import bindings, source_bindings
from hyprmod.core.ownership import SavedList
from hyprmod.pages.managed_bindings import ManagedBindingsPage
from tests.test_keybindings_workflow_gui import open_bindings
from tests.test_keybindings_workflow_gui import window as window
from tests.test_scoped_review import evidence as evidence
from tests.test_transaction_store import plan as plan

pytestmark = pytest.mark.skipif(
    os.environ.get("ATTUNE_GUI_SMOKE") != "1",
    reason="Requires opt-in isolated GTK display",
)


@pytest.fixture
def widgets(monkeypatch):
    monkeypatch.setattr(
        source_bindings,
        "persist_reviewed",
        Mock(side_effect=AssertionError("Explicit temporary source publisher required")),
    )
    Adw.init()
    config = Path(os.environ["XDG_CONFIG_HOME"])
    (config / "hypr").mkdir()
    baseline = bindings.observe(config, Path(os.environ["XDG_STATE_HOME"]))
    observer = Mock(return_value=baseline)
    monkeypatch.setattr(bindings, "run_observe", observer)
    for name in ("persist_reviewed", "prepare_review", "run_prepare_review"):
        monkeypatch.setattr(bindings, name, Mock(side_effect=AssertionError("No binding writers")))
    window: Any = Adw.Window()
    window.hypr = Mock()
    window.hypr.online = True
    raw = Bind(
        MOD_BITS["SUPER"],
        "q",
        "__lua",
        "42",
        repeat=True,
        release=True,
        submap="resize",
        description="Foreign callback",
    )
    window.hypr.get_binds.return_value = [raw]
    window.editor_edit_allowed = Mock(return_value=True)
    window.show_toast = Mock()
    model = ManagedBindingsPage(window)
    model.bind_lifecycle(window)
    toolbar = model.build()
    window.set_content(toolbar)
    yield model, window, observer
    model.close()
    window.destroy()


def drain(model):
    deadline = time.monotonic() + 5
    while model._loading and time.monotonic() < deadline:
        GLib.MainContext.default().iteration(False)
        time.sleep(0.005)
    assert not model._loading


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


class TestManagedWidgets:
    @pytest.mark.parametrize("shortcut_only", [False, True])
    @pytest.mark.parametrize(
        "dispatcher,arg",
        [
            ("dpms", "off HDMI-A-1"),
            ("cyclenext", "prev"),
            ("resizeactive", "20000 0"),
            ("resizeactive", "exact 00100 200"),
            ("workspace", ""),
            ("dpms", "off"),
            ("resizeactive", "20 -10"),
            ("workspace", "3"),
            ("killactive", ""),
            ("exec", "sh -c 'echo  \"$HOME, $USER\"'"),
        ],
    )
    def test_edit_preserves_exact_argument_with_real_widgets(
        self, widgets, dispatcher, arg, shortcut_only
    ):
        model, window, _observer = widgets
        model.ensure_loaded()
        drain(model)
        line = f"bind = SUPER, T, {dispatcher}" + (f", {arg}" if arg else "")
        bind = bindings.validate_line(line)
        model._owned = SavedList([line], key=str)
        dialog = BindEditDialog(
            bind=bind,
            window=window,
            draft_only=True,
            on_apply=lambda changed: model.edit_line(0, changed.to_line()),
        )
        dialog.present(window)
        assert dialog._apply_btn.get_label() == "Update Pending"
        assert dialog.get_bind().to_line() == line
        if shortcut_only:
            dialog._key_entry.set_text("Y")
        dialog._apply_btn.emit("clicked")
        expected = line.replace(", T,", ", Y,", 1) if shortcut_only else line
        assert model.get_config().lines == (expected,)
        assert window.hypr.mock_calls == [call.get_binds()]

    def test_fallback_argument_is_editable_and_structured_controls_still_work(self, widgets):
        _model, window, _observer = widgets
        bind = bindings.validate_line("bind = SUPER, T, dpms, off HDMI-A-1")
        dialog = BindEditDialog(bind=bind, window=window, draft_only=True)
        entry = next(w for w in descendants(dialog._arg_container) if isinstance(w, Adw.EntryRow))
        assert entry.get_text() == "off HDMI-A-1"
        entry.set_text("on DP-1")
        assert dialog.get_bind().arg == "on DP-1"
        dialog.close()
        bind = bindings.validate_line("bind = SUPER, T, dpms, off")
        dialog = BindEditDialog(bind=bind, window=window, draft_only=True)
        combo = next(w for w in descendants(dialog._arg_container) if isinstance(w, Adw.ComboRow))
        combo.set_selected(0)
        assert dialog.get_bind().arg == "on"
        dialog.close()

    def test_submap_hidden_only_in_draft_action_models(self, widgets):
        _model, window, _observer = widgets
        for draft_only in (True, False):
            dialog = BindEditDialog(window=window, draft_only=draft_only)
            dispatchers = set()
            for category in DISPATCHER_CATEGORIES:
                dialog._update_action_model(category["id"])
                dispatchers.update(dialog._current_dispatcher_keys)
            assert ("submap" in dispatchers) == (not draft_only)
            dialog.close()

    def test_lazy_build_and_runtime_metadata_no_override_buttons(self, widgets):
        model, window, observer = widgets
        observer.assert_not_called()
        model.ensure_loaded()
        drain(model)
        rows = [w for w in descendants(window) if isinstance(w, Adw.ActionRow)]
        external = [r for r in rows if "External runtime" in (r.get_subtitle() or "")]
        assert len(external) == 1
        subtitle = external[0].get_subtitle() or ""
        assert "Opaque Lua callback" in subtitle
        assert "resize" in subtitle
        assert "repeat" in subtitle
        assert "release" in subtitle
        assert "Foreign callback" in subtitle
        assert not any(isinstance(w, Gtk.Button) for w in descendants(external[0]))
        assert window.hypr.mock_calls == [call.get_binds()]

    def test_same_combo_never_hides_runtime_and_searches_origins(self, widgets):
        model, window, _observer = widgets
        model.ensure_loaded()
        drain(model)
        line = "bind = SUPER, Q, killactive"
        model._owned = SavedList([line], key=str)
        model._rebuild_list()
        rows = [w for w in descendants(window) if isinstance(w, Adw.ActionRow)]
        assert len(rows) == 2
        assert any("unknown origin" in (r.get_subtitle() or "") for r in rows)
        model._search_term = "external"
        model._rebuild_list()
        rows = [w for w in descendants(window) if isinstance(w, Adw.ActionRow)]
        assert sum(r.get_visible() for r in rows) == 1

    def test_foreign_read_error_keeps_runtime_visible(self, widgets):
        model, window, observer = widgets
        observer.side_effect = ValueError("Foreign bindings output")
        model.ensure_loaded()
        drain(model)
        assert model.locked and model.baseline is None
        rows = [w for w in descendants(window) if isinstance(w, Adw.ActionRow)]
        assert len(rows) == 1 and "External runtime" in (rows[0].get_subtitle() or "")
        assert model._add_button is not None and not model._add_button.get_sensitive()
        assert window.editor_edit_allowed()

    def test_draft_dialog_capture_manual_and_validation_never_mutate_ipc(self, widgets):
        model, window, _observer = widgets
        model.ensure_loaded()
        drain(model)
        window.hypr.reset_mock()
        dialog = BindEditDialog(
            window=window, on_apply=lambda b: model.add_line(b.to_line()), draft_only=True
        )
        dialog.present(window)
        assert dialog._apply_btn.get_label() == "Add to Pending"
        assert not dialog._trigger_mouse_btn.get_visible()
        dialog._on_start_capture(None)
        controller = dialog._key_controller
        dialog._on_key_captured(controller, Gdk.KEY_Control_L, 0, 0)
        dialog._on_key_captured(controller, Gdk.KEY_t, 0, 0)
        assert not dialog._capturing
        assert dialog._key_entry.get_text() == "T"
        dialog._key_entry.set_text("mouse:272")
        dialog._on_apply(None)
        assert not model.is_dirty()
        window.show_toast.assert_called()
        dialog._key_entry.set_text("T")
        command = next(w for w in descendants(dialog._arg_container) if isinstance(w, Adw.EntryRow))
        command.set_text("kitty")
        dialog._on_apply(None)
        assert model.is_dirty()
        window.hypr.assert_not_called()
        assert window.hypr.mock_calls == []

    @pytest.mark.parametrize("binding_lock", [False, True])
    def test_dialog_callback_rechecks_lock_after_open(self, widgets, monkeypatch, binding_lock):
        model, window, _observer = widgets
        model.ensure_loaded()
        drain(model)
        captured = []
        original = BindEditDialog.present

        def present(dialog, parent):
            captured.append(dialog)
            original(dialog, parent)

        monkeypatch.setattr(BindEditDialog, "present", present)
        model._open_dialog()
        dialog = captured[0]
        dialog._key_entry.set_text("T")
        command = next(w for w in descendants(dialog._arg_container) if isinstance(w, Adw.EntryRow))
        command.set_text("kitty")
        if binding_lock:
            model.invalidate("Writer outcome unknown")
        else:
            window.editor_edit_allowed.return_value = False
        dialog._on_apply(None)
        assert not model.is_dirty()
        window.show_toast.assert_called()
        dialog.close()


class TestPendingBaselineRevert:
    @pytest.mark.parametrize("occupied", [False, True])
    def test_actual_pending_revert_button_restores_baseline_or_toasts_atomically(
        self, window, monkeypatch, occupied
    ):
        line = "bind = SUPER, Q, killactive"
        output = Path(os.environ["XDG_CONFIG_HOME"]) / "hypr/attune-bindings.lua"
        output.write_text(bindings.build_text(bindings.BindingsConfig((line,))))
        model = open_bindings(window)
        raw = Bind(MOD_BITS["SUPER"], "Q", "__lua", "42")
        model._runtime = (raw,)
        model.edit_line(0, "bind = SUPER, T, killactive")
        if occupied:
            model._runtime = ()
            model.add_line("bind = SUPER, Q, exec, kitty")
            model._runtime = (raw,)
        toast = Mock()
        monkeypatch.setattr(window, "show_toast", toast)
        window.show_page("pending")
        pending = window._pending_page
        assert pending is not None
        rows = [w for w in descendants(pending._groups_box) if isinstance(w, Adw.ActionRow)]
        row = next(r for r in rows if r.get_title() == "SUPER + T")
        button = next(w for w in descendants(row) if isinstance(w, Gtk.Button))
        before = model._capture_undo()
        ipc = Mock(side_effect=AssertionError("No runtime changes"))
        for name in ("keyword", "dispatch"):
            monkeypatch.setattr(window.hypr, name, ipc)
        for name in ("keyword", "dispatch", "reload"):
            monkeypatch.setattr(f"hyprland_socket.{name}", ipc)
        button.emit("clicked")
        if occupied:
            assert model._capture_undo() == before
            assert model.is_dirty()
            assert "Duplicate keyboard combination" in toast.call_args.args[0]
        else:
            assert model.get_config().lines == (line,)
            assert not model.is_dirty()
            toast.assert_not_called()
        assert output.read_text() == bindings.build_text(bindings.BindingsConfig((line,)))
        model._rebuild_list()
        rows = [w for w in descendants(model._content_box) if isinstance(w, Adw.ActionRow)]
        external = [r for r in rows if "External runtime" in (r.get_subtitle() or "")]
        assert len(external) == 1
        assert not any(isinstance(w, Gtk.Button) for w in descendants(external[0]))
        assert model._runtime == (raw,)
        ipc.assert_not_called()
