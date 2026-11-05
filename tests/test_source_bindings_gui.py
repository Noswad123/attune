"""Source widgets use only temporary TSV copies, with IPC and writers forbidden by default."""

import os
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from gi.repository import Adw, Gtk

from hyprmod.core import bindings, persistence, transaction_publication
from hyprmod.core import input as input_config
from hyprmod.core import source_bindings as source
from hyprmod.core.undo import SavedListSnapshot
from hyprmod.pages.source_bindings import SourceBindingsPage
from hyprmod.ui.diff import ConfigDiffWidget
from tests.test_keybindings_workflow_gui import (
    REAL_BINDINGS_SAVE,
    REAL_PAIR_SAVE,
    REAL_VISUAL_SAVE,
    review_bindings,
    wait_for,
    widgets,
)
from tests.test_keybindings_workflow_gui import window as window
from tests.test_scoped_review import evidence as evidence
from tests.test_transaction_store import plan as plan

pytestmark = pytest.mark.skipif(
    os.environ.get("ATTUNE_GUI_SMOKE") != "1" or os.environ.get("GDK_BACKEND") != "broadway",
    reason="opt-in isolated Broadway widgets",
)

REAL_SOURCE_SAVE = source.persist_reviewed
CATALOG = Path(__file__).absolute().parents[1] / ("integrations/hyprland/jdawson/keybindings.tsv")


def copy_source(path, *, disabled=False, bridge="new"):
    config = source.read_text(CATALOG.read_text())
    if disabled:
        rows = list(config.bindings)
        index = next(i for i, b in enumerate(rows) if b.id == "terminal.t")
        rows[index] = replace(rows[index], flags=("disabled",))
        config = source.SourceConfig(config.catalog, tuple(rows))
    path.write_text(source.build_text(config))
    path.chmod(0o600)
    if bridge != "missing":
        original = (
            CATALOG.with_name(source.BRIDGE_BASENAME)
            if bridge == "new"
            else Path(__file__).parent
            / (
                "fixtures/source-bindings-old-disabled-bridge.lua"
                if bridge == "disabled-only"
                else "fixtures/source-bindings-old-bridge.lua"
            )
        )
        companion = path.with_name(source.BRIDGE_BASENAME)
        companion.write_bytes(original.read_bytes())
        companion.chmod(0o600)


@pytest.fixture
def loaded(window, tmp_path, monkeypatch):
    monkeypatch.setattr(
        input_config,
        "persist_reviewed",
        MagicMock(side_effect=AssertionError("Explicit temporary input publisher required")),
    )
    path = tmp_path / source.BASENAME
    copy_source(path)
    page = window._source_bindings_page
    assert page is not None
    page.open_path(path)
    wait_for(lambda: page._read_cancel is None)
    assert page.baseline is not None, page.load_error
    ipc = MagicMock(side_effect=AssertionError("No source IPC"))
    monkeypatch.setattr(window.hypr, "keyword", ipc)
    for name in ("dispatch", "reload", "eval_lua", "keyword", "keyword_batch"):
        monkeypatch.setattr(f"hyprland_socket.{name}", ipc)
    yield window, page, path, ipc
    wait_for(lambda: page._read_cancel is None and not page._saving)


def reviewed(page):
    page.review_changes()
    wait_for(lambda: page._read_cancel is None)
    assert page._review is not None
    return page._review


def keybinding_rows(page):
    content = list(widgets(page._content_box))
    assert not any(isinstance(w, Gtk.Expander) for w in content)
    assert not any(
        isinstance(w, Gtk.Button) and w.get_label() in {"Delete shortcut", "Assign New"}
        for w in content
    )
    assert not any(
        isinstance(w, Gtk.Label) and w.get_text() in {"Unassigned actions", "Deleted"}
        for w in content
    )
    groups = [w for w in content if isinstance(w, Adw.PreferencesGroup)]
    assert len(groups) == 1 and groups[0].get_title() == "Keybindings"
    rows = [w for w in widgets(groups[0]) if isinstance(w, Adw.ActionRow)]
    assert len(rows) == 80
    for row, binding in zip(rows, page.get_config().bindings, strict=True):
        assert row.get_title() == f"{binding.description}  |  {binding.key}"
        assert f"\n{binding.id} |" in (row.get_subtitle() or "")
        buttons = [w for w in widgets(row) if isinstance(w, Gtk.Button)]
        assert len(buttons) == 2
        assert buttons[0].get_icon_name() == "document-edit-symbolic"
        assert buttons[1].get_sensitive() == binding.assigned
        if not binding.assigned:
            assert "Edit Shortcut" in (buttons[1].get_tooltip_text() or "")
    return rows


