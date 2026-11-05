"""Opt-in isolated widgets; real publishers are enabled only for temporary E2E tests."""

import os
import threading
import time
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from gi.repository import Adw, Gio, GLib, Gtk
from hyprland_socket import HyprlandError

from hyprmod.core import (
    bindings,
    editor_layout,
    persistence,
    source_bindings,
    transaction_publication,
)
from hyprmod.core import input as input_config
from hyprmod.core.undo import OptionChange, SavedListSnapshot
from hyprmod.pages.scope_recovery import ScopeRecoveryPage
from hyprmod.ui.diff import ConfigDiffWidget
from hyprmod.window import HyprModWindow
from tests.test_scoped_review import evidence as evidence
from tests.test_transaction_store import plan as plan

pytestmark = pytest.mark.skipif(
    os.environ.get("ATTUNE_GUI_SMOKE") != "1" or os.environ.get("GDK_BACKEND") != "broadway",
    reason="opt-in isolated Broadway widgets",
)

REAL_BINDINGS_SAVE = bindings.persist_reviewed
REAL_VISUAL_SAVE = persistence.persist_reviewed
REAL_PAIR_SAVE = transaction_publication.publish_reviewed


def wait_for(predicate):
    deadline = time.monotonic() + 15
    context = GLib.MainContext.default()
    while not predicate() and time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.005)
    assert predicate()


