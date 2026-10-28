"""Read-only output and integration information."""

from gi.repository import Adw

from hyprmod.ui import make_page_layout


class SettingsPage:
    def __init__(self, window):
        self._window = window

    def build(self, header: Adw.HeaderBar) -> Adw.ToolbarView:
        toolbar, _, content_box, _ = make_page_layout(header=header)
        group = Adw.PreferencesGroup(
            title="Attune Integration",
            description=(
                "Attune previews appearance, displays, and motion live. "
                "Ctrl+S opens Pending Changes; only Save Reviewed Changes writes to disk."
            ),
        )
        group.add(Adw.ActionRow(title="Managed output", subtitle=self._window.config_path))
        group.add(
            Adw.ActionRow(
                title="Manual integration",
                subtitle=(
                    "After your first reviewed save, explicitly load the managed Lua file "
                    "from your own Hyprland Lua entrypoint using dofile with its absolute path. "
                    "Place it after your appearance defaults. Attune never inserts this for you."
                ),
            )
        )
        group.add(
            Adw.ActionRow(
                title="Your configuration stays yours",
                subtitle=(
                    "Bindings, workspaces, autostart, environment, and rules are not edited. "
                    "No automatic saves, profiles, migrations, or startup reloads. "
                    "Output-path editing is intentionally unavailable."
                ),
            )
        )
        content_box.append(group)
        return toolbar
