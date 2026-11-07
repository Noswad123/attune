"""Bluetooth handoff widgets with external launches mocked."""

import os
from unittest.mock import Mock

import pytest
from gi.repository import Adw, Gio, GLib, Gtk

from hyprmod.pages.bluetooth import BluetoothPage

pytestmark = pytest.mark.skipif(
    os.environ.get("ATTUNE_GUI_SMOKE") != "1" or os.environ.get("GDK_BACKEND") != "broadway",
    reason="opt-in isolated Broadway widgets",
)


@pytest.fixture
def built(monkeypatch):
    Adw.init()
    lookup = Mock(return_value="/usr/bin/blueman-manager")
    launch = Mock()
    monkeypatch.setattr(GLib, "find_program_in_path", lookup)
    monkeypatch.setattr(Gio.Subprocess, "new", launch)
    page = BluetoothPage()
    view = page.build(Adw.HeaderBar())
    return page, view, lookup, launch


def widgets(parent):
    yield parent
    child = parent.get_first_child()
    while child is not None:
        yield from widgets(child)
        child = child.get_next_sibling()


class TestBluetoothPage:
    def test_construction_has_no_external_effects(self, built):
        page, view, lookup, launch = built
        assert isinstance(view, Adw.ToolbarView)
        assert not page._status.get_visible()
        lookup.assert_not_called()
        launch.assert_not_called()

    def test_button_launches_only_fixed_executable_without_shell(self, built):
        page, view, lookup, launch = built
        button = next(
            widget
            for widget in widgets(view)
            if isinstance(widget, Gtk.Button) and widget.get_label() == "Open Bluetooth Manager"
        )
        button.emit("clicked")
        lookup.assert_called_once_with("blueman-manager")
        launch.assert_called_once_with(["/usr/bin/blueman-manager"], Gio.SubprocessFlags.NONE)
        assert page._status.get_visible()
        assert "launch requested" in page._status.get_label()
        assert "does not confirm" in page._status.get_label()

    def test_missing_executable_explains_install_and_allows_retry(self, built):
        page, _view, lookup, launch = built
        lookup.return_value = None
        page.open_manager()
        launch.assert_not_called()
        assert page._status.get_visible()
        assert "not found on PATH" in page._status.get_label()
        assert "sudo pacman -S blueman" in page._status.get_label()
        lookup.return_value = "/path with spaces/blueman-manager"
        page.open_manager()
        launch.assert_called_once_with(
            ["/path with spaces/blueman-manager"], Gio.SubprocessFlags.NONE
        )
        assert "not found" not in page._status.get_label()

    def test_spawn_error_is_visible_literal_text_and_retryable(self, built):
        page, _view, _lookup, launch = built
        launch.side_effect = GLib.Error("Permission <denied> & blocked")
        page.open_manager()
        assert "Permission <denied> & blocked" in page._status.get_label()
        assert not page._status.get_use_markup()
        assert page._status.get_visible()
        launch.side_effect = None
        page.open_manager()
        assert "launch requested" in page._status.get_label()