def widgets(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from widgets(child)
        child = child.get_next_sibling()


@pytest.fixture(params=["legacy", "pair"])
def window(request, monkeypatch):
    pair = None
    if request.param == "pair":
        reviewed = request.getfixturevalue("plan")
        monkeypatch.setenv("XDG_CONFIG_HOME", reviewed.evidence.config_root)
        monkeypatch.setenv("XDG_STATE_HOME", reviewed.evidence.state_root)
        pair = editor_layout.inspect_entry(
            Path(reviewed.evidence.config_root), Path(reviewed.evidence.state_root)
        ).pair
        assert pair is not None
    root = Path(os.environ["XDG_CONFIG_HOME"])
    (root / "hypr").mkdir(exist_ok=True)
    Path(os.environ["XDG_STATE_HOME"]).parent.mkdir(parents=True, exist_ok=True)

    def offline():
        raise HyprlandError("IPC disabled")

    monkeypatch.setattr("hyprland_socket.get_version", offline)
    monkeypatch.setattr(ScopeRecoveryPage, "ensure_loaded", lambda self: None)
    for module, name in (
        (input_config, "persist_reviewed"),
        (bindings, "persist_reviewed"),
        (source_bindings, "persist_reviewed"),
        (persistence, "persist_reviewed"),
        (transaction_publication, "publish_reviewed"),
    ):
        monkeypatch.setattr(
            module, name, MagicMock(side_effect=AssertionError("Explicit temporary E2E required"))
        )
    application = Adw.Application(
        application_id=f"io.github.jdawson.Attune.BindingsTest{uuid4().hex}",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    application.register(None)
    widget = HyprModWindow(application=application, pair_layout=pair)
    yield widget
    wait_for(lambda: not widget._restore_in_progress)
    if widget._pending_page is not None:
        widget._pending_page.cancel_review()
    widget.destroy()
    application.quit()


def open_bindings(window):
    page = window._managed_bindings_page
    assert page is not None
    assert page.baseline is None
    window.show_page("binds")
    wait_for(lambda: page.baseline is not None or page.load_error is not None)
    assert page.baseline is not None, page.load_error
    return page


def review_bindings(window):
    window.save()
    pending = window._pending_page
    assert pending is not None
    wait_for(lambda: pending._bindings_review is not None)
    assert pending._bindings_save_button is not None
    assert pending._bindings_save_button.get_label() == "Save Reviewed Keybindings"
    assert pending._save_button is not None
    assert pending._save_button.get_label() == "Save Reviewed Appearance / Displays"
    review = pending._bindings_review
    assert review is not None
    diff = next(w for w in widgets(pending._bindings_box) if isinstance(w, ConfigDiffWidget))
    start, end = diff._buffer.get_bounds()
    assert diff._buffer.get_text(start, end, True) == review.diff.removesuffix("\n")
    metadata = [w.get_text() for w in widgets(pending._bindings_box) if isinstance(w, Gtk.Label)]
    assert any(
        review.baseline.lexical_path in text and review.review_hash in text for text in metadata
    )
    return pending


def save_bindings(window):
    pending = review_bindings(window)
    pending._on_save_bindings(pending._bindings_save_button)
    wait_for(lambda: not window._restore_in_progress)


class TestManagedKeybindingsWorkflow:
    def test_lazy_visual_review_does_not_observe_bindings(self, window, monkeypatch):
        observe = MagicMock(side_effect=AssertionError("Unvisited bindings must not load"))
        monkeypatch.setattr(bindings, "run_observe", observe)
        window._on_option_changed("general:border_size", 8)
        window.save()
        pending = window._pending_page
        assert pending is not None
        if window.pair_layout is not None:
            wait_for(lambda: pending._pair_review is not None)
        else:
            assert pending._reviewed is not None
        observe.assert_not_called()
        assert window._managed_bindings_page is not None
        assert window._managed_bindings_page.baseline is None

    def test_add_edit_delete_repeated_real_saves_and_reopen(self, window, monkeypatch):
        root = Path(os.environ["XDG_CONFIG_HOME"])
        main = root / "hypr/hyprland.lua"
        main.write_text("-- user defaults, never edited\n")
        page = open_bindings(window)
        originals = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
        state = Path(os.environ["XDG_STATE_HOME"])
        state_originals = {path: path.read_bytes() for path in state.rglob("*") if path.is_file()}
        calls = []

        def publish(review, proposed):
            assert threading.current_thread() is not threading.main_thread()
            assert not threading.current_thread().daemon
            assert review.baseline.lexical_path == str(root / "hypr/attune-bindings.lua")
            calls.append(review)
            return REAL_BINDINGS_SAVE(review, proposed)

        monkeypatch.setattr(bindings, "persist_reviewed", publish)
        keyword = MagicMock(side_effect=AssertionError("No binding live keyword"))
        command = MagicMock(side_effect=AssertionError("No dispatch, unbind or reload"))
        monkeypatch.setattr(window.hypr, "keyword", keyword)
        for name in ("dispatch", "reload", "eval_lua", "keyword", "keyword_batch"):
            monkeypatch.setattr(f"hyprland_socket.{name}", command)
        first = "bind = SUPER, F9, exec, printf '\"literal\" $HOME; <&>\\n'"
        edited = 'bind = SHIFT SUPER, F10, exec, sh -c \'printf "%s" "a,b; $HOME"\''
        page.add_line(first)
        page.edit_line(0, edited)
        page.add_line("bind = SUPER, F11, exec, true")
        page.delete_at(1)
        assert page.get_config().lines == (edited,)
        assert window.has_dirty()
        assert window._sidebar._rows_by_id["binds"]._badge.get_text() == "1"
        save_bindings(window)
        assert not page.is_dirty() and not window.has_dirty()
        output = root / "hypr/attune-bindings.lua"
        assert bindings.read_text(output.read_text()).lines == (edited,)
        reopened_window = HyprModWindow(
            application=window.get_application(), pair_layout=window.pair_layout
        )
        try:
            reopened_page = open_bindings(reopened_window)
            assert reopened_page.get_config().lines == (edited,)
            assert not reopened_window.has_dirty()
        finally:
            if reopened_window._pending_page is not None:
                reopened_window._pending_page.cancel_review()
            reopened_window.destroy()
        page.edit_line(0, first)
        save_bindings(window)
        assert bindings.read_text(output.read_text()).lines == (first,)
        page.delete_at(0)
        save_bindings(window)
        assert bindings.read_text(output.read_text()) == bindings.BindingsConfig()
        reopened = bindings.run_observe(root, Path(os.environ["XDG_STATE_HOME"]))
        assert reopened == page.baseline
        assert len(calls) == 3
        for path, content in originals.items():
            assert path.read_bytes() == content
        assert {path for path in root.rglob("*") if path.is_file()} == set(originals) | {output}
        for path, content in state_originals.items():
            assert path.read_bytes() == content
        assert {
            path
            for path in state.rglob("*")
            if path.is_file()
            and path.name != "bindings.lock"
            and "bindings-backups" not in path.parts
        } == set(state_originals)
        keyword.assert_not_called()
        command.assert_not_called()

    @pytest.mark.parametrize("first_unit", ["visual", "bindings"])
    def test_mixed_drafts_keep_other_unit_dirty_and_undoable(self, window, monkeypatch, first_unit):
        page = open_bindings(window)
        monkeypatch.setattr(bindings, "persist_reviewed", REAL_BINDINGS_SAVE)
        monkeypatch.setattr(persistence, "persist_reviewed", REAL_VISUAL_SAVE)
        monkeypatch.setattr(transaction_publication, "publish_reviewed", REAL_PAIR_SAVE)
        page.add_line("bind = SUPER, F9, exec, true")
        window._on_option_changed("general:border_size", 8)
        if first_unit == "bindings":
            save_bindings(window)
            assert not page.is_dirty()
            assert window.app_state.has_dirty()
            assert isinstance(window._undo.peek(), OptionChange)
        else:
            window.save()
            pending = window._pending_page
            assert pending is not None
            if window.pair_layout is not None:
                wait_for(lambda: pending._pair_review is not None)
            else:
                assert pending._reviewed is not None
            pending._on_save_reviewed(pending._save_button)
            wait_for(lambda: not window._restore_in_progress)
            assert not window.app_state.has_dirty()
            assert page.is_dirty()
            assert isinstance(window._undo.peek(), SavedListSnapshot)
            assert window._banner._label.get_text() != "Changes saved to disk"
        assert window.has_dirty()
        window._on_undo()
        assert not window.has_dirty()

    @pytest.mark.parametrize(
        "outcome", ["refused", "uncertain", "invalid", "exception", "wrong-baseline"]
    )
    def test_failure_retains_both_drafts_and_locks_only_bindings_when_uncertain(
        self, window, monkeypatch, outcome
    ):
        page = open_bindings(window)
        page.add_line("bind = SUPER, F9, exec, true")
        window._on_option_changed("general:border_size", 8)
        result = (
            bindings.BindingsSaveResult("failed", None, None, outcome == "uncertain", "refused")
            if outcome in {"refused", "uncertain"}
            else object()
        )
        publisher = MagicMock(return_value=result)
        if outcome == "wrong-baseline":
            publisher.return_value = bindings.BindingsSaveResult(
                "no-op", page.baseline, None, False, None
            )
        if outcome == "exception":
            publisher.side_effect = ValueError("delegated exception")
        monkeypatch.setattr(bindings, "persist_reviewed", publisher)
        save_bindings(window)
        assert page.is_dirty() and window.app_state.has_dirty()
        assert page.locked == (outcome != "refused")
        assert not window.editor_locked
        assert window._restore_owner is None
        if page.locked:
            entry = window._undo.peek()
            window._on_undo()
            assert not window.app_state.has_dirty()
            binding_entry = window._undo.peek()
            window._on_undo()
            assert window._undo.peek() is binding_entry
            assert page.is_dirty()
            window._on_redo()
            assert window._undo.peek() is entry
            assert window.app_state.has_dirty()

    def test_writer_exclusion_close_veto_and_consumed_review(self, window, monkeypatch):
        page = open_bindings(window)
        page.add_line("bind = SUPER, F9, exec, true")
        entered = threading.Event()
        release = threading.Event()

        def publish(review, proposed):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("test did not release writer")
            return bindings.BindingsSaveResult("failed", None, None, False, "test refusal")

        publisher = MagicMock(side_effect=publish)
        monkeypatch.setattr(bindings, "persist_reviewed", publisher)
        pending = review_bindings(window)
        try:
            pending._on_save_bindings(pending._bindings_save_button)
            assert entered.wait(3)
            assert window._restore_owner == "save-bindings"
            assert window._on_close_request()
            window.finish_restore(False)
            window.finish_scope_restore(False)
            assert window._restore_owner == "save-bindings"
            with pytest.raises(ValueError):
                window.scope_restore_permission()
            with pytest.raises(ValueError):
                window.begin_restore()
            with pytest.raises(ValueError):
                page.add_line("bind = SUPER, F10, exec, false")
            assert len(page.get_config().lines) == 1
            pending._on_save_bindings(pending._bindings_save_button)
            assert publisher.call_count == 1
        finally:
            release.set()
        wait_for(lambda: not window._restore_in_progress)
        assert page.is_dirty() and not page.locked

    def test_thread_start_failure_releases_without_uncertainty(self, window, monkeypatch):
        page = open_bindings(window)
        page.add_line("bind = SUPER, F9, exec, true")
        pending = review_bindings(window)
        monkeypatch.setattr(
            threading.Thread, "start", MagicMock(side_effect=RuntimeError("cannot start"))
        )
        pending._on_save_bindings(pending._bindings_save_button)
        assert not window._restore_in_progress
        assert window._restore_owner is None
        assert page.is_dirty() and not page.locked
        cast(MagicMock, bindings.persist_reviewed).assert_not_called()

    def test_completion_failure_and_duplicate_cannot_strand_or_release_new_owner(
        self, window, monkeypatch
    ):
        page = open_bindings(window)
        page.add_line("bind = SUPER, F9, exec, true")
        pending = review_bindings(window)
        completions = []
        idle_add = GLib.idle_add

        def capture(callback, *args, **kwargs):
            if callback.__name__ == "finish":
                completions.append((callback, args))
                return 1
            return idle_add(callback, *args, **kwargs)

        monkeypatch.setattr(GLib, "idle_add", capture)
        monkeypatch.setattr(bindings, "persist_reviewed", MagicMock(return_value=object()))
        pending._on_save_bindings(pending._bindings_save_button)
        wait_for(lambda: bool(completions))
        callback, args = completions[0]
        with monkeypatch.context() as notifications:
            notifications.setattr(
                window, "show_toast", MagicMock(side_effect=RuntimeError("notification failed"))
            )
            with pytest.raises(RuntimeError, match="notification failed"):
                callback(*args)
        assert page.locked and page.is_dirty()
        assert not window._restore_in_progress and not window.editor_locked
        window._do_discard()
        window.begin_scope_restore()
        callback(*args)
        assert window._restore_owner == "scope" and window._restore_in_progress
        window.finish_scope_restore(False)

    def test_setup_failure_retains_draft_without_uncertainty(self, window, monkeypatch):
        page = open_bindings(window)
        page.add_line("bind = SUPER, F9, exec, true")
        pending = review_bindings(window)
        original = window._set_editor_sensitive

        def sensitivity(sensitive):
            if not sensitive:
                raise RuntimeError("setup failed")
            original(sensitive)

        monkeypatch.setattr(window, "_set_editor_sensitive", sensitivity)
        pending._on_save_bindings(pending._bindings_save_button)
        assert page.is_dirty() and not page.locked
        assert not window._restore_in_progress
        cast(MagicMock, bindings.persist_reviewed).assert_not_called()

    def test_permission_refusal_consumes_review(self, window, monkeypatch):
        page = open_bindings(window)
        page.add_line("bind = SUPER, F9, exec, true")
        pending = review_bindings(window)
        review = pending._bindings_review
        assert review is not None
        monitors = window._monitors_page
        assert monitors is not None
        monkeypatch.setattr(monitors, "is_confirm_pending", lambda: True)
        pending._on_save_bindings(pending._bindings_save_button)
        assert pending._bindings_review is None
        assert not window._restore_in_progress
        monkeypatch.setattr(monitors, "is_confirm_pending", lambda: False)
        window.save_bindings_reviewed(review, review.proposed)
        cast(MagicMock, bindings.persist_reviewed).assert_not_called()
        assert page.is_dirty()

    def test_review_worker_discards_stale_generation_and_keeps_one_read_slot(
        self, window, monkeypatch
    ):
        page = open_bindings(window)
        entered = threading.Event()
        release = threading.Event()
        active = 0
        maximum = 0

        def prepare(baseline, proposed, **kwargs):
            nonlocal active, maximum
            assert threading.current_thread() is not threading.main_thread()
            active += 1
            maximum = max(maximum, active)
            entered.set()
            try:
                if not release.wait(10):
                    raise TimeoutError("test did not release review")
                return bindings.prepare_review(baseline, proposed)
            finally:
                active -= 1

        monkeypatch.setattr(bindings, "run_prepare_review", prepare)
        page.add_line("bind = SUPER, F9, exec, true")
        window.save()
        pending = window._pending_page
        assert pending is not None
        try:
            assert entered.wait(3)
            cancel = pending._bindings_read_cancel
            page.edit_line(0, "bind = SUPER, F9, exec, false")
            pending.refresh()
            assert pending._bindings_read_cancel is cancel
            assert pending._bindings_review is None
        finally:
            release.set()
        wait_for(lambda: pending._bindings_review is not None)
        assert pending._bindings_review is not None
        assert pending._bindings_review.proposed == page.get_config()
        assert maximum == 1

    def test_stale_baseline_refuses_without_losing_drafts(self, window, monkeypatch):
        page = open_bindings(window)
        page.add_line("bind = SUPER, F9, exec, true")
        window._on_option_changed("general:border_size", 8)
        pending = review_bindings(window)
        baseline = page.baseline
        assert baseline is not None
        output = Path(baseline.lexical_path)
        output.write_text("-- external hand-authored file\n")
        monkeypatch.setattr(bindings, "persist_reviewed", REAL_BINDINGS_SAVE)
        pending._on_save_bindings(pending._bindings_save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert page.is_dirty() and window.app_state.has_dirty()
        assert output.read_text() == "-- external hand-authored file\n"
        assert not page.locked and not window.editor_locked

    def test_foreign_bindings_refusal_does_not_block_visual_save(self, window, monkeypatch):
        output = Path(os.environ["XDG_CONFIG_HOME"]) / "hypr/attune-bindings.lua"
        output.write_text("-- foreign hand-authored file\n")
        page = window._managed_bindings_page
        assert page is not None
        window.show_page("binds")
        wait_for(lambda: page.load_error is not None)
        assert page.baseline is None
        window._on_option_changed("general:border_size", 8)
        monkeypatch.setattr(persistence, "persist_reviewed", REAL_VISUAL_SAVE)
        monkeypatch.setattr(transaction_publication, "publish_reviewed", REAL_PAIR_SAVE)
        window.save()
        pending = window._pending_page
        assert pending is not None
        if window.pair_layout is not None:
            wait_for(lambda: pending._pair_review is not None)
        else:
            assert pending._reviewed is not None
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert not window.app_state.has_dirty()
        assert output.read_text() == "-- foreign hand-authored file\n"
        assert not window.editor_locked

    def test_settings_paths_are_literal(self, window):
        settings = window._page_stack.get_child_by_name("settings")
        labels = [widget for widget in widgets(settings) if isinstance(widget, Gtk.Label)]
        assert any("attune-bindings.lua" in label.get_text() for label in labels)
        assert all(
            not label.get_use_markup()
            for label in labels
            if "attune-bindings.lua" in label.get_text()
        )
