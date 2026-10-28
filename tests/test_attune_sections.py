"""Saved visual directives survive an empty IPC document and incomplete live state."""

import copy
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hyprland_monitors import MonitorState
from hyprland_socket import HyprlandError
from hyprland_state import AnimState, HyprlandState

from hyprmod.pages.animations import AnimationsPage
from hyprmod.pages.monitors.page import MonitorsPage


@pytest.fixture
def window():
    win = MagicMock()
    win.hypr = HyprlandState(path=Path("/dev/null"), offline=True)
    win.saved_sections = {}
    return win


def _monitor(name: str = "DP-1", description: str = "Acme Panel SN123") -> MonitorState:
    return MonitorState(
        name=name,
        description=description,
        make="Acme",
        model="Panel",
        width=1920,
        height=1080,
        refresh_rate=60.0,
        x=0,
        y=0,
        scale=1.0,
    )


@pytest.fixture
def monitor_page(window):
    def build(lines, monitors=()):
        window.saved_sections = {"monitor": lines}
        window.hypr = MagicMock()
        window.hypr.monitors.get_all.return_value = list(monitors)
        window.hypr.monitors.apply.return_value = True
        return MonitorsPage(window, push_undo=window.push_undo)

    return build


class TestAnimationDirectives:
    def test_offline_clean_preserves_disabled_and_unknown_records(self, window):
        lines = [
            "animation = windows, 0",
            "animation = futureAnimation, 1, 4.00, unknownCurve, future style",
        ]
        window.saved_sections = {"animation": lines}
        page = AnimationsPage(window)
        assert not page.is_dirty()
        assert page.get_animation_lines() == (lines, {"unknownCurve"})
        assert window.hypr.document.lines == []

    def test_dirty_offline_merges_only_edited_record(self, window):
        untouched = "animation = futureAnimation, 1, 4.00, unknownCurve, future style"
        disabled = "animation = fade, 0, 8.00, dormantCurve"
        window.saved_sections = {
            "animation": ["animation = windows, 1, 5, customCurve", untouched, disabled]
        }
        page = AnimationsPage(window)
        page.set_field("windows", "speed", 7.0)
        lines, curves = page.get_animation_lines()
        assert page.is_dirty()
        assert lines == ["animation = windows,1,7.0,customCurve", untouched, disabled]
        assert curves == {"customCurve", "unknownCurve", "dormantCurve"}

    def test_runtime_drift_does_not_replace_unchanged_saved_record(self, window):
        saved = "animation = windows, 1, 5.00, savedCurve, slide"
        window.saved_sections = {"animation": [saved, "animation = fade, 0"]}
        runtime = AnimState("windows", overridden=True, speed=9, curve="runtimeCurve")
        window.hypr.animations.set_baseline("windows", runtime)
        window.hypr.animations.update_cached("windows", runtime)
        page = AnimationsPage(window)
        page.set_field("fade", "enabled", True)
        lines, curves = page.get_animation_lines()
        assert lines[0] == saved
        assert "savedCurve" in curves
        assert "runtimeCurve" not in curves

    @pytest.mark.parametrize("method", ["unmanage_anim", "set_overridden"])
    def test_removal_omits_dirty_record_without_reload_or_live_fallback(self, window, method):
        window.saved_sections = {
            "animation": ["animation = windows, 1, 5, default", "animation = futureAnimation, 0"]
        }
        page = AnimationsPage(window, push_undo=window.push_undo)
        page.set_field("windows", "speed", 9.0)
        before = page.anims.get_cached("windows")
        window.hypr.reload_compositor = MagicMock()
        page.anims.get_fallback = MagicMock(side_effect=AssertionError("no fallback lookup"))
        page.anims.apply_state = MagicMock(side_effect=AssertionError("no live mutation"))
        if method == "set_overridden":
            page.set_overridden("windows", False)
        else:
            page.unmanage_anim("windows")
        assert page.get_animation_lines() == (["animation = futureAnimation, 0"], set())
        assert page.anims.get_cached("windows") == before
        assert page.is_dirty()
        window.hypr.reload_compositor.assert_not_called()
        page.anims.get_fallback.assert_not_called()
        page.anims.apply_state.assert_not_called()
        assert "Save removes override" in window.show_toast.call_args.args[0]

    def test_unknown_removal_is_explicit_and_discardable(self, window):
        lines = ["animation = futureAnimation, 1, 4, customCurve"]
        window.saved_sections = {"animation": lines}
        page = AnimationsPage(window)
        page.unmanage_anim("futureAnimation")
        assert page.get_animation_lines() == ([], set())
        page.discard()
        assert not page.is_dirty()
        assert page.get_animation_lines() == (lines, {"customCurve"})

    def test_removal_undo_redo_restores_ownership_without_live_mutation(self, window):
        lines = ["animation = windows, 1, 5, default"]
        window.saved_sections = {"animation": lines}
        page = AnimationsPage(window, push_undo=window.push_undo)
        window._animations_page = page
        page.anims.apply_state = MagicMock()
        page.unmanage_anim("windows")
        entry = window.push_undo.call_args.args[0]
        assert entry.apply(window, undo=True)
        assert page.get_animation_lines()[0] == lines
        assert not page.is_dirty()
        assert entry.apply(window, undo=False)
        assert page.get_animation_lines()[0] == []
        page.anims.apply_state.assert_not_called()

    def test_removal_stays_removed_after_mark_saved_and_another_edit(self, window):
        window.saved_sections = {
            "animation": ["animation = windows, 1, 5, default", "animation = fade, 0"]
        }
        page = AnimationsPage(window)
        page.unmanage_anim("windows")
        page.mark_saved()
        assert not page.is_dirty()
        page.set_field("fade", "speed", 4.0)
        assert page.get_animation_lines()[0] == ["animation = fade, 0"]

    def test_preview_error_is_reported_instead_of_escaping_callback(self, window):
        window.saved_sections = {"animation": ["animation = windows, 1, 5, default"]}
        page = AnimationsPage(window)
        page.anims.apply_state = MagicMock(side_effect=HyprlandError("rejected"))
        page.set_field("windows", "speed", 6.0)
        window.show_bug_toast.assert_called_once()


