"""Tests for the XDG install/registration helpers."""

from pathlib import Path

import pytest
from gi.repository import Gio, GLib

from hyprmod import install

DESKTOP_TEXT = "[Desktop Entry]\nType=Application\nExec=attune\nTerminal=false\n"


def _desktop_file(tmp_path: Path) -> Path:
    path = tmp_path / install.DESKTOP_FILE
    path.write_text(DESKTOP_TEXT)
    return path


class TestIsRegistered:
    def test_returns_true_when_entry_found(self, monkeypatch):
        monkeypatch.setattr(Gio.DesktopAppInfo, "new", staticmethod(lambda _id: object()))
        assert install.is_registered() is True

    def test_returns_false_on_constructor_returned_null(self, monkeypatch):
        # PyGObject turns a NULL return from Gio.DesktopAppInfo.new into a
        # TypeError rather than None; is_registered must treat that as "absent"
        # instead of crashing first launch. https://github.com/BlueManCZ/hyprmod/issues/52
        def _raise(_id):
            raise TypeError("constructor returned NULL")

        monkeypatch.setattr(Gio.DesktopAppInfo, "new", staticmethod(_raise))
        assert install.is_registered() is False


class TestPinExecToBinary:
    @pytest.mark.parametrize(
        "binary",
        [
            "/home/user/.local/bin/attune",
            "/home/my user/bin/attune",
            "/home/my$dir/attune",
            "/home/back\\slash/attune",
            '/home/qu"ote/attune',
            "/home/tick`s/attune",
        ],
    )
    def test_written_exec_line_parses_back_to_the_binary(self, tmp_path, monkeypatch, binary):
        # Reserved characters need escaping twice over: once for Exec argument
        # quoting, once for the key file value the desktop reads it out of.
        monkeypatch.setattr(install.shutil, "which", lambda _: binary)
        path = _desktop_file(tmp_path)

        install._pin_exec_to_binary(path)

        key_file = GLib.KeyFile()
        key_file.load_from_file(str(path), GLib.KeyFileFlags.NONE)
        exec_value = key_file.get_string("Desktop Entry", "Exec")
        assert GLib.shell_parse_argv(exec_value)[1] == [binary]

    def test_leaves_file_alone_when_binary_is_not_on_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(install.shutil, "which", lambda _: None)
        path = _desktop_file(tmp_path)

        install._pin_exec_to_binary(path)

        assert path.read_text() == DESKTOP_TEXT


class TestInstallUserFiles:
    def test_installed_entry_points_at_the_binary(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(install.shutil, "which", lambda _: "/opt/attune/bin/attune")

        placed = install.install_user_files(quiet=True)

        desktop = tmp_path / "applications" / install.DESKTOP_FILE
        assert desktop in placed
        assert "Exec=/opt/attune/bin/attune\n" in desktop.read_text()

    def test_install_and_uninstall_leave_upstream_assets_untouched(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(install.shutil, "which", lambda _: None)
        upstream_files = [
            tmp_path / "applications/io.github.bluemancz.hyprmod.desktop",
            tmp_path / "metainfo/io.github.bluemancz.hyprmod.metainfo.xml",
            tmp_path / "icons/hicolor/scalable/apps/io.github.bluemancz.hyprmod.svg",
        ]
        for path in upstream_files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("upstream sentinel")

        placed = install.install_user_files(quiet=True)
        assert len(placed) == 3
        assert all("io.github.jdawson.Attune" in path.name for path in placed)

        assert install.uninstall_user_files(quiet=True) == placed
        assert all(not path.exists() for path in placed)
        assert all(path.read_text() == "upstream sentinel" for path in upstream_files)


class TestEnsureRegistered:
    def test_does_not_register_when_only_upstream_binary_exists(self, monkeypatch):
        monkeypatch.setattr(install, "is_registered", lambda: False)
        monkeypatch.setattr(
            install.shutil, "which", lambda name: "/usr/bin/hyprmod" if name == "hyprmod" else None
        )
        calls = []
        monkeypatch.setattr(install, "install_user_files", lambda **kwargs: calls.append(kwargs))

        install.ensure_registered_silently()

        assert calls == []
