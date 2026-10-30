"""Exercise navigation and review wiring without constructing GTK widgets."""

import os
import stat
from dataclasses import asdict, replace
from pathlib import Path
from types import MethodType
from typing import cast
from unittest.mock import MagicMock

import pytest

from hyprmod import main as main_module
from hyprmod import window as window_module
from hyprmod.core import config, persistence
from hyprmod.core.focused_ui import PAGE_IDS, ReviewSnapshot, filter_schema
from hyprmod.core.schema import load_schema
from hyprmod.ui.search import SearchPage
from hyprmod.window import HyprModWindow


class TestFocusedNavigation:
    def test_close_keeps_monitor_rollback_timer_alive(self):
        win = MagicMock()
        win._restore_in_progress = False
        win._monitors_page.is_confirm_pending.return_value = True
        assert HyprModWindow._on_close_request(win) is True
        win.show_page.assert_called_once_with("monitors")
        win._monitors_page.is_confirm_pending.return_value = False
        assert HyprModWindow._on_close_request(win) is False

    @pytest.mark.parametrize("query", ["keybind", "autostart", "env", "workspace rule", "plugin"])
    def test_search_does_not_index_unsupported_controls(self, query):
        search = SearchPage(filter_schema(load_schema()))
        assert search.search(query) == []

    def test_visual_options_remain_searchable(self):
        search = SearchPage(filter_schema(load_schema()))
        assert search.search("rounding")
        assert search.search("gaps")
        assert search.search("animations")
        assert all(result["_group_id"] in PAGE_IDS for result in search.search("border"))
        assert all(result["_group_id"] in PAGE_IDS for result in search.search("layout"))

    def test_only_supported_pages_are_registered(self, monkeypatch):
        win = MagicMock()
        win._schema = filter_schema(load_schema())
        win._key_to_group = {}
        for name in (
            "MonitorsPage",
            "PendingChangesPage",
            "SettingsPage",
            "HealthPage",
            "BackupsPage",
            "ScopeRecoveryPage",
        ):
            monkeypatch.setattr(window_module, name, MagicMock())
        HyprModWindow._build_pages(win)
        registered = {call.args[1] for call in win._page_stack.add_named.call_args_list}
        assert registered == PAGE_IDS - {"search"}
        health_page = cast(MagicMock, window_module.HealthPage)
        health_page.assert_called_once_with(config.managed_path())
        health_page.return_value.ensure_loaded.assert_not_called()
        backups_page = cast(MagicMock, window_module.BackupsPage)
        backups_page.assert_called_once_with(
            config.managed_path(),
            restore_permission=win.restore_permission,
            begin_restore=win.begin_restore,
            finish_restore=win.finish_restore,
        )
        backups_page.return_value.ensure_loaded.assert_not_called()
        backups_page.return_value.bind_lifecycle.assert_called_once_with(win)

    def test_health_navigation_ensures_lazy_load(self):
        win = MagicMock()
        win._page_titles = {"health": "Health"}
        win._monitors_page = None
        HyprModWindow.show_page(win, "health")
        win._health_page.ensure_loaded.assert_called_once_with()
        win._page_stack.set_visible_child_name.assert_called_once_with("health")

    def test_save_api_only_opens_review(self):
        win = MagicMock()
        HyprModWindow.save(win)
        win._show_pending.assert_called_once_with()
        win._perform_save.assert_not_called()

    def test_backups_navigation_ensures_lazy_load(self):
        win = MagicMock()
        win._page_titles = {"backups": "Backups"}
        win._monitors_page = None
        HyprModWindow.show_page(win, "backups")
        win._backups_page.ensure_loaded.assert_called_once_with()
        win._page_stack.set_visible_child_name.assert_called_once_with("backups")

    @pytest.mark.parametrize("destination", ["profiles", "binds", "workspaces", "plugins"])
    def test_navigation_rejects_unsupported_pages(self, destination):
        win = MagicMock()
        win._page_titles = {destination: "Should not be reachable"}
        HyprModWindow.show_page(win, destination)
        win._page_stack.set_visible_child_name.assert_not_called()

    def test_review_does_not_accept_monitor_preview(self):
        win = MagicMock()
        win._page_titles = {"pending": "Pending Changes"}
        win._monitors_page.is_confirm_pending.return_value = True
        HyprModWindow.show_page(win, "pending")
        win._monitors_page.confirm_changes.assert_not_called()
        win._page_stack.set_visible_child_name.assert_not_called()

    def test_only_monitors_animations_and_used_curves_are_collected(self):
        win = MagicMock()
        win.saved_sections = {"exec-once": ["keep-my-startup"], "bind": ["keep-my-binding"]}
        win._monitors_page.get_monitor_lines.return_value = ["monitor = DP-1, preferred, auto, 1"]
        win._animations_page.get_animation_lines.return_value = (
            ["animation = windows, 1, 5, smooth"],
            {"smooth"},
        )
        win._animations_page.get_curve_definitions.return_value = [
            "bezier = smooth, 0.1, 0.2, 0.3, 1"
        ]
        sections = HyprModWindow.collect_save_sections(win)
        assert sections.monitors == win._monitors_page.get_monitor_lines()
        assert sections.animations == ["animation = windows, 1, 5, smooth"]
        assert sections.beziers == ["bezier = smooth, 0.1, 0.2, 0.3, 1"]
        assert all(
            value is None
            for name, value in asdict(sections).items()
            if name not in {"monitors", "animations", "beziers"}
        )
        assert win._health_page.mock_calls == []
        assert win._backups_page.mock_calls == []

    def test_review_reads_only_managed_output(self, tmp_path, monkeypatch):
        path = tmp_path / "attune.lua"
        path.write_bytes(b"old\r\n")
        monkeypatch.setattr(config, "managed_path", lambda: path)
        monkeypatch.setattr(persistence, "build_text", MagicMock(return_value="new\n"))
        win = MagicMock()
        snapshot = HyprModWindow.review_snapshot(win)
        assert snapshot == ReviewSnapshot(path, "old\r\n", "new\n", path.resolve())

    def test_discard_restores_runtime_baseline_without_parsing_user_config(self):
        win = MagicMock()
        state = MagicMock(is_dirty=True)
        win.app_state.options = {"decoration:rounding": state}
        win._section_pages = []
        HyprModWindow._do_discard(win)
        win.app_state.discard_one.assert_called_once_with("decoration:rounding")
        win.app_state.discard_dirty.assert_not_called()
        win.hypr.clear_pending.assert_called_once_with()


