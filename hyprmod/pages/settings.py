"""Read-only output and integration information."""

import os
from pathlib import Path

from gi.repository import Adw, Gtk

from hyprmod.core.bindings import BASENAME
from hyprmod.core.input import BASENAME as INPUT_BASENAME
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
                "Ctrl+S opens Pending Changes. Appearance/displays, Input and keybindings have "
                "independent explicitly reviewed Save actions, not an atomic Save Everything."
            ),
        )
        pair = self._window.pair_layout
        if pair is None:
            group.add(
                Gtk.Label(
                    label=f"Appearance / displays: {self._window.config_path}",
                    xalign=0,
                    wrap=True,
                    selectable=True,
                )
            )
        else:
            group.add(
                Adw.ActionRow(
                    title="Canonical-pair editor",
                    subtitle="Appearance is portable; displays are machine-local. "
                    "Health and Backups diagnose legacy v1 only, not this pair.",
                )
            )
            group.add(
                Gtk.Label(
                    label=f"Installation registry: {pair.evidence.registry.path.lexical_path}\n"
                    f"Resolved: {pair.evidence.registry.path.resolved_path}",
                    xalign=0,
                    wrap=True,
                    selectable=True,
                )
            )
            for route in pair.evidence.routes:
                group.add(
                    Gtk.Label(
                        label=f"{route.scope.value.title()}: {route.file.path.lexical_path}\n"
                        f"Resolved: {route.file.path.resolved_path}",
                        xalign=0,
                        wrap=True,
                        selectable=True,
                    )
                )
        group.add(
            Gtk.Label(
                label="Keybindings have a separate fixed output: "
                + str(
                    (
                        Path(pair.evidence.config_root)
                        if pair is not None
                        else Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
                    )
                    / "hypr"
                    / BASENAME
                )
                + "\nFirst load: manually add dofile with this exact absolute path to your own "
                "Hyprland Lua entrypoint after your defaults. No includes are inserted. "
                "Saving keybindings does not save appearance/displays, apply, unbind or reload.",
                xalign=0,
                wrap=True,
                selectable=True,
            )
        )
        input_path = (
            (
                Path(pair.evidence.config_root)
                if pair is not None
                else Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            )
            / "hypr"
            / INPUT_BASENAME
        )
        group.add(
            Gtk.Label(
                label=f"Input has a separate fixed output: {input_path}\n"
                "Draft only: no live preview. Only after this file exists, manually add dofile "
                "with this exact absolute path to your own Lua entrypoint after your defaults, "
                "outside Attune. Attune never inserts an include or sends Input IPC. "
                "Linux Git/Stow routes may resolve to a Git source: this remains separate from "
                "appearance output, and Attune does not stage it. "
                "Watchers may reload automatically "
                "only if already loaded; saving is not proof of runtime loading.",
                xalign=0,
                wrap=True,
                selectable=True,
                use_markup=False,
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
                    "Hand-authored bindings, workspaces, autostart, environment, and rules "
                    "are not edited. Input and keybindings use separate dedicated outputs. "
                    "No automatic saves, profiles, migrations, or startup reloads. "
                    "Output-path editing is intentionally unavailable."
                ),
            )
        )
        content_box.append(group)
        return toolbar
