"""Attune application entry point."""

import signal
import sys
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk
from hyprland_config import ParseError

from hyprmod.constants import APPLICATION_ID
from hyprmod.core import config
from hyprmod.install import install_user_files, uninstall_user_files
from hyprmod.pages.backups import BackupsPage
from hyprmod.pages.health import HealthPage
from hyprmod.ui import has_cairo_support
from hyprmod.ui.empty_state import EmptyState
from hyprmod.ui.onboarding_dialog import OnboardingDialog
from hyprmod.window import HyprModWindow

CAIRO_MISSING_BODY = (
    "PyGObject's Cairo bindings are missing, so the monitor layout, the bezier "
    "curve editor, and the animation preview will show up as empty boxes.\n\n"
    "Install them with your package manager: python-cairo on Arch, "
    "python3-gi-cairo on Debian and Ubuntu."
)


class HyprModApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APPLICATION_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._config_error_window: Adw.ApplicationWindow | None = None
        self._recovery_backups: BackupsPage | None = None
        self._integration_shown = False

    def do_startup(self):
        Adw.Application.do_startup(self)
        icon_dir = str(Path(__file__).resolve().parent / "data" / "icons")
        display = Gdk.Display.get_default()
        if display is not None:
            theme = Gtk.IconTheme.get_for_display(display)
            paths = theme.get_search_path() or []
            theme.set_search_path([icon_dir, *paths])

    def do_activate(self):
        if self._recovery_backups is not None and self._recovery_backups.restore_writing:
            if self._config_error_window is not None:
                self._config_error_window.present()
            return
        win = self.props.active_window
        if not isinstance(win, HyprModWindow):
            existing = set(self.get_windows())
            try:
                win = HyprModWindow(application=self)
            except (OSError, ValueError, ParseError) as exc:
                # ``application=self`` registers the window with the app
                # before ``__init__`` reaches the config read, so a failed
                # one is already in the window list. Left there it answers
                # ``active_window`` on the next activation and presents as
                # an empty window over a swallowed traceback.
                for window in set(self.get_windows()) - existing:
                    window.destroy()
                self._show_config_error(str(exc))
                return
        self._dismiss_config_error()

        # Do not stack integration guidance over an install problem.
        if not has_cairo_support():
            dialog = Adw.AlertDialog(heading="Missing Cairo Bindings", body=CAIRO_MISSING_BODY)
            dialog.add_response("close", "Close")
            dialog.present(win)
        elif not self._integration_shown:
            self._integration_shown = True
            OnboardingDialog().present(win)

        win.present()

    def _show_config_error(self, message: str) -> None:
        """Put the config-error window up in place of the main window.

        Built before the previous one goes so the app never drops to zero
        windows, which would quit it mid-retry.
        """
        error_window = Adw.ApplicationWindow(application=self, title="Attune")
        error_window.set_default_size(700, 500)
        view = Adw.ToolbarView()
        recovery_header = Adw.HeaderBar()
        view.add_top_bar(recovery_header)
        stack = Gtk.Stack()
        stack.add_named(view, "recovery")

        health_page = HealthPage(config.managed_path())
        health_page.bind_lifecycle(error_window)
        backups_page = BackupsPage(config.managed_path())
        backups_page.bind_lifecycle(error_window)

        def open_backups() -> None:
            if stack.get_child_by_name("backups") is None:
                header = Adw.HeaderBar()
                header.set_title_widget(Adw.WindowTitle(title="Backups"))
                back = Gtk.Button(label="Back")
                back.connect("clicked", lambda _button: stack.set_visible_child_name("recovery"))
                header.pack_start(back)
                stack.add_named(backups_page.build(header), "backups")
            stack.set_visible_child_name("backups")
            backups_page.ensure_loaded()

        backups_button = Gtk.Button(label="Backups")
        backups_button.connect("clicked", lambda _button: open_backups())
        recovery_header.pack_end(backups_button)

        def open_health() -> None:
            if stack.get_child_by_name("health") is None:
                header = Adw.HeaderBar()
                header.set_title_widget(Adw.WindowTitle(title="Health"))
                back = Gtk.Button(label="Back")
                back.connect("clicked", lambda _button: stack.set_visible_child_name("recovery"))
                header.pack_start(back)
                stack.add_named(health_page.build(header), "health")
            stack.set_visible_child_name("health")
            health_page.ensure_loaded()

        view.set_content(
            EmptyState(
                title="Cannot Read Attune Output",
                description=f"{message}\n\nCheck the managed output file, then try again.",
                icon_name="dialog-warning-symbolic",
                primary_action=("Try Again", self.activate),
                secondary_action=("Open Health", open_health),
            )
        )
        error_window.set_content(stack)
        self._dismiss_config_error()
        self._recovery_backups = backups_page
        self._config_error_window = error_window
        error_window.present()

    def _dismiss_config_error(self) -> None:
        if self._recovery_backups is not None and self._recovery_backups.restore_writing:
            return
        if self._config_error_window is not None:
            self._config_error_window.destroy()
            self._config_error_window = None
        self._recovery_backups = None


def main():
    args = sys.argv[1:]
    if "--install" in args:
        install_user_files()
        return 0
    if "--uninstall" in args:
        uninstall_user_files()
        return 0
    # Positional commands must not reach the dormant profile CLI.
    if args and not args[0].startswith("-"):
        print(
            "Attune has no profile CLI. Open the app to review appearance changes.",
            file=sys.stderr,
        )
        return 2

    app = HyprModApp()

    # Route SIGINT/SIGTERM through the GLib main loop so Ctrl-C from the
    # terminal (or `kill`) shuts the app down cleanly. Python's default
    # SIGINT handler can't interrupt GLib's C-level loop — the exception
    # only surfaces when control next returns to Python, which typically
    # produces a stray traceback after the UI has already been frozen.
    def _on_signal(*_args) -> bool:
        windows = app.get_windows()
        if not windows:
            app.quit()
        for window in windows:
            window.close()
        # Keep the main loop alive if a monitor preview vetoed closure.
        return GLib.SOURCE_CONTINUE

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, _on_signal)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _on_signal)

    return app.run(sys.argv)


if __name__ == "__main__":
    main()