class TestSourceWidgets:
    @pytest.mark.parametrize("initially_disabled", [False, True])
    def test_clear_terminal_save_reopen_edit_same_row_without_resurrection(
        self, loaded, monkeypatch, initially_disabled
    ):
        window, page, path, ipc = loaded
        if initially_disabled:
            copy_source(path, disabled=True)
            page.open_path(path)
            wait_for(lambda: page._read_cancel is None)
        before = page.get_config()
        index = next(i for i, b in enumerate(before.bindings) if b.id == "terminal.t")
        original = before.bindings[index]
        row = keybinding_rows(page)[index]
        assert all(w.get_visible() for w in keybinding_rows(page))
        next(
            w
            for w in widgets(row)
            if isinstance(w, Gtk.Button) and w.get_icon_name() == "document-edit-symbolic"
        ).emit("clicked")
        dialog = window.get_visible_dialog()
        assert dialog is not None and dialog.get_title() == "Edit Source Shortcut"
        entry = next(w for w in widgets(dialog) if isinstance(w, Adw.EntryRow))
        assert entry.get_text() == original.key
        entry.set_text("")
        next(
            w
            for w in widgets(dialog)
            if isinstance(w, Gtk.Button) and w.get_label() == "Update Pending"
        ).emit("clicked")
        deleted = page.get_config()
        assert deleted.bindings[index] == replace(original, key="", flags=())
        assert source.fixed_metadata(deleted) == source.fixed_metadata(before)
        assert all(w.get_visible() for w in keybinding_rows(page))
        assert keybinding_rows(page)[index].get_title() == f"{original.description}  |  "
        change = next(page.iter_pending_changes())
        assert change.kind == "removed" and change.title.startswith("Clear shortcut:")
        assert original.key in change.subtitle and "-> Unassigned:" in change.subtitle
        window._on_undo()
        assert page.get_config() == before and not page.is_dirty()
        window._on_redo()
        assert page.get_config() == deleted
        window.save()
        pending = window._pending_page
        assert pending is not None
        next(
            w
            for w in widgets(pending._groups_box)
            if isinstance(w, Gtk.Button) and w.get_tooltip_text() == "Revert this change"
        ).emit("clicked")
        assert page.get_config() == before and not page.is_dirty()
        window._on_undo()
        assert page.get_config() == deleted
        page.discard()
        assert page.get_config() == before
        page.edit_binding(index, "", original.description)
        window.show_page("binds")
        managed = window._managed_bindings_page
        assert managed is not None
        wait_for(lambda: managed.baseline is not None)
        managed.add_line("bind = SUPER, F9, killactive")
        window._on_option_changed("general:border_size", 8)
        reviewed(page)
        monkeypatch.setattr(source, "persist_reviewed", REAL_SOURCE_SAVE)
        page._save_button.emit("clicked")
        wait_for(lambda: not window._restore_in_progress)
        assert not page.is_dirty() and not page.locked
        assert managed.is_dirty() and window.app_state.has_dirty()
        assert source.read_text(path.read_text()) == deleted
        stored = next(
            line for line in path.read_text().splitlines() if line.startswith("terminal.t\t")
        )
        assert "disabled" not in stored and original.key not in stored
        page.open_path(path)
        wait_for(lambda: page._read_cancel is None)
        assert page.get_config() == deleted
        rows = keybinding_rows(page)
        assert all(w.get_visible() for w in rows)
        assert rows[index].get_title() == f"{original.description}  |  "
        labels = [w.get_text() for w in widgets(page._content_box) if isinstance(w, Gtk.Label)]
        assert "80 keybindings | 79 shortcut fields set | 0 disabled" in labels
        with pytest.raises(ValueError, match="Enter a shortcut first"):
            page.set_enabled(index, True)
        search = Gtk.SearchEntry(text=original.key)
        page._search_changed(search)
        assert not keybinding_rows(page)[index].get_visible()
        search = Gtk.SearchEntry(text="terminal.t")
        page._search_changed(search)
        assert keybinding_rows(page)[index].get_visible()
        search.set_text("")
        page._search_changed(search)
        assert all(w.get_visible() for w in keybinding_rows(page))
        next(
            w
            for w in widgets(keybinding_rows(page)[index])
            if isinstance(w, Gtk.Button) and w.get_icon_name() == "document-edit-symbolic"
        ).emit("clicked")
        dialog = window.get_visible_dialog()
        assert dialog is not None and dialog.get_title() == "Edit Source Shortcut"
        entries = [w for w in widgets(dialog) if isinstance(w, Adw.EntryRow)]
        assert entries[0].get_text() == ""
        assert entries[1].get_text() == original.description
        assert next(w for w in widgets(dialog) if isinstance(w, Adw.SwitchRow)).get_active()
        entries[0].set_text("Shift+Super+F12")
        next(
            w
            for w in widgets(dialog)
            if isinstance(w, Gtk.Button) and w.get_label() == "Update Pending"
        ).emit("clicked")
        assigned_config = page.get_config()
        assert assigned_config.bindings[index] == replace(original, key="Shift+Super+F12", flags=())
        change = next(page.iter_pending_changes())
        assert change.kind == "added" and change.title.startswith("Assign shortcut:")
        window._on_undo()
        assert page.get_config() == deleted and not page.is_dirty()
        window._on_redo()
        assert page.get_config() == assigned_config
        change.revert()
        assert page.get_config() == deleted
        window._on_undo()
        assert page.get_config() == assigned_config
        page.discard()
        assert page.get_config() == deleted
        page.edit_binding(index, "Shift+Super+F12", original.description)
        assert page.get_config() == assigned_config
        reviewed(page)
        page._save_reviewed()
        wait_for(lambda: not window._restore_in_progress)
        assert not page.is_dirty() and not page.locked
        page.open_path(path)
        wait_for(lambda: page._read_cancel is None)
        assert page.get_config() == assigned_config
        assert page.get_config().bindings[index].enabled
        assert all(w.get_visible() for w in keybinding_rows(page))
        ipc.assert_not_called()

    def test_pending_revert_clear_refuses_reused_key_atomically(self, loaded, monkeypatch):
        window, page, path, ipc = loaded
        before = page.get_config()
        baseline = page.baseline
        original_bytes = path.read_bytes()
        terminal = next(i for i, b in enumerate(before.bindings) if b.id == "terminal.t")
        other = next(i for i, b in enumerate(before.bindings) if b.id == "terminal.return")
        assert source.key_identity(before.bindings[terminal].key) == source.key_identity("SUPER+T")
        page.edit_binding(terminal, "", before.bindings[terminal].description)
        page.edit_binding(other, "SUPER+T", "Reused deleted shortcut")
        proposed = page.get_config()
        assert proposed.bindings[terminal] == replace(before.bindings[terminal], key="")
        assert proposed.bindings[other].key == "SUPER+T" and proposed.bindings[other].enabled
        window.show_page("pending")
        pending = window._pending_page
        assert pending is not None
        row = next(
            w
            for w in widgets(pending._groups_box)
            if isinstance(w, Adw.ActionRow) and w.get_title().startswith("Clear shortcut:")
        )
        assert before.bindings[terminal].description in row.get_title()
        history = (list(window._undo._undo_stack), list(window._undo._redo_stack))
        changes = [(c.title, c.subtitle, c.kind) for c in page.iter_pending_changes()]
        toast = MagicMock()
        monkeypatch.setattr(window, "show_toast", toast)
        publisher = MagicMock(side_effect=AssertionError("Revert must not save"))
        monkeypatch.setattr(source, "persist_reviewed", publisher)
        next(
            w
            for w in widgets(row)
            if isinstance(w, Gtk.Button) and w.get_tooltip_text() == "Revert this change"
        ).emit("clicked")
        wait_for(lambda: not pending._refresh_pending)
        toast.assert_called_once()
        assert "Duplicate" in toast.call_args.args[0]
        assert page.get_config() == proposed and page.baseline is baseline
        assert page.is_dirty() and not page.locked
        assert (list(window._undo._undo_stack), list(window._undo._redo_stack)) == history
        assert [(c.title, c.subtitle, c.kind) for c in page.iter_pending_changes()] == changes
        assert path.read_bytes() == original_bytes
        assert page._review is None and not page._saving
        publisher.assert_not_called()
        ipc.assert_not_called()

    @pytest.mark.parametrize("enabled", [False, True])
    def test_blank_dialog_clears_regardless_of_switch(self, loaded, enabled):
        window, page, _path, ipc = loaded
        before = page.get_config()
        page._open_dialog(1)
        dialog = window.get_visible_dialog()
        assert dialog is not None
        next(w for w in widgets(dialog) if isinstance(w, Adw.EntryRow)).set_text("  ")
        next(w for w in widgets(dialog) if isinstance(w, Adw.SwitchRow)).set_active(enabled)
        labels = [w.get_text() for w in widgets(dialog) if isinstance(w, Gtk.Label)]
        assert (
            "Leave Shortcut empty for no assignment. "
            "Disable keeps the assigned shortcut stored and off."
        ) in labels
        next(
            w
            for w in widgets(dialog)
            if isinstance(w, Gtk.Button) and w.get_label() == "Update Pending"
        ).emit("clicked")
        assert page.get_config().bindings[1] == replace(before.bindings[1], key="")
        ipc.assert_not_called()

    def test_edit_callback_errors_and_disabled_edit_preserves_state(self, loaded, monkeypatch):
        window, page, _path, ipc = loaded
        before = page.get_config()
        page.set_enabled(1, False)
        page.edit_binding(1, "Shift+Super+F12", "Still disabled")
        assert page.get_config().bindings[1] == replace(
            before.bindings[1],
            key="Shift+Super+F12",
            description="Still disabled",
            flags=("disabled",),
        )
        draft = page.get_config()
        row = next(
            w
            for w in widgets(page._content_box)
            if isinstance(w, Adw.ActionRow) and before.bindings[1].id in w.get_subtitle()
        )
        edit = next(
            w
            for w in widgets(row)
            if isinstance(w, Gtk.Button) and w.get_icon_name() == "document-edit-symbolic"
        )
        toast = MagicMock()
        monkeypatch.setattr(window, "show_toast", toast)
        with monkeypatch.context() as patch:
            patch.setattr(window, "editor_edit_allowed", lambda: False)
            edit.emit("clicked")
        toast.assert_called_once()
        assert page.get_config() == draft
        for index in (-1, len(before.bindings)):
            with pytest.raises(ValueError, match="no longer exists"):
                page.edit_binding(index, "", before.bindings[1].description)
        page.discard()
        for id in ("pointer.move", "hardware.volume.up", "manager.escape", "wisp.action.terminal"):
            index = next(i for i, b in enumerate(before.bindings) if b.id == id)
            original = before.bindings[index]
            page.set_enabled(index, False)
            page.edit_binding(index, "", original.description)
            assert page.get_config().bindings[index] == replace(original, key="")
        assert source.fixed_metadata(page.get_config()) == source.fixed_metadata(before)
        page.discard()
        assert page.get_config() == before
        ipc.assert_not_called()

    @pytest.mark.parametrize("installed", [False, True])
    def test_unassigned_disabled_only_bridge_refuses_review(
        self, window, tmp_path, monkeypatch, installed
    ):
        page = window._source_bindings_page
        assert page is not None
        if installed:
            path = Path(os.environ["XDG_CONFIG_HOME"]) / "hypr" / source.BASENAME
        else:
            path = tmp_path / source.BASENAME
        copy_source(path, bridge="disabled-only")
        selected = tmp_path / "selected"
        if installed:
            selected.mkdir()
            selected_path = selected / source.BASENAME
            selected_path.symlink_to(path)
            selected_path.with_name(source.BRIDGE_BASENAME).write_bytes(
                CATALOG.with_name(source.BRIDGE_BASENAME).read_bytes()
            )
            path = selected_path
        original = path.read_bytes()
        page.open_path(path)
        wait_for(lambda: page._read_cancel is None)
        assert page.baseline is not None, page.load_error
        baseline = page.baseline
        index = next(i for i, b in enumerate(page.get_config().bindings) if b.id == "terminal.t")
        page.edit_binding(index, "", page.get_config().bindings[index].description)
        proposed = page.get_config()
        toast = MagicMock()
        monkeypatch.setattr(window, "show_toast", toast)
        publisher = MagicMock(side_effect=AssertionError("Review required"))
        monkeypatch.setattr(source, "persist_reviewed", publisher)
        page.review_changes()
        wait_for(lambda: page._read_cancel is None)
        assert page._review is None and not page._save_button.get_visible()
        assert any("unassigned-v1" in str(c) for c in toast.call_args_list)
        page._save_reviewed()
        publisher.assert_not_called()
        assert page.is_dirty() and not page.locked
        assert page.baseline is baseline and page.get_config() == proposed
        assert path.read_bytes() == original

    def test_disable_terminal_pending_save_reopen_and_enable(self, loaded, monkeypatch):
        window, page, path, ipc = loaded
        before = page.get_config()
        index = next(i for i, b in enumerate(before.bindings) if b.id == "terminal.t")
        original = before.bindings[index]
        row = next(
            w
            for w in widgets(page._content_box)
            if isinstance(w, Adw.ActionRow) and original.id in w.get_subtitle()
        )
        next(
            w for w in widgets(row) if isinstance(w, Gtk.Button) and w.get_label() == "Disable"
        ).emit("clicked")
        disabled = page.get_config()
        assert disabled.bindings[index] == replace(original, flags=("disabled",))
        assert source.fixed_metadata(disabled) == source.fixed_metadata(before)
        assert len(disabled.bindings) == 80
        change = next(page.iter_pending_changes())
        assert change.kind == "modified" and change.title.startswith("Disable:")
        assert "Enabled:" in change.subtitle and "-> Disabled:" in change.subtitle
        managed = window._managed_bindings_page
        assert managed is not None
        window.show_page("binds")
        wait_for(lambda: managed.baseline is not None)
        managed.add_line("bind = SUPER, F9, killactive")
        window._on_option_changed("general:border_size", 8)
        window.save()
        pending = window._pending_page
        assert pending is not None
        assert any(c.title == change.title for c in pending.collect_changes())
        next(
            w
            for w in widgets(pending._content_box)
            if isinstance(w, Gtk.Button) and w.get_label() == "Review Source Shortcuts..."
        ).emit("clicked")
        wait_for(lambda: page._read_cancel is None)
        review = page._review
        assert review is not None
        assert source.SourceReview.from_json(review.to_json()) == review
        assert review.proposed == disabled and "disabled" in review.proposed_text
        monkeypatch.setattr(source, "persist_reviewed", REAL_SOURCE_SAVE)
        page._save_button.emit("clicked")
        wait_for(lambda: not window._restore_in_progress)
        assert not page.is_dirty() and not page.locked
        assert managed.is_dirty() and window.app_state.has_dirty()
        reopened = SourceBindingsPage(window)
        try:
            reopened.build()
            reopened.open_path(path)
            wait_for(lambda: reopened._read_cancel is None)
            assert reopened.get_config() == disabled
            rows = [w for w in widgets(reopened._content_box) if isinstance(w, Adw.ActionRow)]
            assert len(rows) == 80
            row = next(w for w in rows if original.id in w.get_subtitle())
            assert "Disabled" in (row.get_subtitle() or "") and row.get_visible()
            assert keybinding_rows(reopened)[index] is row
            assert original.key in row.get_title()
            search = Gtk.SearchEntry()
            search.set_text("disabled")
            reopened._search_changed(search)
            rows = [w for w in widgets(reopened._content_box) if isinstance(w, Adw.ActionRow)]
            assert sum(w.get_visible() for w in rows) == 1
            row = next(w for w in rows if w.get_visible())
            next(
                w for w in widgets(row) if isinstance(w, Gtk.Button) and w.get_label() == "Enable"
            ).emit("clicked")
            assert reopened.get_config() == before
            change = next(reopened.iter_pending_changes())
            assert change.kind == "modified" and change.title.startswith("Enable:")
            reviewed(reopened)
            reopened._save_reviewed()
            wait_for(lambda: not window._restore_in_progress)
            assert not reopened.is_dirty() and not reopened.locked
            assert source.read_text(path.read_text()) == before
        finally:
            reopened.close()
        ipc.assert_not_called()

    def test_reassign_disabled_terminal_key_save_reopen_and_refuse_enable(
        self, loaded, monkeypatch
    ):
        window, page, path, ipc = loaded
        before = page.get_config()
        terminal = next(i for i, b in enumerate(before.bindings) if b.id == "terminal.t")
        other = next(i for i, b in enumerate(before.bindings) if b.id == "terminal.return")
        row = next(
            w
            for w in widgets(page._content_box)
            if isinstance(w, Adw.ActionRow) and "terminal.t |" in (w.get_subtitle() or "")
        )
        next(
            w for w in widgets(row) if isinstance(w, Gtk.Button) and w.get_label() == "Disable"
        ).emit("clicked")
        page.edit_binding(other, "SUPER+T", "Reassigned terminal shortcut")
        proposed = page.get_config()
        assert not proposed.bindings[terminal].enabled
        assert proposed.bindings[terminal].key == before.bindings[terminal].key
        review = reviewed(page)
        assert review.proposed == proposed
        monkeypatch.setattr(source, "persist_reviewed", REAL_SOURCE_SAVE)
        page._save_button.emit("clicked")
        wait_for(lambda: not window._restore_in_progress)
        assert not page.is_dirty() and not page.locked
        saved_bytes = path.read_bytes()
        page.open_path(path)
        wait_for(lambda: page._read_cancel is None)
        assert page.get_config() == proposed and len(proposed.bindings) == 80
        assert source.fixed_metadata(proposed) == source.fixed_metadata(before)
        toast = MagicMock()
        monkeypatch.setattr(window, "show_toast", toast)
        publisher = MagicMock(side_effect=AssertionError("Refused edit must not save"))
        monkeypatch.setattr(source, "persist_reviewed", publisher)
        history = list(window._undo._undo_stack)
        row = next(
            w
            for w in widgets(page._content_box)
            if isinstance(w, Adw.ActionRow) and "terminal.t |" in (w.get_subtitle() or "")
        )
        next(
            w for w in widgets(row) if isinstance(w, Gtk.Button) and w.get_label() == "Enable"
        ).emit("clicked")
        toast.assert_called_once()
        assert "Duplicate" in toast.call_args.args[0]
        assert "saved" not in toast.call_args.args[0].casefold()
        assert page.get_config() == proposed and not page.is_dirty()
        assert list(window._undo._undo_stack) == history
        assert page._review is None and not page._save_button.get_visible()
        page._save_reviewed()
        publisher.assert_not_called()
        assert path.read_bytes() == saved_bytes
        ipc.assert_not_called()

    @pytest.mark.parametrize("bridge", ["old", "missing"])
    def test_bridge_capability_refusal_retains_all_drafts(
        self, window, tmp_path, monkeypatch, bridge
    ):
        path = tmp_path / source.BASENAME
        copy_source(path, bridge=bridge)
        original = path.read_bytes()
        page = window._source_bindings_page
        assert page is not None
        page.open_path(path)
        wait_for(lambda: page._read_cancel is None)
        index = next(i for i, b in enumerate(page.get_config().bindings) if b.id == "terminal.t")
        page.set_enabled(index, False)
        window.show_page("binds")
        managed = window._managed_bindings_page
        assert managed is not None
        wait_for(lambda: managed.baseline is not None)
        managed.add_line("bind = SUPER, F9, killactive")
        window._on_option_changed("general:border_size", 8)
        toast = MagicMock()
        monkeypatch.setattr(window, "show_toast", toast)
        publisher = MagicMock(side_effect=AssertionError("Review required"))
        monkeypatch.setattr(source, "persist_reviewed", publisher)
        window.save()
        pending = window._pending_page
        assert pending is not None
        next(
            w
            for w in widgets(pending._content_box)
            if isinstance(w, Gtk.Button) and w.get_label() == "Review Source Shortcuts..."
        ).emit("clicked")
        wait_for(lambda: page._read_cancel is None)
        assert page._review is None and not page._save_button.get_visible()
        assert any("Update the source keybindings bridge" in str(c) for c in toast.call_args_list)
        page._save_reviewed()
        publisher.assert_not_called()
        assert path.read_bytes() == original
        assert page.is_dirty() and managed.is_dirty() and window.app_state.has_dirty()
        assert not page.locked

    def test_bridge_changed_after_review_refuses_save(self, loaded, monkeypatch):
        window, page, path, ipc = loaded
        original = path.read_bytes()
        page.set_enabled(1, False)
        reviewed(page)
        bridge = path.with_name(source.BRIDGE_BASENAME)
        bridge.write_bytes(bridge.read_bytes() + b"\n-- changed after review\n")
        monkeypatch.setattr(source, "persist_reviewed", REAL_SOURCE_SAVE)
        toast = MagicMock()
        monkeypatch.setattr(window, "show_toast", toast)
        page._save_reviewed()
        wait_for(lambda: not window._restore_in_progress)
        assert page.is_dirty() and not page.locked and path.read_bytes() == original
        assert any("not saved" in str(c) for c in toast.call_args_list)
        ipc.assert_not_called()

    @pytest.mark.parametrize("initially_disabled", [False, True])
    def test_enabled_history_discard_and_atomic_pending_revert(
        self, window, tmp_path, initially_disabled
    ):
        path = tmp_path / source.BASENAME
        copy_source(path, disabled=initially_disabled)
        page = window._source_bindings_page
        assert page is not None
        page.open_path(path)
        wait_for(lambda: page._read_cancel is None)
        before = page.get_config()
        index = next(i for i, b in enumerate(before.bindings) if b.id == "terminal.t")
        original = before.bindings[index]
        page.edit_binding(index, "Shift+Super+F12", "Mixed edit", enabled=initially_disabled)
        changed = page.get_config()
        window._on_undo()
        assert page.get_config() == before and not page.is_dirty()
        window._on_redo()
        assert page.get_config() == changed
        change = next(page.iter_pending_changes())
        assert change.kind == "modified"
        assert change.title.startswith("Enable:" if initially_disabled else "Disable:")
        window.save()
        pending = window._pending_page
        assert pending is not None
        next(
            w
            for w in widgets(pending._groups_box)
            if isinstance(w, Gtk.Button) and w.get_tooltip_text() == "Revert this change"
        ).emit("clicked")
        assert page.get_config() == before and not page.is_dirty()
        window._on_undo()
        assert page.get_config() == changed
        page.edit_binding(0, original.key, "Occupy original key")
        conflict = page.get_config()
        history = list(window._undo._undo_stack)
        if initially_disabled:
            change.revert()
            assert page.get_config().bindings[index] == original
            assert page.get_config().bindings[0] == conflict.bindings[0]
        else:
            with pytest.raises(ValueError, match="Duplicate"):
                change.revert()
            assert page.get_config() == conflict and list(window._undo._undo_stack) == history
        page.discard()
        assert page.get_config() == before and not page.is_dirty()

    def test_toggle_preserves_base_flags_context_and_native_submap(self, loaded):
        _window, page, _path, ipc = loaded
        before = page.get_config()
        for id in ("pointer.move", "hardware.volume.up", "manager.escape", "wisp.action.terminal"):
            index = next(i for i, b in enumerate(before.bindings) if b.id == id)
            original = before.bindings[index]
            page.set_enabled(index, False)
            disabled = page.get_config()
            assert disabled.bindings[index] == replace(
                original, flags=tuple(sorted((*original.flags, "disabled")))
            )
            assert source.fixed_metadata(disabled) == source.fixed_metadata(before)
            page.set_enabled(index, True)
            assert page.get_config() == before and not page.is_dirty()
        ipc.assert_not_called()

    @pytest.mark.parametrize("gate", ["permission", "read", "writer"])
    def test_dialog_switch_and_callback_gate(self, loaded, monkeypatch, gate):
        window, page, _path, ipc = loaded
        before = page.get_config()
        page._open_dialog(1)
        dialog = window.get_visible_dialog()
        assert dialog is not None
        switch = next(w for w in widgets(dialog) if isinstance(w, Adw.SwitchRow))
        assert switch.get_active()
        switch.set_active(False)
        entries = [w for w in widgets(dialog) if isinstance(w, Adw.EntryRow)]
        entries[0].set_text("")
        entries[1].set_text("Disabled terminal")
        apply = next(
            w
            for w in widgets(dialog)
            if isinstance(w, Gtk.Button) and w.get_label() == "Update Pending"
        )
        with monkeypatch.context() as patch:
            if gate == "permission":
                patch.setattr(window, "editor_edit_allowed", lambda: False)
            elif gate == "read":
                patch.setattr(page, "_read_cancel", threading.Event())
            else:
                patch.setattr(page, "_saving", True)
            apply.emit("clicked")
            assert page.get_config() == before
        apply.emit("clicked")
        assert page.get_config().bindings[1] == replace(
            before.bindings[1], key="", description="Disabled terminal"
        )
        page._open_dialog(1)
        dialog = window.get_visible_dialog()
        assert dialog is not None
        switch = next(w for w in widgets(dialog) if isinstance(w, Adw.SwitchRow))
        assert switch.get_active()
        dialog.close()
        ipc.assert_not_called()

    def test_blank_enabled_boolean_and_reusable_disabled_key(self, loaded):
        _window, page, _path, ipc = loaded
        before = page.get_config()
        for enabled in (1, "false", None):
            with pytest.raises(ValueError, match="boolean"):
                page.set_enabled(1, enabled)
        page.edit_binding(1, "  ", "Remove")
        assert page.get_config().bindings[1] == replace(
            before.bindings[1], key="", description="Remove"
        )
        with pytest.raises(ValueError, match="Enter a shortcut first"):
            page.set_enabled(1, True)
        page.discard()
        page.set_enabled(1, False)
        page.edit_binding(0, before.bindings[1].key, "Reused")
        disabled = page.get_config()
        assert disabled.bindings[0].key == disabled.bindings[1].key
        rows, baselines = page._capture_undo()
        rows[1] = replace(rows[1], flags=("disabled", "locked"))
        with pytest.raises(ValueError, match="read-only"):
            page.restore_snapshot(rows, baselines)
        assert page.get_config() == disabled
        ipc.assert_not_called()

    @pytest.mark.parametrize("location", ["prepared", "standard"])
    def test_reload_warning_does_not_infer_loading_from_path(
        self, window, tmp_path, monkeypatch, location
    ):
        page = window._source_bindings_page
        assert page is not None
        if location == "prepared":
            directory = tmp_path / "integrations/hyprland/jdawson"
            directory.mkdir(parents=True)
            path = directory / source.BASENAME
            monkeypatch.setattr(page, "_prepared_path", path)
        else:
            path = Path(os.environ["XDG_CONFIG_HOME"]) / "hypr" / source.BASENAME
        path.write_bytes(CATALOG.read_bytes())
        if location == "prepared":
            button = next(
                w
                for w in widgets(window)
                if isinstance(w, Gtk.Button) and w.get_label() == "Open Prepared Source Mappings"
            )
            assert "offline prepared bundle" in (button.get_tooltip_text() or "")
            button.emit("clicked")
        else:
            page.ensure_loaded()
        wait_for(lambda: page._read_cancel is None)
        assert page.baseline is not None, page.load_error
        assert page.baseline.lexical_path == str(path)
        reviewed(page)
        labels = [w.get_text() for w in widgets(page._review_box) if isinstance(w, Gtk.Label)]
        warning = (
            "Attune does not install a loader or send reload IPC. "
            "Saving an already-integrated or watched file may trigger an immediate reload. "
            "Loading/activation is unverified."
        )
        assert any(warning in label for label in labels)
        assert all("only if you integrate" not in label for label in labels)

    def test_actual_pending_rows_select_their_binding_tabs(self, loaded):
        window, page, _path, _ipc = loaded
        window.show_source_bindings_review()
        wait_for(lambda: page._read_cancel is None)
        managed = window._managed_bindings_page
        assert managed is not None
        wait_for(lambda: managed.baseline is not None)
        managed.add_line("bind = SUPER, F9, killactive")
        page.edit_binding(0, "Shift+Super+F12", "Pending source shortcut")
        window.save()
        pending = window._pending_page
        assert pending is not None
        assert window._bindings_tabs is not None
        assert window._bindings_tabs.get_visible_child_name() == "existing"
        groups = [w for w in widgets(pending._groups_box) if isinstance(w, Adw.PreferencesGroup)]
        managed_group = next(group for group in groups if group.get_title() == "Keybindings")
        managed_row = next(w for w in widgets(managed_group) if isinstance(w, Adw.ActionRow))
        managed_row.emit("activated")
        assert window._page_stack.get_visible_child_name() == "binds"
        assert window._bindings_tabs.get_visible_child_name() == "additional"
        window.save()
        groups = [w for w in widgets(pending._groups_box) if isinstance(w, Adw.PreferencesGroup)]
        source_group = next(group for group in groups if group.get_title() == "Source Shortcuts")
        source_row = next(w for w in widgets(source_group) if isinstance(w, Adw.ActionRow))
        source_row.emit("activated")
        assert window._page_stack.get_visible_child_name() == "binds"
        assert window._bindings_tabs.get_visible_child_name() == "existing"
        wait_for(lambda: page._read_cancel is None)

    def test_prepared_button_edit_review_save_reopen_temporary_copy(
        self, window, tmp_path, monkeypatch
    ):
        page = window._source_bindings_page
        assert page is not None
        directory = tmp_path / "integrations/hyprland/jdawson"
        directory.mkdir(parents=True)
        path = directory / source.BASENAME
        original = CATALOG.read_bytes()
        path.write_bytes(original)
        monkeypatch.setattr(page, "_prepared_path", path)
        prepared = next(
            w
            for w in widgets(window)
            if isinstance(w, Gtk.Button) and w.get_label() == "Open Prepared Source Mappings"
        )
        prepared.emit("clicked")
        wait_for(lambda: page._read_cancel is None)
        assert page.baseline is not None, page.load_error
        assert len(page.get_config().bindings) == 80
        first = page.get_config().bindings[0]
        row = next(w for w in widgets(page._content_box) if isinstance(w, Adw.ActionRow))
        edit = next(w for w in widgets(row) if isinstance(w, Gtk.Button))
        edit.emit("clicked")
        dialog = window.get_visible_dialog()
        assert dialog is not None
        entries = [w for w in widgets(dialog) if isinstance(w, Adw.EntryRow)]
        entries[0].set_text("Shift+Super+F12")
        entries[1].set_text("Prepared copy edited through buttons")
        apply = next(
            w
            for w in widgets(dialog)
            if isinstance(w, Gtk.Button) and w.get_label() == "Update Pending"
        )
        apply.emit("clicked")
        review = next(
            w
            for w in widgets(window)
            if isinstance(w, Gtk.Button) and w.get_label() == "Review Source Shortcuts..."
        )
        review.emit("clicked")
        wait_for(lambda: page._read_cancel is None)
        assert page._review is not None

        def publish(review, proposed):
            assert review.baseline.lexical_path == str(path)
            assert path != CATALOG
            return REAL_SOURCE_SAVE(review, proposed)

        monkeypatch.setattr(source, "persist_reviewed", publish)
        save = next(
            w
            for w in widgets(window)
            if isinstance(w, Gtk.Button) and w.get_label() == "Save Reviewed Source Shortcuts"
        )
        assert save.get_visible() and save.get_sensitive()
        save.emit("clicked")
        wait_for(lambda: not window._restore_in_progress)
        assert not page.locked and not page.is_dirty(), page.load_error
        prepared.emit("clicked")
        wait_for(lambda: page._read_cancel is None)
        assert page.get_config().bindings[0] == replace(
            first, key="Shift+Super+F12", description="Prepared copy edited through buttons"
        )
        assert len(page.get_config().bindings) == 80
        assert CATALOG.read_bytes() == original

    def test_all_80_are_descriptive_editable_and_selected_data_unverified(self, loaded):
        window, page, _path, ipc = loaded
        config = page.get_config()
        assert len(config.bindings) == 80
        rows = [w for w in widgets(page._content_box) if isinstance(w, Adw.ActionRow)]
        assert len(rows) == 80
        for row, binding in zip(rows, config.bindings, strict=True):
            assert binding.description in row.get_title()
            assert binding.key in row.get_title()
            assert binding.id in row.get_subtitle()
            assert "Authored Lua action (unchanged)" in (row.get_subtitle() or "")
            assert len([w for w in widgets(row) if isinstance(w, Gtk.Button)]) == 2
        labels = [w.get_text() for w in widgets(page._content_box) if isinstance(w, Gtk.Label)]
        assert any("Selected source data; activation/loading unverified" in s for s in labels)
        assert not page.is_dirty()
        assert window.editor_edit_allowed()
        ipc.assert_not_called()

    def test_two_field_dialog_preserves_metadata_and_exact_key(self, loaded):
        window, page, _path, ipc = loaded
        before = page.get_config()
        page._open_dialog(0)
        dialog = window.get_visible_dialog()
        assert dialog is not None
        entries = [w for w in widgets(dialog) if isinstance(w, Adw.EntryRow)]
        assert [w.get_title() for w in entries] == ["Shortcut", "Description"]
        entries[0].set_text("Shift+Super+F12")
        entries[1].set_text("My literal <&> shortcut")
        button = next(
            w
            for w in widgets(dialog)
            if isinstance(w, Gtk.Button) and w.get_label() == "Update Pending"
        )
        button.emit("clicked")
        assert page.get_config().bindings[0] == replace(
            before.bindings[0], key="Shift+Super+F12", description="My literal <&> shortcut"
        )
        assert page.get_config().bindings[1:] == before.bindings[1:]
        assert page.is_dirty()
        window._on_undo()
        assert page.get_config() == before
        window._on_redo()
        assert page.is_dirty()
        ipc.assert_not_called()

    def test_native_submap_conflicts_full_proposal_before_mutation(self, loaded):
        _window, page, _path, _ipc = loaded
        original = page.get_config()
        target = next(i for i, b in enumerate(original.bindings) if b.context == "manager")
        global_row = next(b for b in original.bindings if b.context == "global")
        with pytest.raises(ValueError, match="Duplicate"):
            page.edit_binding(target, global_row.key.swapcase(), "Conflict")
        assert page.get_config() == original
        wisp = next(i for i, b in enumerate(original.bindings) if b.submap == "wisp")
        page.edit_binding(wisp, "Shift+Super+F12", "Native submap")
        page.edit_binding(target, "super+shift+f12", "Global manager context")
        assert page.is_dirty()

    def test_real_review_save_reopen_only_temporary_source(self, loaded, monkeypatch):
        window, page, path, ipc = loaded
        before = page.get_config()
        page.edit_binding(0, "Shift+Super+F12", "Edited shortcut")
        review = reviewed(page)
        diff = next(w for w in widgets(page._review_box) if isinstance(w, ConfigDiffWidget))
        start, end = diff._buffer.get_bounds()
        assert diff._buffer.get_text(start, end, True) == review.diff.removesuffix("\n")
        assert page._save_button is not None and page._save_button.get_visible()

        def publish(review, proposed):
            assert not threading.current_thread().daemon
            assert threading.current_thread() is not threading.main_thread()
            assert review.baseline.lexical_path == str(path)
            return REAL_SOURCE_SAVE(review, proposed)

        monkeypatch.setattr(source, "persist_reviewed", publish)
        page._save_reviewed()
        wait_for(lambda: not window._restore_in_progress)
        assert not page.locked and not page.is_dirty(), page.load_error
        saved = source.read_text(path.read_text())
        assert saved.bindings[1:] == before.bindings[1:]
        assert saved.bindings[0].description == "Edited shortcut"
        reopened = SourceBindingsPage(window)
        reopened.open_path(path)
        wait_for(lambda: reopened._read_cancel is None)
        assert reopened.get_config() == saved
        reopened.close()
        ipc.assert_not_called()

    def test_pending_navigation_other_units_survive_source_save(self, loaded, monkeypatch):
        window, page, _path, _ipc = loaded
        window.show_page("binds")
        managed = window._managed_bindings_page
        assert managed is not None
        wait_for(lambda: managed.baseline is not None)
        managed.add_line("bind = SUPER, F9, killactive")
        window._on_option_changed("general:border_size", 8)
        page.edit_binding(0, "Shift+Super+F12", "Source draft")
        window.save()
        pending = window._pending_page
        assert pending is not None
        changes = pending.collect_changes()
        assert any(c.category == "Source Shortcuts" and c.navigate_to == "binds" for c in changes)
        button = next(
            w
            for w in widgets(pending._content_box)
            if isinstance(w, Gtk.Button) and w.get_label() == "Review Source Shortcuts..."
        )
        button.emit("clicked")
        wait_for(lambda: page._read_cancel is None)
        assert page._review is not None
        assert window._bindings_tabs is not None
        assert window._bindings_tabs.get_visible_child_name() == "existing"
        monkeypatch.setattr(source, "persist_reviewed", REAL_SOURCE_SAVE)
        page._save_reviewed()
        wait_for(lambda: not window._restore_in_progress)
        assert not page.is_dirty()
        assert managed.is_dirty() and window.app_state.has_dirty()
        assert all(
            not isinstance(e, SavedListSnapshot) or e.page_attr != "_source_bindings_page"
            for e in window._undo._undo_stack
        )
        assert window._undo._undo_stack

    def test_source_undo_survives_visual_save_and_managed_save(self, loaded, monkeypatch):
        window, page, _path, _ipc = loaded
        window.show_page("binds")
        managed = window._managed_bindings_page
        assert managed is not None
        wait_for(lambda: managed.baseline is not None)
        window._on_option_changed("general:border_size", 8)
        managed.add_line("bind = SUPER, F9, killactive")
        before = page.get_config()
        page.edit_binding(0, "Shift+Super+F12", "Keep source draft")
        monkeypatch.setattr(bindings, "persist_reviewed", REAL_BINDINGS_SAVE)
        pending = review_bindings(window)
        pending._on_save_bindings(pending._bindings_save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert page.is_dirty() and window.app_state.has_dirty() and not managed.is_dirty()
        monkeypatch.setattr(persistence, "persist_reviewed", REAL_VISUAL_SAVE)
        monkeypatch.setattr(transaction_publication, "publish_reviewed", REAL_PAIR_SAVE)
        window.save()
        if window.pair_layout is not None:
            wait_for(lambda: pending._pair_review is not None)
        else:
            assert pending._reviewed is not None
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert not window.app_state.has_dirty()
        assert page.is_dirty()
        window._on_undo()
        assert page.get_config() == before

    @pytest.mark.parametrize(
        "bad",
        [object(), source.SourceSaveResult("failed", None, None, True, "Uncertain test result")],
    )
    def test_uncertain_result_locks_source_only_and_retains_history(self, loaded, monkeypatch, bad):
        window, page, _path, _ipc = loaded
        page.edit_binding(0, "Shift+Super+F12", "Retain me")
        reviewed(page)
        monkeypatch.setattr(source, "persist_reviewed", MagicMock(return_value=bad))
        page._save_reviewed()
        wait_for(lambda: not window._restore_in_progress)
        assert page.locked and page.is_dirty()
        assert window.editor_edit_allowed() and window._undo._undo_stack
        window._on_undo()
        assert page.is_dirty() and window._undo._undo_stack

    def test_direct_writer_close_veto_exclusion_and_one_shot(self, loaded, monkeypatch):
        window, page, _path, _ipc = loaded
        page.edit_binding(0, "Shift+Super+F12", "Writer draft")
        reviewed(page)
        entered, release = threading.Event(), threading.Event()

        def publish(*_args):
            entered.set()
            release.wait(10)
            return source.SourceSaveResult("failed", None, None, False, "Refused test")

        publisher = MagicMock(side_effect=publish)
        monkeypatch.setattr(source, "persist_reviewed", publisher)
        page._save_reviewed()
        try:
            wait_for(entered.is_set)
            assert window._restore_owner == "source-bindings"
            assert window._on_close_request(window)
            window.finish_restore(False)
            assert window._restore_owner == "source-bindings"
            assert not window.begin_source_bindings_save()
            page._save_reviewed()
            publisher.assert_called_once()
        finally:
            release.set()
            wait_for(lambda: not window._restore_in_progress)
        assert not page.locked and page.is_dirty()

    def test_dirty_choice_review_invalidation_and_stale_file(self, loaded):
        _window, page, path, _ipc = loaded
        page.edit_binding(0, "Shift+Super+F12", "Draft")
        with pytest.raises(ValueError, match="Discard"):
            page.open_path(path)
        reviewed(page)
        page.edit_binding(0, "Shift+Super+F12", "New revision")
        assert page._review is None
        path.write_text(path.read_text().replace("global", "invalid", 1))
        page.review_changes()
        wait_for(lambda: page._read_cancel is None)
        assert page._review is None and page.is_dirty()

    def test_missing_and_malformed_source_keeps_app_usable(self, window, tmp_path):
        page = window._source_bindings_page
        assert page is not None
        page.ensure_loaded()
        wait_for(lambda: page._read_cancel is None)
        assert page.load_error and not page.locked and window.editor_edit_allowed()
        path = tmp_path / source.BASENAME
        path.write_text("not TSV\n")
        page.open_path(path)
        wait_for(lambda: page._read_cancel is None)
        assert page.baseline is None and page.load_error
        assert not page.locked and window.editor_edit_allowed()

    @pytest.mark.parametrize("close", [False, True])
    def test_stale_review_completion_cannot_enable_save(self, loaded, monkeypatch, close):
        _window, page, _path, _ipc = loaded
        page.edit_binding(0, "Shift+Super+F12", "First revision")
        baseline = page.baseline
        assert baseline is not None
        result = source.prepare_review(baseline, page.get_config())
        entered, release = threading.Event(), threading.Event()

        def prepare(*_args, **_kwargs):
            entered.set()
            release.wait(10)
            return result

        monkeypatch.setattr(source, "run_prepare_review", prepare)
        page.review_changes()
        try:
            wait_for(entered.is_set)
            if close:
                page.close()
            else:
                page._invalidate_review()
            page.review_changes()
        finally:
            release.set()
            wait_for(lambda: page._read_cancel is None)
        assert page._review is None
        assert page._save_button is not None and not page._save_button.get_visible()

    def test_noop_preserves_other_dirty_units(self, loaded, monkeypatch):
        window, page, _path, _ipc = loaded
        window._on_option_changed("general:border_size", 8)
        reviewed(page)
        monkeypatch.setattr(source, "persist_reviewed", REAL_SOURCE_SAVE)
        page._save_reviewed()
        wait_for(lambda: not window._restore_in_progress)
        assert not page.is_dirty() and not page.locked
        assert window.app_state.has_dirty() and window._undo._undo_stack

    def test_other_writer_refuses_consumed_review(self, loaded, monkeypatch):
        window, page, _path, _ipc = loaded
        page.edit_binding(0, "Shift+Super+F12", "Source draft")
        reviewed(page)
        window._restore_owner = "save-bindings"
        window._restore_in_progress = True
        publisher = MagicMock()
        monkeypatch.setattr(source, "persist_reviewed", publisher)
        try:
            page._save_reviewed()
            assert page._review is None
            assert window._restore_owner == "save-bindings"
            publisher.assert_not_called()
        finally:
            window._restore_owner = None
            window._restore_in_progress = False

    def test_writer_setup_failure_is_not_uncertain(self, loaded, monkeypatch):
        window, page, _path, _ipc = loaded
        page.edit_binding(0, "Shift+Super+F12", "Source draft")
        reviewed(page)
        with monkeypatch.context() as patch:
            patch.setattr(threading.Thread, "start", MagicMock(side_effect=RuntimeError("setup")))
            page._save_reviewed()
        assert not window._restore_in_progress and not page.locked and page.is_dirty()

    def test_wrong_observation_context_refused(self, window, tmp_path, monkeypatch):
        first = tmp_path / "first"
        first.mkdir()
        path = first / source.BASENAME
        path.write_bytes(CATALOG.read_bytes())
        baseline = source.observe(path, Path(os.environ["XDG_STATE_HOME"]))
        monkeypatch.setattr(source, "run_observe", MagicMock(return_value=baseline))
        page = window._source_bindings_page
        assert page is not None
        page.open_path(tmp_path / source.BASENAME)
        wait_for(lambda: page._read_cancel is None)
        assert page.baseline is None and page.load_error

    def test_readonly_metadata_and_order_rejected_by_snapshot(self, loaded):
        _window, page, _path, _ipc = loaded
        rows, baselines = page._capture_undo()
        reordered = list(reversed(rows))
        with pytest.raises(ValueError, match="read-only"):
            page.restore_snapshot(reordered, baselines)
        changed = list(rows)
        changed[0] = replace(rows[0], id="changed.id")
        with pytest.raises(ValueError, match="read-only"):
            page.restore_snapshot(changed, baselines)
        assert not page.is_dirty()