class TestMonitorDirectives:
    SAVED = [
        "monitor = DP-1, 1920x1080@60, 0x0, 1",
        "monitor = HDMI-A-1, disable",
        "monitor = desc:Disconnected Panel, preferred, auto-right, 1.25, vrr, 2",
        "monitor = , preferred, auto, 1",
    ]

    def test_offline_clean_keeps_all_directives(self, monitor_page):
        page = monitor_page(self.SAVED)
        assert not page.is_dirty()
        assert page.get_monitor_lines() == self.SAVED

    def test_clean_live_page_does_not_replace_saved_mode_with_runtime(self, monitor_page):
        mon = _monitor()
        mon.width = 2560
        page = monitor_page(self.SAVED, [mon])
        assert not page.is_dirty()
        assert page.get_monitor_lines() == self.SAVED

    def test_edit_preserves_disconnected_disabled_and_dynamic_records(self, monitor_page):
        page = monitor_page(self.SAVED, [_monitor()])
        page._monitors[0].scale = 1.5
        assert page.is_dirty()
        assert page.get_monitor_lines() == [
            "monitor = DP-1, 1920x1080@60.00Hz, 0x0, 1.5",
            *self.SAVED[1:],
        ]

    def test_new_record_offline_does_not_drop_saved_directives(self, monitor_page):
        page = monitor_page(self.SAVED)
        page._monitors.append(_monitor("DP-2"))
        page._ownership.own("DP-2")
        assert page.is_dirty()
        assert page.get_monitor_lines() == [
            *self.SAVED,
            "monitor = DP-2, 1920x1080@60.00Hz, 0x0, 1",
        ]

    def test_edit_keeps_original_description_prefix(self, monitor_page):
        saved = "monitor = desc:Acme, preferred, auto, 1"
        page = monitor_page([saved, *self.SAVED[1:]], [_monitor()])
        page._monitors[0].scale = 1.5
        assert page.get_monitor_lines() == [
            "monitor = desc:Acme, preferred, auto, 1.5",
            *self.SAVED[1:],
        ]

    def test_selector_change_replaces_old_selector_only(self, monitor_page):
        page = monitor_page(self.SAVED, [_monitor()])
        page._monitors[0].identify_by_description = True
        assert page.get_monitor_lines() == [
            "monitor = desc:Acme Panel SN123, 1920x1080@60.00Hz, 0x0, 1",
            *self.SAVED[1:],
        ]

    def test_explicit_removal_does_not_mutate_live_layout(self, monitor_page, window):
        page = monitor_page(self.SAVED, [_monitor()])
        before = copy.deepcopy(page._monitors)
        page._remove_monitor(page._monitors[0])
        assert page.get_monitor_lines() == self.SAVED[1:]
        assert page._monitors == before
        assert page.is_dirty()
        window.hypr.monitors.apply.assert_not_called()
        window.hypr.document.find_all.assert_not_called()
        assert "Save removes override" in window.show_toast.call_args.args[0]

    def test_removal_discard_and_undo_do_not_apply_live(self, monitor_page, window):
        page = monitor_page(self.SAVED, [_monitor()])
        window._monitors_page = page
        page._remove_monitor(page._monitors[0])
        entry = window.push_undo.call_args.args[0]
        assert entry.apply(window, undo=True)
        assert page.get_monitor_lines() == self.SAVED
        assert not page.is_dirty()
        assert entry.apply(window, undo=False)
        assert page.get_monitor_lines() == self.SAVED[1:]
        page.discard()
        assert not page.is_dirty()
        assert page.get_monitor_lines() == self.SAVED
        window.hypr.monitors.apply.assert_not_called()

    def test_mark_saved_preserves_retained_records_for_later_edits(self, monitor_page):
        page = monitor_page(self.SAVED, [_monitor()])
        page._monitors[0].scale = 1.5
        page.mark_saved()
        assert not page.is_dirty()
        page._monitors[0].scale = 2.0
        assert page.get_monitor_lines()[1:] == self.SAVED[1:]

    def test_other_selector_for_same_port_is_not_removed(self, monitor_page):
        first = "monitor = DP-1, preferred, auto, 1"
        last = "monitor = desc:Acme, preferred, auto, 1"
        page = monitor_page([first, last, *self.SAVED[1:]], [_monitor()])
        page._remove_monitor(page._monitors[0])
        assert page.get_monitor_lines() == [first, *self.SAVED[1:]]

    def test_duplicate_target_selectors_cannot_resurrect_removed_record(self, monitor_page):
        page = monitor_page([self.SAVED[0], self.SAVED[0], *self.SAVED[1:]], [_monitor()])
        page._remove_monitor(page._monitors[0])
        assert page.get_monitor_lines() == self.SAVED[1:]
