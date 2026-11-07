"""Isolated Input workflow. Real writers require explicit temporary E2E opt-in."""

import os
import threading
from dataclasses import replace
from itertools import permutations
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from gi.repository import Adw, GLib, Gtk

from hyprmod.core import bindings, persistence, source_bindings, transaction_publication
from hyprmod.core import input as backend
from hyprmod.core.undo import OptionChange, SavedListSnapshot
from hyprmod.ui.diff import ConfigDiffWidget
from hyprmod.window import HyprModWindow
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

REAL_INPUT_SAVE = backend.persist_reviewed


@pytest.fixture(autouse=True)
def forbid_input_writer(monkeypatch):
    monkeypatch.setattr(
        backend,
        "persist_reviewed",
        MagicMock(side_effect=AssertionError("Explicit temporary Input E2E required")),
    )


def open_input(window):
    page = window._input_page
    assert page is not None
    window.navigate("input")
    wait_for(lambda: page.baseline is not None or page.load_error is not None)
    assert page.baseline is not None, page.load_error
    return page


def review_input(window):
    window._on_save()
    pending = window._pending_page
    assert pending is not None

    def errors():
        return [
            w.get_text()
            for w in widgets(pending._input_box)
            if isinstance(w, Gtk.Label) and w.get_text().startswith("Cannot review")
        ]

    wait_for(lambda: pending._input_review is not None or errors())
    assert pending._input_review is not None, errors()
    assert pending._input_save_button is not None
    assert pending._input_save_button.get_label() == "Save Reviewed Input"
    review = pending._input_review
    diff = next(w for w in widgets(pending._input_box) if isinstance(w, ConfigDiffWidget))
    start, end = diff._buffer.get_bounds()
    assert diff._buffer.get_text(start, end, True) == review.diff.removesuffix("\n")
    return pending


def save_input(window):
    pending = review_input(window)
    pending._on_save_input(pending._input_save_button)
    wait_for(lambda: not window._restore_in_progress)


def history(window):
    return list(window._undo._undo_stack), list(window._undo._redo_stack)