@pytest.fixture
def review_window(monkeypatch):
    monkeypatch.setattr(persistence, "persist_reviewed", MagicMock(return_value=None))
    win = MagicMock()
    win._page_stack.get_visible_child_name.return_value = "pending"
    win._monitors_page.is_confirm_pending.return_value = False
    win.review_snapshot.return_value = ReviewSnapshot(Path("attune.lua"), "old", "new")
    return win


class TestReviewedSave:
    @pytest.mark.parametrize("uncertain", [False, True])
    def test_fsync_failure_preserves_or_invalidates_editor_according_to_write_outcome(
        self, tmp_path, monkeypatch, uncertain
    ):
        path = tmp_path / "attune.lua"
        sections = config.ConfigSections()
        previous = persistence.build_text({"general:gaps_in": "5"}, sections)
        proposed = persistence.build_text({"general:gaps_in": "9"}, sections)
        path.write_text(previous)
        reviewed = ReviewSnapshot(path, previous, proposed, path.resolve())
        win = MagicMock()
        win._restore_in_progress = False
        win._editor_invalidated = False
        win.editor_edit_allowed = MethodType(HyprModWindow.editor_edit_allowed, win)
        win.finish_restore = MethodType(HyprModWindow.finish_restore, win)
        win._page_stack.get_visible_child_name.return_value = "pending"
        win._monitors_page.is_confirm_pending.return_value = False
        win.review_snapshot.return_value = reviewed
        win.app_state.get_all_live_values.return_value = {"general:gaps_in": "9"}
        win.collect_save_sections.return_value = sections
        fsync = os.fsync
        parent = path.parent.stat()

        def fail_sync(fd):
            info = os.fstat(fd)
            target_directory = (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino)
            if (uncertain and target_directory) or (not uncertain and stat.S_ISREG(info.st_mode)):
                raise OSError("injected fsync failure")
            fsync(fd)

        monkeypatch.setattr(os, "fsync", fail_sync)
        with config.managed_path_override(path):
            assert config.read_cached()[0]["general:gaps_in"] == "5"
            HyprModWindow.save_reviewed(win, reviewed)
            win._perform_save.assert_not_called()
            win._banner.show_saved.assert_not_called()
            assert win._editor_invalidated is uncertain
            assert path.read_text() == (proposed if uncertain else previous)
            assert config.read_cached()[0]["general:gaps_in"] == ("9" if uncertain else "5")
            if uncertain:
                assert "Output may have changed" in win.show_toast.call_args.args[0]
                win.review_snapshot.return_value = ReviewSnapshot(
                    path, proposed, proposed, path.resolve()
                )
                win.review_snapshot.reset_mock()
                HyprModWindow.save_reviewed(win, win.review_snapshot.return_value)
                win.review_snapshot.assert_not_called()
                assert not win.editor_edit_allowed()
                win.app_state.mark_saved.assert_not_called()
            else:
                assert win.editor_edit_allowed()

    def test_matching_review_saves(self, review_window):
        HyprModWindow.save_reviewed(review_window, review_window.review_snapshot())
        review_window._perform_save.assert_called_once_with()
        review_window._banner.show_saved.assert_called_once_with()

    @pytest.mark.parametrize(
        "change",
        [{"path": Path("other.lua")}, {"saved_text": "external"}, {"proposed_text": "later"}],
    )
    def test_stale_review_is_refreshed_without_saving(self, review_window, change):
        reviewed = review_window.review_snapshot()
        review_window.review_snapshot.return_value = replace(reviewed, **change)
        HyprModWindow.save_reviewed(review_window, reviewed)
        review_window._perform_save.assert_not_called()
        review_window._show_pending.assert_called_once_with()

    def test_review_required_on_pending_page(self, review_window):
        review_window._page_stack.get_visible_child_name.return_value = "general"
        HyprModWindow.save_reviewed(review_window, review_window.review_snapshot())
        review_window._perform_save.assert_not_called()
        review_window._show_pending.assert_called_once_with()

    def test_unconfirmed_monitor_is_not_saved(self, review_window):
        review_window._monitors_page.is_confirm_pending.return_value = True
        HyprModWindow.save_reviewed(review_window, review_window.review_snapshot())
        review_window._perform_save.assert_not_called()

    def test_failed_read_does_not_save(self, review_window):
        reviewed = review_window.review_snapshot()
        review_window.review_snapshot.side_effect = PermissionError("denied")
        HyprModWindow.save_reviewed(review_window, reviewed)
        review_window._perform_save.assert_not_called()
        review_window.show_toast.assert_called_once()

    def test_failed_write_does_not_show_saved(self, review_window):
        review_window._perform_save.side_effect = ValueError("unsafe output")
        HyprModWindow.save_reviewed(review_window, review_window.review_snapshot())
        review_window._banner.show_saved.assert_not_called()
        review_window.show_toast.assert_called_once()


class TestNoProfileCLI:
    def test_positional_commands_do_not_run_profile_cli(self, monkeypatch):
        monkeypatch.setattr(main_module.sys, "argv", ["attune", "profile", "activate", "test"])
        app = MagicMock()
        monkeypatch.setattr(main_module, "HyprModApp", app)
        assert main_module.main() == 2
        app.assert_not_called()
