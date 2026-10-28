"""Open Attune's GSettings store without migrating configuration files."""

import subprocess
from pathlib import Path

from gi.repository import Gio

from hyprmod.constants import APPLICATION_ID
from hyprmod.core import config
from hyprmod.data import bundled_data_dir

# The GSettings schema id matches our application id by convention.
SETTINGS_SCHEMA_ID = APPLICATION_ID


def _recompile_schemas_if_stale(schema_dir: Path) -> None:
    """Recompile GSettings schemas if the compiled file is stale or missing."""
    xml_files = list(schema_dir.glob("*.gschema.xml"))
    if not xml_files:
        return
    compiled = schema_dir / "gschemas.compiled"
    latest_xml_mtime = max(xml.stat().st_mtime for xml in xml_files)
    if not compiled.exists() or compiled.stat().st_mtime < latest_xml_mtime:
        subprocess.run(["glib-compile-schemas", str(schema_dir)], check=False)


def open_settings() -> Gio.Settings | None:
    """Open hyprmod's GSettings store, or ``None`` when the schema is missing."""
    schema_dir = bundled_data_dir()
    _recompile_schemas_if_stale(schema_dir)
    schema_source = Gio.SettingsSchemaSource.new_from_directory(
        str(schema_dir),
        Gio.SettingsSchemaSource.get_default(),
        False,
    )
    schema_obj = schema_source.lookup(SETTINGS_SCHEMA_ID, False)
    if schema_obj is None:
        return None
    return Gio.Settings.new_full(schema_obj, None, None)


def apply_saved_config_path(settings: Gio.Settings | None) -> None:
    """Use Attune's fixed Lua destination, ignoring legacy path preferences.

    Startup must never convert, create, or repoint a user's configuration.
    """
    if settings is not None:
        config.set_managed_path(None)
