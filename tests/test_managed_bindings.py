"""Managed binding drafts never publish or change runtime state."""

import os
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from gi.repository import GLib
from hyprland_socket import MOD_BITS, Bind

from hyprmod.core import bindings
from hyprmod.core.ownership import SavedList
from hyprmod.core.undo import SavedListSnapshot
from hyprmod.pages.managed_bindings import ManagedBindingsPage

Q = "bind = SUPER, Q, killactive"
T = "bind = SUPER, T, exec, kitty"


@pytest.fixture(autouse=True)
def no_binding_writers(monkeypatch):
    for name in ("persist_reviewed", "prepare_review", "run_prepare_review"):
        monkeypatch.setattr(bindings, name, Mock(side_effect=AssertionError("No binding writes")))


@pytest.fixture
def page():
    config = Path(os.environ["XDG_CONFIG_HOME"])
    (config / "hypr").mkdir()
    window = Mock()
    window.editor_edit_allowed.return_value = True
    window.hypr.online = True
    window.hypr.get_binds.return_value = []
    entries = []
    page = ManagedBindingsPage(window, on_dirty_changed=Mock(), push_undo=entries.append)
    page.baseline = bindings.observe(config, Path(os.environ["XDG_STATE_HOME"]))
    window._managed_bindings_page = page
    return page, window, entries


def saved_page(page, lines):
    model, _window, _entries = page
    target = Path(model.baseline.lexical_path)
    target.write_text(bindings.build_text(bindings.BindingsConfig(tuple(lines))))
    model.baseline = bindings.observe(model._config_root, model._state_root)
    model._owned = SavedList(list(model.baseline.config.lines), key=str)
    return model


def drain_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        GLib.MainContext.default().iteration(False)
        time.sleep(0.005)
    assert predicate()


class TestManagedDraft:
    def test_lazy_constructor(self):
        window = Mock()
        model = ManagedBindingsPage(window)
        assert model.baseline is None
        assert model.load_error is None
        assert not model.locked
        assert model.get_config() == bindings.BindingsConfig()
        assert not model.is_dirty()
        window.hypr.get_binds.assert_not_called()

    def test_add_edit_delete_undo_and_discard_are_local(self, page):
        model, window, entries = page
        model.add_line(T)
        assert model.is_dirty()
        assert len(entries) == 1
        entry = entries[-1]
        assert isinstance(entry, SavedListSnapshot)
        assert entry.page_attr == "_managed_bindings_page"
        assert entry.apply(window, undo=True)
        assert not model.is_dirty()
        assert entry.apply(window, undo=False)
        assert model.get_config().lines == (T,)
        model.edit_line(0, Q)
        model.delete_at(0)
        assert not model.is_dirty()
        model.add_line(T)
        model.discard()
        assert not model.is_dirty()
        assert window.hypr.mock_calls == []
        assert not Path(model.baseline.lexical_path).exists()

    def test_edits_count_once_and_revert_exact_baselines(self, page):
        model = saved_page(page, [Q, T])
        model.edit_line(0, "bind = SUPER, Q, exec, one")
        changes = list(model.iter_pending_changes())
        assert len(changes) == model.pending_change_count() == 1
        assert changes[0].kind == "modified"
        assert changes[0].category == "Keybindings"
        assert changes[0].navigate_to == "binds"
        changes[0].revert()
        assert not model.is_dirty()
        model.delete_at(0)
        changes = list(model.iter_pending_changes())
        assert len(changes) == 1 and changes[0].kind == "removed"
        changes[0].revert()
        assert model.get_config().lines == (Q, T)
        assert not model.is_dirty()

    def test_delete_and_readd_exact_saved_line_has_no_pending_changes(self, page):
        model = saved_page(page, [Q])
        model.delete_at(0)
        model.add_line(Q)
        assert not model.is_dirty()
        assert model.pending_change_count() == 0

    @pytest.mark.parametrize("dispatcher", ["__lua", "exec", "unknown_callback"])
    def test_external_conflicts_block_alias_case_and_move(self, page, dispatcher):
        model, window, entries = page
        model._runtime = (Bind(MOD_BITS["CTRL"], "q", dispatcher, "42", submap="resize"),)
        before = model._capture_undo()
        with pytest.raises(ValueError, match="external runtime"):
            model.add_line("bind = CONTROL, Q, exec, kitty")
        assert model._capture_undo() == before
        assert not entries
        model.add_line(T)
        before = model._capture_undo()
        with pytest.raises(ValueError, match="external runtime"):
            model.edit_line(0, "bind = CTRL, q, killactive")
        assert model._capture_undo() == before
        assert window.hypr.mock_calls == []

    def test_same_combo_edit_keeps_external_inventory(self, page):
        model = saved_page(page, [Q])
        raw = Bind(MOD_BITS["SUPER"], "q", "__lua", "42", description="foreign")
        model._runtime = (raw,)
        model.edit_line(0, "bindr = WIN, Q, exec, kitty")
        assert model._runtime == (raw,)
        assert model.get_config().lines == ("bindr = SUPER, Q, exec, kitty",)

    def test_revert_exact_owned_baseline_allows_observed_external_overlap(self, page):
        model = saved_page(page, [Q])
        raw = Bind(MOD_BITS["SUPER"], "Q", "__lua", "42")
        model._runtime = (raw,)
        model.edit_line(0, T)
        model._revert_item(0)
        assert model.get_config().lines == (Q,)
        assert not model.is_dirty()
        assert model._runtime == (raw,)
        page[1].hypr.assert_not_called()
        assert page[1].hypr.mock_calls == []

    @pytest.mark.parametrize("refusal", ["window-lock", "binding-lock", "duplicate"])
    def test_baseline_revert_refusal_is_atomic(self, page, refusal):
        model = saved_page(page, [Q])
        model.edit_line(0, T)
        if refusal == "window-lock":
            page[1].editor_edit_allowed.return_value = False
        elif refusal == "binding-lock":
            model.invalidate("Binding writer lock")
        else:
            model.add_line(Q)
        before, count = model._capture_undo(), len(page[2])
        with pytest.raises(ValueError):
            model._revert_item(0)
        assert model._capture_undo() == before
        assert len(page[2]) == count

    @pytest.mark.parametrize(
        "line",
        [
            "bind = SUPER, Q, custom_callback, x",
            "bind = SUPER, Q, resizeactive, nonsense",
            "bind = SUPER, Q, killactive, address:0x123",
            "unbind = SUPER, Q",
            "bindm = SUPER, mouse:272, movewindow",
            "bind = SUPER, Q, exec, x\nhl.dsp.exec('bad')",
            "bind = SUPER, Q, submap, resize",
        ],
    )
    def test_validation_failure_is_atomic(self, page, line):
        model, window, entries = page
        model.add_line(T)
        before, count = model._capture_undo(), len(entries)
        with pytest.raises(ValueError):
            model.edit_line(0, line)
        assert model._capture_undo() == before
        assert len(entries) == count
        assert window.hypr.mock_calls == []

    def test_owned_duplicates_block_and_shell_text_is_preserved(self, page):
        model, _window, entries = page
        command = "sh -c 'echo  \"$HOME, $USER\"'"
        line = f"bind = CONTROL SUPER, T, exec, {command}"
        model.add_line(line)
        assert bindings.validate_line(model.get_config().lines[0]).arg == command
        with pytest.raises(ValueError, match="Duplicate keyboard"):
            model.add_line("bindr = SUPER CTRL, t, exec, x")
        assert len(entries) == 1

    def test_locks_rechecked_and_binding_invalidation_is_sticky(self, page):
        model, window, _entries = page
        model.add_line(Q)
        window.editor_edit_allowed.return_value = False
        with pytest.raises(ValueError, match="locked"):
            model.edit_line(0, T)
        window.editor_edit_allowed.return_value = True
        model.invalidate("Foreign output. Fix manually and restart.")
        with pytest.raises(ValueError, match="Foreign"):
            model.add_line(T)
        with pytest.raises(ValueError):
            model.restore_snapshot([], [])
        model.discard()
        assert model.locked and model.load_error
        assert not model.is_dirty()
        assert window.editor_edit_allowed()

    def test_no_unverified_mark_saved_or_baseline_adoption(self, page):
        model, _window, _entries = page
        old = model.baseline
        model.add_line(Q)
        with pytest.raises(ValueError, match="verified"):
            model.mark_saved()
        with pytest.raises(ValueError):
            model.adopt_saved(old)
        target = Path(old.lexical_path)
        target.write_text(bindings.build_text(model.get_config()))
        fresh = bindings.observe(model._config_root, model._state_root)
        model.adopt_saved(fresh)
        assert model.baseline == fresh
        assert not model.is_dirty()
        model.add_line(T)
        model.discard()
        assert model.get_config() == fresh.config


