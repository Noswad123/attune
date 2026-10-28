"""Curve preset saves become explicit, independently reviewable compositor drafts."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hyprland_config import BezierData
from hyprland_socket import HyprlandError
from hyprland_state import HyprlandState

from hyprmod.core import config, persistence
from hyprmod.data.bezier_data import get_curve_store
from hyprmod.pages.animations import AnimationsPage
from hyprmod.ui.bezier_editor import BezierEditor, BezierEditorDialog
from hyprmod.window import HyprModWindow

SAVED = (0.1, 0.2, 0.3, 1.0)
EDITED = (0.2, 0.4, 0.6, 1.0)
OTHER = (0.3, 0.5, 0.7, 1.0)
CANONICAL = "bezier = custom, 0.10, 0.20, 0.30, 1.00"
SPARE = "bezier = disconnectedCurve, 0.15, 0.25, 0.35, 1.00"


@pytest.fixture
def window():
    win = MagicMock()
    win.hypr = HyprlandState(path=Path("/dev/null"), offline=True)
    win.saved_sections = {
        "animation": ["animation = windows, 1, 5, custom"],
        "bezier": [CANONICAL, SPARE],
    }
    win._monitors_page = None
    return win


@pytest.fixture
def page(window):
    result = AnimationsPage(window, on_dirty_changed=window.dirty, push_undo=window.push_undo)
    window._animations_page = result
    return result


def _dialog(window, page, animation_name=None):
    dialog = BezierEditorDialog.__new__(BezierEditorDialog)
    dialog._parent = window
    dialog._anims = page.anims
    dialog._animation_name = animation_name
    dialog._animation_page = page
    dialog._on_curve_saved = MagicMock()
    dialog._editor = MagicMock()
    dialog._editor.get_points.return_value = EDITED
    dialog._dialog = MagicMock()
    dialog._preview_active = False
    dialog._original_eff = page.anims.get_effective(animation_name) if animation_name else None
    dialog._user_saved = False
    return dialog


class TestCurveStoreIsolation:
    def test_store_follows_dynamic_config_path(self, tmp_path, monkeypatch):
        first = get_curve_store()
        monkeypatch.setattr(config, "HYPRMOD_DIR", tmp_path / "another-home")
        second = get_curve_store()
        assert second is not first
        second.save_user_curve("isolated", EDITED)
        assert (config.HYPRMOD_DIR / "user_curves.json").exists()
        assert "isolated" not in first.get_user_curve_names()
        assert get_curve_store() is second


class TestCurveDraft:
    def test_speed_edit_preserves_canonical_definitions_despite_store_drift(self, window):
        store = get_curve_store()
        store.save_user_curve("custom", OTHER)
        page = AnimationsPage(window)
        window._animations_page = page
        store.set_hyprland_curves({"custom": EDITED})
        page.set_field("windows", "speed", 7.0)
        sections = HyprModWindow.collect_save_sections(window)
        assert sections.beziers == [CANONICAL, SPARE]
        assert page.get_curve_points("custom") == SAVED

    def test_same_name_save_is_dirty_without_animation_field_change(self, page, window):
        store = get_curve_store()
        store.save_user_curve("custom", EDITED)
        window.dirty.reset_mock()
        page.curve_saved("custom")
        assert page.is_dirty()
        assert page.changed_curve_names == {"custom"}
        assert not page.is_anim_dirty("windows")
        assert page.get_curve_points("custom") == EDITED
        window.dirty.assert_called_once_with()
        pending = list(page.iter_pending_changes())
        assert len(pending) == 1
        assert pending[0].title == "Curve: custom"
        sections = HyprModWindow.collect_save_sections(window)
        assert sections.beziers == [BezierData("custom", EDITED).to_line(), SPARE]
        assert sections.animations == window.saved_sections["animation"]
        output = persistence.read_document(persistence.build_text({}, sections))
        assert BezierData.from_body(output.find_all("bezier")[0].value).points == EDITED

    def test_curve_only_save_as_new_is_reviewable(self, page, window):
        store = get_curve_store()
        store.save_user_curve("newCurve", EDITED)
        page.curve_saved("newCurve")
        sections = HyprModWindow.collect_save_sections(window)
        assert sections.beziers == [CANONICAL, SPARE, BezierData("newCurve", EDITED).to_line()]
        assert list(page.iter_pending_changes())[0].kind == "added"

    def test_new_reference_resolves_from_store_without_overwriting_saved_names(self, page, window):
        get_curve_store().save_user_curve("newCurve", EDITED)
        page.set_field("windows", "curve", "newCurve")
        sections = HyprModWindow.collect_save_sections(window)
        assert sections.beziers == [CANONICAL, SPARE, BezierData("newCurve", EDITED).to_line()]

    def test_preset_save_without_editor_callback_does_not_change_compositor_draft(self, page):
        get_curve_store().save_user_curve("custom", EDITED)
        assert not page.is_dirty()
        assert page.get_curve_definitions({"custom"}) == [CANONICAL, SPARE]

    def test_revert_restores_canonical_points_not_changed_preset(self, page):
        store = get_curve_store()
        store.save_user_curve("custom", EDITED)
        page.anims.define_bezier = MagicMock()
        page.curve_saved("custom")
        pending = list(page.iter_pending_changes())[0]
        pending.revert()
        assert not page.is_dirty()
        assert page.get_curve_definitions({"custom"}) == [CANONICAL, SPARE]
        assert page.get_curve_points("custom") == SAVED
        page.anims.define_bezier.assert_called_with("custom", SAVED)
        assert store.get_curve_points("custom") == EDITED

    def test_curve_save_undo_redo_restores_points_and_pending(self, page, window):
        get_curve_store().save_user_curve("custom", EDITED)
        page.curve_saved("custom")
        change = window.push_undo.call_args.args[0]
        assert change.apply(window, undo=True)
        assert not page.is_dirty()
        assert page.get_curve_points("custom") == SAVED
        assert change.apply(window, undo=False)
        assert page.is_dirty()
        assert page.get_curve_points("custom") == EDITED

    def test_multiple_same_name_saves_can_be_undone_independently(self, page, window):
        store = get_curve_store()
        store.save_user_curve("custom", EDITED)
        page.curve_saved("custom")
        store.save_user_curve("custom", OTHER)
        page.curve_saved("custom")
        change = window.push_undo.call_args.args[0]
        change.apply(window, undo=True)
        assert page.get_curve_points("custom") == EDITED
        assert page.is_dirty()

    def test_discard_new_curve_draft_keeps_existing_definitions_and_library(self, page):
        store = get_curve_store()
        store.save_user_curve("newCurve", EDITED)
        page.curve_saved("newCurve")
        page.discard()
        assert not page.is_dirty()
        assert page.get_curve_definitions({"custom"}) == [CANONICAL, SPARE]
        assert store.get_curve_points("newCurve") == EDITED

    def test_mark_saved_adopts_points_as_canonical_for_next_edit(self, page):
        store = get_curve_store()
        store.save_user_curve("custom", EDITED)
        page.curve_saved("custom")
        page.mark_saved()
        assert not page.is_dirty()
        store.save_user_curve("custom", OTHER)
        page.set_field("windows", "speed", 7.0)
        assert page.get_curve_definitions({"custom"}) == [
            BezierData("custom", EDITED).to_line(),
            SPARE,
        ]

    def test_returning_to_canonical_points_clears_curve_dirty(self, page):
        store = get_curve_store()
        store.save_user_curve("custom", EDITED)
        page.curve_saved("custom")
        store.save_user_curve("custom", SAVED)
        page.curve_saved("custom")
        assert not page.is_dirty()
        assert page.get_curve_definitions({"custom"}) == [CANONICAL, SPARE]

    def test_unreferenced_saved_curve_is_not_deleted_on_unmanage(self, page):
        page.unmanage_anim("windows")
        assert page.get_animation_lines()[0] == []
        assert page.get_curve_definitions(set()) == [CANONICAL, SPARE]


class TestCurveEditorCallbacks:
    @pytest.mark.parametrize("animation_name", [None, "windows"])
    def test_save_callback_stages_same_name_points_from_both_entrypoints(
        self, page, window, animation_name
    ):
        dialog = _dialog(window, page, animation_name)
        editor = MagicMock()
        editor.get_points.return_value = EDITED
        editor._on_curve_saved = dialog._on_editor_saved
        BezierEditor._save_and_refresh(editor, "custom")
        assert get_curve_store().get_curve_points("custom") == EDITED
        assert page.is_dirty()
        assert not page.is_anim_dirty("windows")
        assert page.get_curve_points("custom") == EDITED
        assert list(page.iter_pending_changes())[0].title == "Curve: custom"

    def test_standalone_entrypoint_supplies_animation_page(self, page, window, monkeypatch):
        factory = MagicMock()
        monkeypatch.setattr("hyprmod.pages.animations.BezierEditorDialog", factory)
        page._on_open_curve_editor(None)
        assert factory.call_args.kwargs["animation_page"] is page

    def test_preset_delete_preserves_canonical_definition(self, page, window):
        get_curve_store().save_user_curve("custom", EDITED)
        page.curve_saved("custom")
        get_curve_store().delete_user_curve("custom")
        _dialog(window, page)._on_editor_deleted("custom")
        assert page.get_curve_definitions(set()) == [CANONICAL, SPARE]
        assert "custom" not in page.get_animation_lines()[1]

    def test_preset_rename_does_not_delete_old_saved_definition(self, page, window):
        store = get_curve_store()
        store.save_user_curve("custom", EDITED)
        store.rename_user_curve("custom", "renamed")
        _dialog(window, page)._on_editor_renamed("custom", "renamed")
        assert page.get_curve_definitions({"renamed"}) == [
            CANONICAL,
            SPARE,
            BezierData("renamed", EDITED).to_line(),
        ]

    def test_preview_errors_do_not_escape_callbacks(self, page, window):
        dialog = _dialog(window, page, "windows")
        page.anims.preview = MagicMock(side_effect=HyprlandError("rejected"))
        dialog._on_curve_changed(*EDITED)
        assert not dialog._preview_active
        window.show_bug_toast.assert_called_once()

    @pytest.mark.parametrize("saved", [False, True])
    def test_preview_restore_errors_do_not_escape_close(self, page, window, saved):
        dialog = _dialog(window, page, "windows")
        dialog._preview_active = True
        dialog._user_saved = saved
        page.anims.preview = MagicMock(side_effect=HyprlandError("rejected"))
        page.anims.apply = MagicMock(side_effect=HyprlandError("rejected"))
        dialog._on_closed(None)
        window.show_bug_toast.assert_called_once()
