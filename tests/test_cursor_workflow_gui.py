"""Isolated Cursor/Devices views sharing one reviewed, temporary Input output."""

import os
import threading
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from gi.repository import Adw

from hyprmod.core import bindings, persistence, source_bindings, transaction_publication
from hyprmod.core import input as backend
from hyprmod.core.undo import OptionChange, SavedListSnapshot
from hyprmod.pages import cursor as inherited_cursor
from hyprmod.ui.options.numeric import PreciseFloatOptionRow
from hyprmod.window import HyprModWindow
from tests.test_input_workflow_gui import (
    REAL_INPUT_SAVE,
    history,
    open_input,
    review_input,
    save_input,
)
from tests.test_keybindings_workflow_gui import (
    REAL_BINDINGS_SAVE,
    REAL_PAIR_SAVE,
    REAL_VISUAL_SAVE,
    open_bindings,
    review_bindings,
    wait_for,
    widgets,
)
from tests.test_keybindings_workflow_gui import window as window
from tests.test_scoped_review import evidence as evidence
from tests.test_source_bindings_gui import REAL_SOURCE_SAVE, copy_source, reviewed
from tests.test_transaction_store import plan as plan

pytestmark = pytest.mark.skipif(
    os.environ.get("ATTUNE_GUI_SMOKE") != "1" or os.environ.get("GDK_BACKEND") != "broadway",
    reason="opt-in isolated Broadway widgets",
)

CURSOR_DEFAULTS = {
    "cursor:no_warps": False,
    "cursor:persistent_warps": False,
    "cursor:warp_on_change_workspace": 0,
    "cursor:zoom_factor": 1.0,
    "cursor:inactive_timeout": 0.0,
    "cursor:hide_on_key_press": False,
    "cursor:hide_on_touch": True,
    "cursor:hide_on_tablet": False,
}


@pytest.fixture(autouse=True)
def no_cursor_side_effects(monkeypatch):
    forbidden = MagicMock(side_effect=AssertionError("Cursor must remain draft-only"))
    monkeypatch.setattr(inherited_cursor, "set_cursor", forbidden)
    monkeypatch.setattr(inherited_cursor, "_run", forbidden)
    monkeypatch.setattr(inherited_cursor.CursorPage, "__init__", forbidden)
    for name in ("set_cursor", "dispatch", "reload", "eval_lua", "keyword", "keyword_batch"):
        monkeypatch.setattr(f"hyprland_socket.{name}", forbidden)
    yield forbidden
    forbidden.assert_not_called()


def open_cursor(window):
    window.navigate("cursor")
    page = window._input_page
    if page is None:
        pytest.fail("Cursor requires the shared Input owner")
    wait_for(lambda: page.baseline is not None or page.load_error is not None)
    assert page.baseline is not None, page.load_error
    assert window._page_stack.get_visible_child_name() == "cursor"
    return page


