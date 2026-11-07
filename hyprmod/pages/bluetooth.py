"""Explicit handoff to Blueman, separate from compositor configuration."""

from gi.repository import Adw, Gio, GLib, Gtk

from hyprmod.ui import make_page_layout


class BluetoothPage:
    def build(self, header: Adw.HeaderBar) -> Adw.ToolbarView:
        toolbar, _, content, _ = make_page_layout(header=header)
        group = Adw.PreferencesGroup(
            title="Bluetooth Devices",
            description="Use Blueman to discover, pair and connect Bluetooth devices in a "
            "separate window. Put your device in pairing mode, open the manager, then "
            "search for and select your device.",
        )
        row = Adw.ActionRow(
            title="Blueman Device Manager",
            subtitle="Bluetooth actions take effect through Blueman, not Pending Changes "
            "or Save Reviewed Input. Attune does not start Bluetooth services or install packages.",
        )
        row.set_subtitle_lines(0)
        button = Gtk.Button(label="Open Bluetooth Manager", valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda _button: self.open_manager())
        row.add_suffix(button)
        row.set_activatable_widget(button)
        group.add(row)
        content.append(group)
        self._status = Gtk.Label(xalign=0, wrap=True, selectable=True, visible=False)
        content.append(self._status)
        return toolbar

    def open_manager(self) -> None:
        executable = GLib.find_program_in_path("blueman-manager")
        if executable is None:
            message = (
                "blueman-manager was not found on PATH. Install the blueman package using your "
                "system package manager (Arch/CachyOS: sudo pacman -S blueman), then try again."
            )
        else:
            try:
                Gio.Subprocess.new([executable], Gio.SubprocessFlags.NONE)
            except GLib.Error as exc:
                message = (
                    f"Could not open Blueman: {exc.message}. Check the installation and retry."
                )
            else:
                message = (
                    "Blueman launch requested. Use its window to pair and connect devices. "
                    "If it does not open, run blueman-manager in a terminal to see its errors. "
                    "Launching does not confirm Bluetooth service or device status."
                )
        self._status.set_label(message)
        self._status.set_visible(True)
