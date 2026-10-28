"""About dialog using the standard GNOME ``Adw.AboutDialog``.

Presents version, license, and upstream credits.
Attached to the ``win.show-about`` action, which is
registered in ``HyprModWindow._build_ui`` and exposed through the primary
menu on every page header.
"""

from importlib.metadata import PackageNotFoundError, version

from gi.repository import Adw, Gtk
from hyprland_schema import HYPRLAND_VERSION

from hyprmod.constants import APPLICATION_ID

APPLICATION_NAME = "Attune"
DEVELOPER_NAME = "jdawson"
COPYRIGHT = "© 2026 Ivo Šmerek"
COMMENTS = "A native GTK4/libadwaita settings app for Hyprland, forked from HyprMod"

# Adw.AboutDialog renders entries in the ``developers`` list as clickable
# links when they match the "Name URL" format. Keep the handle in the URL
# so users can reach the author's GitHub profile from the Credits tab.
DEVELOPERS = ["Ivo Šmerek https://github.com/BlueManCZ"]


def build_about_dialog(running_hyprland_version: str | None = None) -> Adw.AboutDialog:
    """Construct the About dialog for the application.

    *running_hyprland_version* is the version string reported by the live
    compositor (e.g. ``"0.54.3"``). When provided, it's shown in the main
    description; when omitted (Hyprland offline), the bundled schema
    version is shown instead so users still have a version reference.
    """
    try:
        app_version = version("attune")
    except PackageNotFoundError:
        app_version = "unknown"

    # hyprland_schema keys versions by the GitHub tag (``vX.Y.Z``) while the
    # live compositor reports without the prefix. Strip so both numbers
    # display consistently.
    schema_version = HYPRLAND_VERSION.removeprefix("v")
    running = running_hyprland_version.removeprefix("v") if running_hyprland_version else None

    if running:
        hyprland_line = f"Hyprland {running}"
    else:
        hyprland_line = f"Hyprland schema: {schema_version} (bundled)"

    # debug_info goes into the Troubleshooting section. Give bug reporters
    # both numbers unambiguously, regardless of detection state.
    debug_info = (
        f"{APPLICATION_NAME} {app_version}\n"
        f"Hyprland (running): {running or 'not detected'}\n"
        f"Hyprland schema (bundled): {schema_version}"
    )

    return Adw.AboutDialog(
        application_name=APPLICATION_NAME,
        application_icon=APPLICATION_ID,
        version=app_version,
        developer_name=DEVELOPER_NAME,
        developers=DEVELOPERS,
        copyright=COPYRIGHT,
        license_type=Gtk.License.GPL_3_0,
        comments=f"{COMMENTS}\n\n{hyprland_line}",
        debug_info=debug_info,
    )