class TestReadSlot:
    def test_offline_empty_inventory_is_unknown(self, page, monkeypatch):
        model, window, _entries = page
        monkeypatch.setattr(bindings, "run_observe", Mock(return_value=model.baseline))
        window.hypr.online = False
        model.ensure_loaded()
        drain_until(lambda: not model._loading)
        assert "offline" in (model._inventory_error or "")
        window.hypr.get_binds.assert_not_called()

    def test_load_off_main_thread_once_and_unknown_inventory(self, page, monkeypatch):
        model, window, _entries = page
        baseline = model.baseline
        model.baseline = None
        threads = []

        def observe(*args, **kwargs):
            threads.append(threading.current_thread())
            return baseline

        monkeypatch.setattr(bindings, "run_observe", observe)
        window.hypr.get_binds.return_value = None
        model.ensure_loaded()
        model.ensure_loaded()
        drain_until(lambda: not model._loading)
        assert model.baseline == baseline
        assert len(threads) == 1 and threads[0] is not threading.current_thread()
        assert model._inventory_error
        assert not model.locked

    def test_foreign_error_locks_only_binding_editor_inventory_retained(self, page, monkeypatch):
        model, window, _entries = page
        model.baseline = None
        raw = Bind(0, "F1", "__lua", "2", description="Read-only foreign callback")
        window.hypr.get_binds.return_value = [raw]
        monkeypatch.setattr(bindings, "run_observe", Mock(side_effect=ValueError("Foreign output")))
        model.ensure_loaded()
        drain_until(lambda: not model._loading)
        assert model.baseline is None and model.locked
        assert model._runtime == (raw,)
        assert "Foreign" in (model.load_error or "")
        assert window.editor_edit_allowed()
        with pytest.raises(ValueError):
            model.add_line(Q)

    def test_close_cancels_and_retires_generation_without_early_slot_release(
        self, page, monkeypatch
    ):
        model, _window, _entries = page
        model.baseline = None
        entered, release = threading.Event(), threading.Event()

        def observe(*args, cancel_event):
            entered.set()
            release.wait(3)
            assert cancel_event.is_set()
            raise ValueError("Cancelled")

        observer = Mock(side_effect=observe)
        monkeypatch.setattr(bindings, "run_observe", observer)
        model.ensure_loaded()
        assert entered.wait(2)
        model.close()
        model.ensure_loaded()
        assert model._loading
        release.set()
        drain_until(lambda: not model._loading)
        assert model.baseline is None and model.load_error is None
        observer.assert_called_once()