class TestCursorWorkflow:
    def test_shared_owner_rows_domains_search_and_pending_navigation(self, window, monkeypatch):
        page = open_cursor(window)
        baseline = page.baseline
        assert open_input(window) is page and page.baseline is baseline
        assert window._cursor_page is None
        assert backend.CURSOR_KEYS == frozenset(CURSOR_DEFAULTS)
        assert len(backend.INPUT_KEYS) == 23
        assert set(page._rows) == backend.INPUT_KEYS
        assert len({id(row) for row in page._rows.values()}) == 22
        for key, default in CURSOR_DEFAULTS.items():
            assert backend.DEFAULTS[key] == default
            assert type(backend.DEFAULTS[key]) is type(default)
        toolbar = window._page_stack.get_child_by_name("cursor")
        cursor_widgets = list(widgets(toolbar))
        assert all(page._rows[key].row in cursor_widgets for key in backend.CURSOR_KEYS)
        devices_widgets = list(widgets(window._page_stack.get_child_by_name("input")))
        assert all(page._rows[key].row not in devices_widgets for key in backend.CURSOR_KEYS)
        for key, lower, upper in (
            ("cursor:zoom_factor", 1.0, 10.0),
            ("cursor:inactive_timeout", 0.0, 20.0),
        ):
            row = page._rows[key]
            assert isinstance(row, PreciseFloatOptionRow)
            assert row.option["min"] == lower and row.option["max"] == upper
        workspace = page._rows["cursor:warp_on_change_workspace"].row
        assert isinstance(workspace, Adw.ComboRow)
        choices = workspace.get_model()
        if choices is None:
            pytest.fail("Workspace warp mode requires enum choices")
        assert choices.get_n_items() == 3
        for selected in (1, 2, 0):
            workspace.set_selected(selected)
            value = dict(page.get_config().values)["cursor:warp_on_change_workspace"]
            assert type(value) is int and value == selected
        page.discard()
        assert not backend.INPUT_KEYS.intersection(window.app_state.options)
        assert not backend.INPUT_KEYS.intersection(window.options_flat)
        entries = {entry["key"]: entry for entry in page.get_search_entries()}
        assert all(entries[key]["_group_id"] == "cursor" for key in backend.CURSOR_KEYS)
        assert all(
            entries[key]["_group_id"] == "input" for key in backend.INPUT_KEYS - backend.CURSOR_KEYS
        )
        results = window._search_page_builder.search("warp")
        assert any(result["_group_id"] == "cursor" for result in results)
        highlight = MagicMock()
        monkeypatch.setattr(page, "highlight_option", highlight)
        window._on_search_result_activate("cursor", "cursor:no_warps")
        assert window._page_stack.get_visible_child_name() == "cursor"
        highlight.assert_called_once_with("cursor:no_warps")
        page.set_keyboard_sources("us,de", ",nodeadkeys")
        page.set_value("cursor:no_warps", True)
        changes = list(page.iter_pending_changes())
        assert sum(change.navigate_to == "input" for change in changes) == 2
        assert sum(change.navigate_to == "cursor" for change in changes) == 1
        for destination in ("input", "cursor"):
            count = sum(change.navigate_to == destination for change in changes)
            assert window._sidebar._rows_by_id[destination]._badge.get_text() == str(count)
        assert window._sidebar._rows_by_id["pending"]._badge.get_text() == "3"

    def test_real_combined_save_reopen_repeat_preserves_all_other_values(
        self, window, monkeypatch, no_cursor_side_effects
    ):
        root = Path(os.environ["XDG_CONFIG_HOME"])
        main = root / "hypr/hyprland.lua"
        main.write_text("-- authored Lua must not be read\n")
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if path == main:
                raise AssertionError("Cursor must not read authored main Lua")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", guarded_open)
        page = open_cursor(window)
        originals = {
            path: path.read_bytes() for path in root.rglob("*") if path.is_file() and path != main
        }
        state = Path(os.environ["XDG_STATE_HOME"])
        old_state = {path: path.read_bytes() for path in state.rglob("*") if path.is_file()}
        calls = []

        def publish(review, proposed):
            assert threading.current_thread() is not threading.main_thread()
            assert not threading.current_thread().daemon
            assert review.baseline.lexical_path == str(root / "hypr" / backend.BASENAME)
            calls.append(review)
            return REAL_INPUT_SAVE(review, proposed)

        monkeypatch.setattr(backend, "persist_reviewed", publish)
        for key, value in backend.DEFAULTS.items():
            page.set_value(key, value)
        open_input(window).set_keyboard_sources("us,de", ",nodeadkeys")
        page.set_value("input:kb_options", "vendor:unknown,caps:escape")
        open_cursor(window)
        zoom = page._rows["cursor:zoom_factor"]
        assert isinstance(zoom, PreciseFloatOptionRow)
        zoom.row.set_text("2.5")
        zoom.row.emit("apply")
        expected = page.get_config()
        pending = review_input(window)
        assert 'kb_layout = "us,de"' in pending._input_review.diff
        assert "zoom_factor = 2.5" in pending._input_review.diff
        assert not backend.INPUT_KEYS.intersection(window.app_state.options)
        pending._on_save_input(pending._input_save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert not page.is_dirty() and not window.has_dirty()
        output = root / "hypr" / backend.BASENAME
        assert backend.read_text(output.read_text()) == expected
        reopened = HyprModWindow(
            application=window.get_application(), pair_layout=window.pair_layout
        )
        try:
            assert open_cursor(reopened).get_config() == expected
            assert open_input(reopened).get_config() == expected
        finally:
            if reopened._pending_page is not None:
                reopened._pending_page.cancel_review()
            reopened.destroy()
        page.set_value("cursor:hide_on_touch", False)
        save_input(window)
        values = dict(expected.values) | {"cursor:hide_on_touch": False}
        assert backend.read_text(output.read_text()) == backend.InputConfig.from_mapping(values)
        open_input(window).set_value("input:repeat_rate", 37)
        save_input(window)
        values["input:repeat_rate"] = 37
        assert backend.read_text(output.read_text()) == backend.InputConfig.from_mapping(values)
        assert len(calls) == 3 and not page.locked
        assert backend.run_observe(root, state) == page.baseline
        assert {p for p in root.rglob("*") if p.is_file()} == set(originals) | {main, output}
        for path, content in originals.items():
            assert path.read_bytes() == content
        with original_open(main, "rb") as stream:
            assert stream.read() == b"-- authored Lua must not be read\n"
        assert {
            p
            for p in state.rglob("*")
            if p.is_file() and p.name != "input.lock" and "input-backups" not in p.parts
        } == set(old_state)
        for path, content in old_state.items():
            assert path.read_bytes() == content
        no_cursor_side_effects.assert_not_called()

    def test_device_only_saved_output_accepts_cursor_without_losing_devices(
        self, window, monkeypatch
    ):
        page = open_input(window)
        for key in sorted(backend.INPUT_KEYS - backend.CURSOR_KEYS):
            page.set_value(key, backend.DEFAULTS[key])
        page.set_keyboard_sources("de,us", "nodeadkeys,")
        page.set_value("input:kb_options", "vendor:unknown,grp:alt_shift_toggle")
        devices = page.get_config()
        monkeypatch.setattr(backend, "persist_reviewed", REAL_INPUT_SAVE)
        save_input(window)
        reopened = HyprModWindow(
            application=window.get_application(), pair_layout=window.pair_layout
        )
        try:
            model = open_cursor(reopened)
            assert model.get_config() == devices
            model.set_value("cursor:persistent_warps", True)
            save_input(reopened)
            assert dict(model.get_config().values) == dict(devices.values) | {
                "cursor:persistent_warps": True
            }
            saved = model.baseline
            if saved is None:
                pytest.fail("Successful Input save requires a verified baseline")
            assert backend.read_text(Path(saved.lexical_path).read_text()) == model.get_config()
        finally:
            if reopened._pending_page is not None:
                reopened._pending_page.cancel_review()
            reopened.destroy()

    @pytest.mark.parametrize("first", ["input", "cursor"])
    def test_either_view_invalidates_the_shared_review(self, window, first):
        page = open_cursor(window)
        page.set_value("input:left_handed" if first == "input" else "cursor:no_warps", True)
        pending = review_input(window)
        old = pending._input_review
        page.set_value("cursor:no_warps" if first == "input" else "input:left_handed", True)
        assert pending._input_review is None and not pending._input_save_button.get_sensitive()
        window.save_input_reviewed(old, old.proposed)
        cast(MagicMock, backend.persist_reviewed).assert_not_called()
        fresh = review_input(window)._input_review
        assert "left_handed = true" in fresh.diff and "no_warps = true" in fresh.diff

    def test_device_only_proposal_cannot_publish_a_combined_review(self, window):
        page = open_cursor(window)
        page.set_value("input:left_handed", True)
        page.set_value("cursor:no_warps", True)
        pending = review_input(window)
        baseline, before = page.baseline, history(window)
        device_only = backend.InputConfig.from_mapping({"input:left_handed": True})
        window.save_input_reviewed(pending._input_review, device_only)
        cast(MagicMock, backend.persist_reviewed).assert_not_called()
        assert page.baseline is baseline and history(window) == before
        assert page.is_dirty() and not page.locked and not window._restore_in_progress

    def test_device_only_review_cannot_authorize_a_combined_draft(self, window, monkeypatch):
        page = open_cursor(window)
        page.set_value("input:left_handed", True)
        page.set_value("cursor:no_warps", True)
        prepare = backend.run_prepare_review

        def omit_cursor(baseline, proposed, **kwargs):
            return prepare(
                baseline,
                backend.InputConfig.from_mapping({"input:left_handed": True}),
                **kwargs,
            )

        monkeypatch.setattr(backend, "run_prepare_review", omit_cursor)
        window.save()
        pending = window._pending_page
        wait_for(lambda: pending._input_read_cancel is None)
        assert pending._input_review is None and not pending._input_save_button.get_sensitive()
        cast(MagicMock, backend.persist_reviewed).assert_not_called()
        assert page.is_dirty() and not page.locked

    def test_paired_keyboard_cursor_undo_redo_pending_revert_and_discard(self, window):
        page = open_cursor(window)
        before = page.get_config()
        open_input(window).set_keyboard_sources("us,de", ",nodeadkeys")
        keyboard = page.get_config()
        open_cursor(window).set_value("cursor:no_warps", True)
        combined = page.get_config()
        assert all(
            isinstance(entry, SavedListSnapshot) and entry.page_attr == "_input_page"
            for entry in history(window)[0]
        )
        assert len(history(window)[0]) == 2
        window._on_undo()
        assert page.get_config() == keyboard
        window._on_undo()
        assert page.get_config() == before
        window._on_redo()
        window._on_redo()
        assert page.get_config() == combined
        cursor = next(c for c in page.iter_pending_changes() if c.navigate_to == "cursor")
        cursor.revert()
        assert page.get_config() == keyboard
        next(page.iter_pending_changes()).revert()
        assert page.get_config() == before
        page.set_keyboard_sources("gb", "")
        page.set_value("cursor:hide_on_tablet", True)
        window._do_discard()
        assert page.get_config() == before and not window.has_dirty()

    @pytest.mark.parametrize("buffer", ["caps:escape", "invalid token"])
    def test_cursor_changes_preserve_unapplied_keyboard_options(self, window, buffer):
        page = open_input(window)
        row = page._rows["input:kb_options"].row
        assert isinstance(row, Adw.EntryRow)
        row.set_text(buffer)
        open_cursor(window).set_value("cursor:no_warps", True)
        page.set_value("cursor:zoom_factor", 2.0)
        page.remove_override("cursor:no_warps")
        next(c for c in page.iter_pending_changes() if c.navigate_to == "cursor").revert()
        assert row.get_text() == buffer
        assert "input:kb_options" not in dict(page.get_config().values)
        assert (
            "Unapplied text (not in draft)" in page._origin_labels["input:kb_options"].get_label()
        )
        row.emit("apply")
        assert ("input:kb_options" in dict(page.get_config().values)) == (buffer == "caps:escape")

    @pytest.mark.parametrize("other", ["source", "managed", "visual"])
    @pytest.mark.parametrize("input_first", [False, True])
    def test_sequential_saves_with_mixed_input_draft_preserve_other_units(
        self, window, monkeypatch, other, input_first
    ):
        root = Path(os.environ["XDG_CONFIG_HOME"])
        source = window._source_bindings_page
        path = root / "hypr" / source_bindings.BASENAME
        copy_source(path)
        source.open_path(path)
        wait_for(lambda: source.baseline is not None)
        managed = open_bindings(window)
        page = open_cursor(window)
        pages = {"input": page, "source": source, "managed": managed}
        baselines = {unit: model.baseline for unit, model in pages.items()}
        visual_baseline = {
            key: (state.saved_value, state.saved_managed)
            for key, state in window.app_state.options.items()
        }
        page.set_keyboard_sources("us,de", ",nodeadkeys")
        page.set_value("cursor:no_warps", True)
        source.edit_binding(0, "Shift+Super+F12", "Mixed cursor workflow")
        managed.add_line("bind = SUPER, F9, killactive")
        window._on_option_changed("general:border_size", 8)
        page.set_value("cursor:zoom_factor", 2.0)
        window._on_option_changed("decoration:rounding", 9)
        window._on_undo()
        window._on_undo()
        drafts = {unit: model.get_config() for unit, model in pages.items()}
        writers = {
            "input": MagicMock(side_effect=REAL_INPUT_SAVE),
            "source": MagicMock(side_effect=REAL_SOURCE_SAVE),
            "managed": MagicMock(side_effect=REAL_BINDINGS_SAVE),
            "visual": MagicMock(
                side_effect=REAL_PAIR_SAVE if window.pair_layout else REAL_VISUAL_SAVE
            ),
        }
        monkeypatch.setattr(backend, "persist_reviewed", writers["input"])
        monkeypatch.setattr(source_bindings, "persist_reviewed", writers["source"])
        monkeypatch.setattr(bindings, "persist_reviewed", writers["managed"])
        monkeypatch.setattr(
            transaction_publication if window.pair_layout else persistence,
            "publish_reviewed" if window.pair_layout else "persist_reviewed",
            writers["visual"],
        )
        first, second = ("input", other) if input_first else (other, "input")
        saved = set()
        for unit in (first, second, *(u for u in (*pages, "visual") if u not in (first, second))):
            before = history(window)
            if unit == "input":
                pending = review_input(window)
                assert "no_warps = true" in pending._input_review.diff
                assert 'kb_layout = "us,de"' in pending._input_review.diff
                pending._on_save_input(pending._input_save_button)
            elif unit == "source":
                reviewed(source)
                source._save_reviewed()
            elif unit == "managed":
                pending = review_bindings(window)
                pending._on_save_bindings(pending._bindings_save_button)
            else:
                window.save()
                pending = window._pending_page
                if window.pair_layout is not None:
                    wait_for(lambda: pending._pair_review is not None)
                pending._on_save_reviewed(pending._save_button)
            wait_for(lambda: not window._restore_in_progress)
            assert writers[unit].call_count == 1
            saved.add(unit)
            for name, model in pages.items():
                assert not model.locked and model.get_config() == drafts[name]
                assert model.is_dirty() == (name not in saved)
                if name not in saved:
                    assert model.baseline is baselines[name]
                else:
                    assert model.baseline.config == drafts[name]
            assert window.app_state.has_dirty() == ("visual" not in saved)
            if "visual" not in saved:
                assert {
                    key: (state.saved_value, state.saved_managed)
                    for key, state in window.app_state.options.items()
                } == visual_baseline
            assert history(window) == tuple(
                [
                    entry
                    for entry in stack
                    if not (
                        isinstance(entry, OptionChange)
                        if unit == "visual"
                        else isinstance(entry, SavedListSnapshot)
                        and entry.page_attr
                        == {
                            "input": "_input_page",
                            "source": "_source_bindings_page",
                            "managed": "_managed_bindings_page",
                        }[unit]
                    )
                ]
                for stack in before
            )
        assert not window.has_dirty() and history(window) == ([], [])

    def test_uncertain_combined_save_locks_both_views_not_other_units(self, window, monkeypatch):
        page = open_cursor(window)
        page.set_value("cursor:no_warps", True)
        open_input(window).set_value("input:left_handed", True)
        window._on_option_changed("general:border_size", 8)
        before = history(window)
        monkeypatch.setattr(backend, "persist_reviewed", MagicMock(return_value=object()))
        save_input(window)
        assert page.locked and page.is_dirty() and not window.editor_locked
        assert history(window) == before
        for destination, key in (("input", "input:left_handed"), ("cursor", "cursor:no_warps")):
            window.navigate(destination)
            assert not page._rows[key].row.get_sensitive()
            with pytest.raises(ValueError, match="locked|Input"):
                page.set_value(key, False)
        managed = open_bindings(window)
        managed.add_line("bind = SUPER, F9, killactive")
        assert managed.is_dirty() and not managed.locked
        window._on_option_changed("decoration:rounding", 9)
        assert window.app_state.has_dirty()

    def test_combined_writer_owns_close_and_blocks_both_view_edits(self, window, monkeypatch):
        page = open_cursor(window)
        page.set_value("cursor:no_warps", True)
        page.set_value("input:left_handed", True)
        pending = review_input(window)
        started, release = threading.Event(), threading.Event()

        def publish(review, proposed):
            started.set()
            release.wait(10)
            return REAL_INPUT_SAVE(review, proposed)

        monkeypatch.setattr(backend, "persist_reviewed", publish)
        pending._on_save_input(pending._input_save_button)
        try:
            wait_for(started.is_set)
            assert window._restore_owner == "save-input" and window._on_close_request()
            for key in ("input:left_handed", "cursor:no_warps"):
                with pytest.raises(ValueError):
                    page.set_value(key, False)
            assert not window.begin_source_bindings_save()
            window.finish_restore(False)
            assert window._restore_owner == "save-input" and window._restore_in_progress
        finally:
            release.set()
            wait_for(lambda: not window._restore_in_progress)
        assert not page.is_dirty() and not page.locked
