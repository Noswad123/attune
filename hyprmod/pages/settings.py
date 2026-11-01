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
        pair = self._window.pair_layout
        if pair is None:
            group.add(Adw.ActionRow(title="Managed output", subtitle=self._window.config_path))
        else:
            group.add(
                Adw.ActionRow(
                    title="Canonical-pair editor",
                    subtitle="Appearance is portable; displays are machine-local. "
                    "Health and Backups diagnose legacy v1 only, not this pair.",
                )
            )
            group.add(
                Adw.ActionRow(
                    title="Installation registry",
                    subtitle=f"Registered: {pair.evidence.registry.path.lexical_path}\n"
                    f"Resolved: {pair.evidence.registry.path.resolved_path}",
                )
            )
            for route in pair.evidence.routes:
                group.add(
                    Adw.ActionRow(
                        title=route.scope.value.title(),
                        subtitle=f"Registered: {route.file.path.lexical_path}\n"
                        f"Resolved: {route.file.path.resolved_path}",
                    )
                )
        group.add(
            Adw.ActionRow(
                title="Manual integration",
                subtitle=(
                    "Explicitly load the registered managed Lua output(s) "
                    "from your own Hyprland Lua entrypoint using dofile with its absolute path. "
                    "Place them after your defaults. Attune never inserts this for you. "
                    "Disk state does not prove runtime loading. No reload IPC is sent on Save."
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
