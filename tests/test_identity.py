"""Attune's public identity must not reuse upstream desktop or preference IDs."""

import subprocess
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from gi.repository import Gio

from hyprmod.constants import APPLICATION_ID
from hyprmod.data import bundled_data_dir
from hyprmod.ui import about

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_ID = "io.github.bluemancz.hyprmod"


class TestIdentity:
    def test_distribution_preserves_internal_package(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        assert project["project"]["name"] == "attune"
        assert project["project"]["scripts"] == {"attune": "hyprmod.main:main"}
        assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["hyprmod"]

    def test_desktop_metainfo_and_icons_match_application_id(self):
        assert APPLICATION_ID == "io.github.jdawson.Attune"
        desktop = bundled_data_dir("applications", f"{APPLICATION_ID}.desktop").read_text()
        assert "Name=Attune\n" in desktop
        assert "Exec=attune\n" in desktop
        assert f"Icon={APPLICATION_ID}\n" in desktop
        assert f"StartupWMClass={APPLICATION_ID}\n" in desktop
        assert UPSTREAM_ID not in desktop

        metainfo = ET.parse(bundled_data_dir("metainfo", f"{APPLICATION_ID}.metainfo.xml"))
        assert metainfo.findtext("id") == APPLICATION_ID
        assert metainfo.findtext("launchable") == f"{APPLICATION_ID}.desktop"
        assert metainfo.findtext("name") == "Attune"
        assert metainfo.findtext("provides/binary") == "attune"
        assert metainfo.findtext("project_license") == "GPL-3.0-or-later"
        assert metainfo.findall("url") == []

        icon = Path("icons/hicolor/scalable/apps") / f"{APPLICATION_ID}.svg"
        assert bundled_data_dir(str(icon)).read_bytes() == (ROOT / "data" / icon).read_bytes()
        assert not bundled_data_dir(str(icon.with_name(f"{UPSTREAM_ID}.svg"))).exists()

    def test_schema_has_independent_namespace(self, tmp_path):
        schema = bundled_data_dir(f"{APPLICATION_ID}.gschema.xml")
        (tmp_path / schema.name).write_bytes(schema.read_bytes())
        subprocess.run(["glib-compile-schemas", "--strict", str(tmp_path)], check=True)
        source = Gio.SettingsSchemaSource.new_from_directory(str(tmp_path), None, False)
        compiled = source.lookup(APPLICATION_ID, False)
        if compiled is None:
            pytest.fail("Attune schema was not compiled")
        assert compiled.get_path() == "/io/github/jdawson/Attune/"
        assert source.lookup(UPSTREAM_ID, False) is None

    def test_about_uses_attune_version_and_keeps_upstream_credit(self, monkeypatch):
        versions = []
        monkeypatch.setattr(about, "version", lambda name: versions.append(name) or "0.5.0")
        properties = {}
        monkeypatch.setattr(about.Adw, "AboutDialog", lambda **kwargs: properties.update(kwargs))

        about.build_about_dialog("0.55.0")

        assert versions == ["attune"]
        assert properties["application_name"] == "Attune"
        assert properties["application_icon"] == APPLICATION_ID
        assert properties["version"] == "0.5.0"
        assert "Attune 0.5.0" in properties["debug_info"]
        assert "Ivo" in properties["copyright"]
        assert "website" not in properties
        assert "issue_url" not in properties

    def test_about_version_is_unknown_without_distribution(self, monkeypatch):
        def missing_version(name):
            raise about.PackageNotFoundError(name)

        monkeypatch.setattr(about, "version", missing_version)
        properties = {}
        monkeypatch.setattr(about.Adw, "AboutDialog", lambda **kwargs: properties.update(kwargs))

        about.build_about_dialog()

        assert properties["version"] == "unknown"