class TestInputWorkflow:
    def test_devices_page_and_explicit_search_without_visual_schema_leak(self, window):
        page = open_input(window)
        assert "input" in window._sidebar._rows_by_id
        toolbar = window._page_stack.get_child_by_name("input")
        groups = [
            w for w in widgets(toolbar) if isinstance(w, Adw.PreferencesGroup) and w.get_title()
        ]
        assert len(groups) == 3
        device_keys = backend.INPUT_KEYS - backend.CURSOR_KEYS
        assert len({id(page._rows[key]) for key in device_keys}) == 14
        assert len({id(page._rows[key]) for key in backend.CURSOR_KEYS}) == 8
        device_widgets = list(widgets(toolbar))
        assert all(page._rows[key].row in device_widgets for key in device_keys)
        assert all(page._rows[key].row not in device_widgets for key in backend.CURSOR_KEYS)
        assert set(page._rows) == backend.INPUT_KEYS
        assert not backend.INPUT_KEYS.intersection(window.app_state.options)
        assert not backend.INPUT_KEYS.intersection(window.options_flat)
        results = window._search_page_builder.search("keyboard")
        assert any(result["_group_id"] == "input" for result in results)
        window._on_search_result_activate("input", "input:kb_layout")
        assert window._page_stack.get_visible_child_name() == "input"
        assert not page.is_dirty()

    def test_pending_unvisited_input_does_not_read_or_create(self, window, monkeypatch):
        observe = MagicMock(side_effect=AssertionError("Pending must not load Input"))
        monkeypatch.setattr(backend, "run_observe", observe)
        window._on_option_changed("general:border_size", 8)
        window.save()
        observe.assert_not_called()
        assert window._input_page.baseline is None
        assert not (Path(os.environ["XDG_CONFIG_HOME"]) / "hypr/attune-input.lua").exists()

    def test_real_repeated_save_reopen_preserves_other_files(self, window, monkeypatch):
        root = Path(os.environ["XDG_CONFIG_HOME"])
        state = Path(os.environ["XDG_STATE_HOME"])
        main = root / "hypr/hyprland.lua"
        main.write_text("-- authored defaults, never opened or changed\n")
        page = open_input(window)
        originals = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        old_state = {p: p.read_bytes() for p in state.rglob("*") if p.is_file()}
        calls = []

        def publish(review, proposed):
            assert threading.current_thread() is not threading.main_thread()
            assert not threading.current_thread().daemon
            assert review.baseline.config_root == str(root)
            calls.append(review)
            return REAL_INPUT_SAVE(review, proposed)

        monkeypatch.setattr(backend, "persist_reviewed", publish)
        ipc = MagicMock(side_effect=AssertionError("Input must not mutate compositor state"))
        monkeypatch.setattr(window.hypr, "keyword", ipc)
        for name in ("dispatch", "reload", "eval_lua", "keyword", "keyword_batch"):
            monkeypatch.setattr(f"hyprland_socket.{name}", ipc)
        page.set_keyboard_sources("us,de", ",nodeadkeys")
        page.set_value("input:kb_options", "caps:escape,custom:unknown")
        for key, value in {
            "input:left_handed": True,
            "input:natural_scroll": True,
            "input:sensitivity": -0.25,
            "input:scroll_factor": 1.2,
            "input:touchpad:tap-to-click": False,
            "input:touchpad:scroll_factor": 0.8,
        }.items():
            page.set_value(key, value)
        expected = page.get_config()
        save_input(window)
        assert not page.is_dirty() and not window.has_dirty()
        output = root / "hypr/attune-input.lua"
        assert backend.read_text(output.read_text()) == expected
        assert backend.RECORD in output.read_text()
        reopened = HyprModWindow(
            application=window.get_application(), pair_layout=window.pair_layout
        )
        try:
            assert open_input(reopened).get_config() == expected
        finally:
            if reopened._pending_page is not None:
                reopened._pending_page.cancel_review()
            reopened.destroy()
        page.set_keyboard_sources("gb", "")
        save_input(window)
        page.remove_override("input:left_handed")
        save_input(window)
        assert len(calls) == 3
        assert backend.run_observe(root, state) == page.baseline
        assert {p for p in root.rglob("*") if p.is_file()} == set(originals) | {output}
        for path, content in originals.items():
            assert path.read_bytes() == content
        assert {
            p
            for p in state.rglob("*")
            if p.is_file() and p.name != "input.lock" and "input-backups" not in p.parts
        } == set(old_state)
        for path, content in old_state.items():
            assert path.read_bytes() == content
        ipc.assert_not_called()

    def test_keyboard_pair_atomic_undo_redo_and_revert(self, window):
        page = open_input(window)
        before = page.get_config()
        page.set_keyboard_sources("us,de", ",nodeadkeys")
        after = page.get_config()
        assert len(window._undo._undo_stack) == 1
        entry = window._undo._undo_stack[-1]
        assert isinstance(entry, SavedListSnapshot) and entry.page_attr == "_input_page"
        window._on_undo()
        assert page.get_config() == before
        window._on_redo()
        assert page.get_config() == after
        change = next(page.iter_pending_changes())
        assert change.category == "Input" and change.navigate_to == "input"
        change.revert()
        assert page.get_config() == before
        assert not backend.INPUT_KEYS.intersection(window.app_state.options)

    @pytest.mark.parametrize("unit", ["input", "source", "managed", "visual"])
    def test_four_dirty_units_save_independently(self, window, tmp_path, monkeypatch, unit):
        source = window._source_bindings_page
        source_path = tmp_path / source_bindings.BASENAME
        copy_source(source_path)
        source.open_path(source_path)
        wait_for(lambda: source.baseline is not None)
        managed = open_bindings(window)
        page = open_input(window)
        initial_input = page.baseline
        initial_source = source.baseline
        initial_managed = managed.baseline
        page.set_value("input:left_handed", True)
        source.edit_binding(0, "Shift+Super+F12", "Source draft")
        managed.add_line("bind = SUPER, F9, killactive")
        window._on_option_changed("general:border_size", 8)
        window._on_option_changed("decoration:rounding", 9)
        window._on_undo()
        before = history(window)
        monkeypatch.setattr(backend, "persist_reviewed", REAL_INPUT_SAVE)
        monkeypatch.setattr(source_bindings, "persist_reviewed", REAL_SOURCE_SAVE)
        monkeypatch.setattr(bindings, "persist_reviewed", REAL_BINDINGS_SAVE)
        monkeypatch.setattr(persistence, "persist_reviewed", REAL_VISUAL_SAVE)
        monkeypatch.setattr(transaction_publication, "publish_reviewed", REAL_PAIR_SAVE)
        if unit == "input":
            save_input(window)
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
        assert page.is_dirty() == (unit != "input")
        assert source.is_dirty() == (unit != "source")
        assert managed.is_dirty() == (unit != "managed")
        assert window.app_state.has_dirty() == (unit != "visual")
        if unit != "input":
            assert page.baseline is initial_input
        if unit != "source":
            assert source.baseline is initial_source
        if unit != "managed":
            assert managed.baseline is initial_managed

        def belongs(entry):
            return (
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

        assert history(window) == tuple([e for e in stack if not belongs(e)] for stack in before)
        assert window.has_dirty()

    @pytest.mark.parametrize(
        "first,second", permutations(("input", "source", "managed", "visual"), 2)
    )
    def test_sequential_real_saves_refresh_sibling_review_context(
        self, window, monkeypatch, first, second
    ):
        root = Path(os.environ["XDG_CONFIG_HOME"])
        source_path = root / "hypr" / source_bindings.BASENAME
        copy_source(source_path)
        source = window._source_bindings_page
        source.open_path(source_path)
        wait_for(lambda: source.baseline is not None)
        managed = open_bindings(window)
        page = open_input(window)
        pages = {"input": page, "source": source, "managed": managed}
        baselines = {unit: model.baseline for unit, model in pages.items()}
        visual_baseline = {
            key: (state.saved_value, state.saved_managed)
            for key, state in window.app_state.options.items()
        }
        pair = window.pair_layout
        ipc = MagicMock(side_effect=AssertionError("No compositor mutation in isolated saves"))
        for name in ("dispatch", "reload", "eval_lua", "keyword", "keyword_batch"):
            monkeypatch.setattr(f"hyprland_socket.{name}", ipc)
        page.set_keyboard_sources("us,de", ",nodeadkeys")
        source.edit_binding(0, "Shift+Super+F12", "Sequential source draft")
        managed.add_line("bind = SUPER, F9, killactive")
        window._on_option_changed("general:border_size", 8)
        window._on_option_changed("decoration:rounding", 9)
        window._on_undo()
        drafts = {unit: model.get_config() for unit, model in pages.items()}
        writers = {
            "input": MagicMock(side_effect=REAL_INPUT_SAVE),
            "source": MagicMock(side_effect=REAL_SOURCE_SAVE),
            "managed": MagicMock(side_effect=REAL_BINDINGS_SAVE),
            "visual": MagicMock(side_effect=REAL_PAIR_SAVE if pair else REAL_VISUAL_SAVE),
        }
        monkeypatch.setattr(backend, "persist_reviewed", writers["input"])
        monkeypatch.setattr(source_bindings, "persist_reviewed", writers["source"])
        monkeypatch.setattr(bindings, "persist_reviewed", writers["managed"])
        monkeypatch.setattr(
            transaction_publication if pair else persistence,
            "publish_reviewed" if pair else "persist_reviewed",
            writers["visual"],
        )
        saved = set()
        order = (
            first,
            second,
            *(unit for unit in (*pages, "visual") if unit not in (first, second)),
        )
        for unit in order:
            before = history(window)
            pending = window._pending_page
            if unit == "input":
                pending = review_input(window)
                review = pending._input_review
            elif unit == "managed":
                pending = review_bindings(window)
                review = pending._bindings_review
            elif unit == "source":
                review = reviewed(source)
            else:
                window.save()
                pending = window._pending_page
                if pair is not None:
                    wait_for(lambda: pending._pair_review is not None)
                review = pending._pair_review if pair else pending._reviewed
            assert review is not None
            if unit in pages:
                original = baselines[unit]
                assert pages[unit].baseline is original
                same_source = {
                    "input": backend.same_source,
                    "source": source_bindings.same_source,
                    "managed": bindings.same_source,
                }[unit]
                assert same_source(original, review.baseline)
                if saved:
                    assert review.baseline != original
                    assert review.baseline.protected != original.protected
                if unit == "input":
                    pending._on_save_input(pending._input_save_button)
                elif unit == "managed":
                    pending._on_save_bindings(pending._bindings_save_button)
                else:
                    source._save_reviewed()
            else:
                pending._on_save_reviewed(pending._save_button)
            wait_for(lambda: not window._restore_in_progress)
            assert writers[unit].call_count == 1
            assert writers[unit].call_args.args[0] is review
            saved.add(unit)
            for name, model in pages.items():
                assert not model.locked
                assert model.get_config() == drafts[name]
                assert model.is_dirty() == (name not in saved)
                if name not in saved:
                    assert model.baseline is baselines[name]
                else:
                    assert model.baseline.config == drafts[name]
                    assert Path(model.baseline.lexical_path).read_text() == model.baseline.text
            assert window.app_state.has_dirty() == ("visual" not in saved)
            if "visual" not in saved:
                assert window.pair_layout is pair
                assert {
                    key: (state.saved_value, state.saved_managed)
                    for key, state in window.app_state.options.items()
                } == visual_baseline
            elif pair is not None:
                assert dict(window.pair_layout.appearance.values)["general:border_size"] == "8"
            else:
                assert "8" == window.saved_values["general:border_size"]
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
        ipc.assert_not_called()

    @pytest.mark.parametrize("failure", ["exception", "type", "wrong-context", "wrong-goal"])
    def test_uncertain_result_locks_input_only(self, window, monkeypatch, failure):
        page = open_input(window)
        page.set_value("input:left_handed", True)
        window._on_option_changed("general:border_size", 8)
        before = history(window)

        def publish(review, proposed):
            if failure == "exception":
                raise RuntimeError("delegated failure")
            if failure == "type":
                return object()
            result = REAL_INPUT_SAVE(review, proposed)
            fresh = result.baseline
            if fresh is None:
                raise ValueError(result.error)
            if failure == "wrong-context":
                object.__setattr__(fresh, "config_root", str(Path(fresh.config_root) / "other"))
            else:
                object.__setattr__(fresh, "config", backend.InputConfig())
            return result

        monkeypatch.setattr(backend, "persist_reviewed", publish)
        save_input(window)
        assert page.locked and page.is_dirty()
        assert not window.editor_locked
        assert window.app_state.has_dirty()
        assert history(window) == before
        window._on_undo()
        assert not window.app_state.has_dirty()
        window._on_undo()
        assert page.is_dirty() and history(window)[0] == before[0][:-1]

    @pytest.mark.parametrize("unavailable", [False, True])
    def test_foreign_input_does_not_block_other_saves(
        self, window, monkeypatch, tmp_path, unavailable
    ):
        output = Path(os.environ["XDG_CONFIG_HOME"]) / "hypr/attune-input.lua"
        output.write_text("-- foreign, must remain untouched\n")
        if unavailable:
            monkeypatch.setattr(
                backend, "run_observe", MagicMock(side_effect=OSError("Input route unavailable"))
            )
        page = window._input_page
        window.show_page("input")
        wait_for(lambda: page.locked)
        assert page.load_error and not window.editor_locked
        managed = open_bindings(window)
        managed.add_line("bind = SUPER, F9, killactive")
        monkeypatch.setattr(bindings, "persist_reviewed", REAL_BINDINGS_SAVE)
        pending = review_bindings(window)
        pending._on_save_bindings(pending._bindings_save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert not managed.is_dirty()
        window._on_option_changed("general:border_size", 8)
        monkeypatch.setattr(persistence, "persist_reviewed", REAL_VISUAL_SAVE)
        monkeypatch.setattr(transaction_publication, "publish_reviewed", REAL_PAIR_SAVE)
        window.save()
        if window.pair_layout is not None:
            wait_for(lambda: pending._pair_review is not None)
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert not window.app_state.has_dirty()
        source = window._source_bindings_page
        path = tmp_path / source_bindings.BASENAME
        copy_source(path)
        source.open_path(path)
        wait_for(lambda: source.baseline is not None)
        source.edit_binding(0, "Shift+Super+F12", "Independent source")
        monkeypatch.setattr(source_bindings, "persist_reviewed", REAL_SOURCE_SAVE)
        reviewed(source)
        source._save_reviewed()
        wait_for(lambda: not window._restore_in_progress)
        assert not source.is_dirty()
        assert page.locked and not window.editor_locked
        assert output.read_text() == "-- foreign, must remain untouched\n"

    def test_close_overlap_and_refused_backup_finish_cannot_release_input(
        self, window, monkeypatch
    ):
        page = open_input(window)
        page.set_value("input:left_handed", True)
        started, release = threading.Event(), threading.Event()

        def publish(review, proposed):
            started.set()
            release.wait(10)
            return REAL_INPUT_SAVE(review, proposed)

        monkeypatch.setattr(backend, "persist_reviewed", publish)
        pending = review_input(window)
        pending._on_save_input(pending._input_save_button)
        try:
            wait_for(started.is_set)
            assert window._restore_owner == "save-input"
            assert window._on_close_request()
            with pytest.raises(ValueError):
                window.begin_restore()
            window.finish_restore(False)
            assert window._restore_owner == "save-input" and window._restore_in_progress
            assert not window.begin_source_bindings_save()
        finally:
            release.set()
            wait_for(lambda: not window._restore_in_progress)
        assert not page.is_dirty()

    def test_stale_review_consumed_and_double_click_is_one_shot(self, window, monkeypatch):
        page = open_input(window)
        page.set_value("input:left_handed", True)
        pending = review_input(window)
        old = pending._input_review
        page.set_value("input:sensitivity", 0.2)
        assert pending._input_review is None
        assert not pending._input_save_button.get_sensitive()
        window.save_input_reviewed(old, old.proposed)
        cast(MagicMock, backend.persist_reviewed).assert_not_called()
        publisher = MagicMock(side_effect=REAL_INPUT_SAVE)
        monkeypatch.setattr(backend, "persist_reviewed", publisher)
        pending = review_input(window)
        pending._on_save_input(pending._input_save_button)
        pending._on_save_input(pending._input_save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert publisher.call_count == 1 and not page.is_dirty()

    def test_monitor_preview_refusal_consumes_review_before_permission(self, window, monkeypatch):
        page = open_input(window)
        page.set_value("input:left_handed", True)
        pending = review_input(window)
        monkeypatch.setattr(window._monitors_page, "is_confirm_pending", lambda: True)
        pending._on_save_input(pending._input_save_button)
        assert pending._input_review is None and pending._input_save_request is None
        assert not window._restore_in_progress and page.is_dirty() and not page.locked
        pending._on_save_input(pending._input_save_button)
        cast(MagicMock, backend.persist_reviewed).assert_not_called()

    def test_cancelled_late_review_cannot_enable_save(self, window, monkeypatch):
        page = open_input(window)
        page.set_value("input:left_handed", True)
        real_prepare = backend.run_prepare_review
        started, release = threading.Event(), threading.Event()

        def prepare(baseline, proposed, **kwargs):
            started.set()
            release.wait(10)
            return real_prepare(baseline, proposed)

        monkeypatch.setattr(backend, "run_prepare_review", prepare)
        window.save()
        pending = window._pending_page
        try:
            wait_for(started.is_set)
            pending.cancel_review()
        finally:
            release.set()
            wait_for(lambda: pending._input_read_cancel is None)
        assert pending._input_review is None
        assert not pending._input_save_button.get_sensitive()
        cast(MagicMock, backend.persist_reviewed).assert_not_called()

    def test_loading_instructions_are_literal_and_do_not_create_output(self, window):
        labels = [
            w
            for w in widgets(window._page_stack.get_child_by_name("settings"))
            if isinstance(w, Gtk.Label) and "Input has a separate fixed output" in w.get_text()
        ]
        assert len(labels) == 1
        label = labels[0]
        path = Path(os.environ["XDG_CONFIG_HOME"]) / "hypr/attune-input.lua"
        assert str(path) in label.get_text() and "after this file exists" in label.get_text()
        assert not label.get_use_markup() and not path.exists()

    @pytest.mark.parametrize("failure", ["setup", "start"])
    def test_predelegation_failure_releases_owner_without_locking(
        self, window, monkeypatch, failure
    ):
        page = open_input(window)
        page.set_value("input:left_handed", True)
        pending = review_input(window)
        original = window._set_editor_sensitive

        def sensitivity(sensitive):
            if not sensitive:
                raise RuntimeError("setup refused")
            original(sensitive)

        with monkeypatch.context() as attempt:
            if failure == "setup":
                attempt.setattr(window, "_set_editor_sensitive", sensitivity)
            else:
                attempt.setattr(
                    threading.Thread, "start", MagicMock(side_effect=RuntimeError("start"))
                )
            pending._on_save_input(pending._input_save_button)
        assert not window._restore_in_progress and window._restore_owner is None
        assert page.is_dirty() and not page.locked
        assert not window._source_bindings_page._saving
        cast(MagicMock, backend.persist_reviewed).assert_not_called()

    def test_start_exception_after_worker_entry_retains_authority(self, window, monkeypatch):
        page = open_input(window)
        page.set_value("input:left_handed", True)
        pending = review_input(window)
        started, release = threading.Event(), threading.Event()
        original_start = threading.Thread.start

        def publish(review, proposed):
            started.set()
            release.wait(10)
            return REAL_INPUT_SAVE(review, proposed)

        def start(thread):
            original_start(thread)
            assert started.wait(5)
            raise RuntimeError("start raised after entry")

        monkeypatch.setattr(backend, "persist_reviewed", publish)
        try:
            with monkeypatch.context() as attempt:
                attempt.setattr(threading.Thread, "start", start)
                pending._on_save_input(pending._input_save_button)
            assert window._restore_owner == "save-input" and window._restore_in_progress
            assert window._on_close_request()
        finally:
            release.set()
            wait_for(lambda: not window._restore_in_progress)
        assert not page.is_dirty() and not page.locked

    def test_completion_notification_failure_and_duplicate_do_not_release_new_owner(
        self, window, monkeypatch
    ):
        page = open_input(window)
        page.set_value("input:left_handed", True)
        pending = review_input(window)
        completions = []
        original = GLib.idle_add

        def capture(callback, *args, **kwargs):
            if callback.__name__ == "finish":
                completions.append((callback, args))
                return 1
            return original(callback, *args, **kwargs)

        monkeypatch.setattr(GLib, "idle_add", capture)
        monkeypatch.setattr(backend, "persist_reviewed", MagicMock(return_value=object()))
        pending._on_save_input(pending._input_save_button)
        wait_for(lambda: bool(completions))
        callback, args = completions[0]
        with monkeypatch.context() as notifications:
            notifications.setattr(
                window, "show_toast", MagicMock(side_effect=RuntimeError("notification failed"))
            )
            with pytest.raises(RuntimeError, match="notification failed"):
                callback(*args)
        assert page.locked and page.is_dirty() and not window._restore_in_progress
        window._do_discard()
        assert page.is_dirty() and history(window)[0]
        window._restore_owner = "source-bindings"
        window._restore_in_progress = True
        try:
            callback(*args)
            assert window._restore_owner == "source-bindings" and window._restore_in_progress
        finally:
            window.finish_source_bindings_save()

    def test_protected_retarget_refuses_without_false_saved(self, window, monkeypatch):
        root = Path(os.environ["XDG_CONFIG_HOME"])
        main = root / "hypr/hyprland.lua"
        main.write_text("-- protected authored Lua\n")
        page = open_input(window)
        page.set_value("input:left_handed", True)
        baseline = page.baseline
        before = history(window)
        pending = review_input(window)
        output = root / "hypr/attune-input.lua"
        output.symlink_to(main)
        monkeypatch.setattr(backend, "persist_reviewed", REAL_INPUT_SAVE)
        pending._on_save_input(pending._input_save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert page.is_dirty() and page.baseline is baseline and not window.editor_locked
        assert history(window) == before
        assert output.is_symlink() and main.read_text() == "-- protected authored Lua\n"

    def test_noop_adopts_input_only_and_preserves_visual_dirty(self, window, monkeypatch):
        page = open_input(window)
        page.set_value("input:left_handed", True)
        monkeypatch.setattr(backend, "persist_reviewed", REAL_INPUT_SAVE)
        save_input(window)
        window._on_option_changed("general:border_size", 8)
        window.save()
        pending = window._pending_page
        before = history(window)
        review = backend.prepare_review(page.baseline, page.get_config())
        pending._input_review = review
        pending._input_source = page.baseline
        publisher = MagicMock(side_effect=REAL_INPUT_SAVE)
        monkeypatch.setattr(backend, "persist_reviewed", publisher)
        pending._on_save_input(pending._input_save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert publisher.call_count == 1
        assert not page.locked and not page.is_dirty() and window.app_state.has_dirty()
        assert history(window) == before

    def test_result_flags_must_be_exact_booleans(self, window, monkeypatch):
        page = open_input(window)
        page.set_value("input:left_handed", True)

        def publish(review, proposed):
            result = REAL_INPUT_SAVE(review, proposed)
            object.__setattr__(result, "may_have_written", 1)
            return result

        monkeypatch.setattr(backend, "persist_reviewed", publish)
        save_input(window)
        assert page.locked and page.is_dirty() and not window.editor_locked

    @pytest.mark.parametrize("invalid", ["type", "config", "context"])
    def test_invalid_review_type_and_context_cannot_enable_save(self, window, monkeypatch, invalid):
        page = open_input(window)
        page.set_value("input:left_handed", True)
        real_prepare = backend.run_prepare_review

        def wrong(baseline, proposed, **kwargs):
            review = real_prepare(baseline, proposed, **kwargs)
            if invalid == "type":
                return object()
            if invalid == "config":
                object.__setattr__(review, "proposed", backend.InputConfig())
            else:
                changed = replace(review.baseline)
                object.__setattr__(changed, "config_root", str(Path(changed.config_root) / "other"))
                object.__setattr__(review, "baseline", changed)
            return review

        monkeypatch.setattr(backend, "run_prepare_review", wrong)
        window.save()
        pending = window._pending_page
        wait_for(lambda: pending._input_read_cancel is None)
        assert pending._input_review is None and not pending._input_save_button.get_sensitive()
        cast(MagicMock, backend.persist_reviewed).assert_not_called()
