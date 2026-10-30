"""Attune application entry point."""

import os
import signal
import sys
import threading
import weakref
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk
from hyprland_config import ParseError

from hyprmod.constants import APPLICATION_ID
from hyprmod.core import config, scoped_recovery
from hyprmod.install import install_user_files, uninstall_user_files
from hyprmod.pages.backups import BackupsPage
from hyprmod.pages.health import HealthPage
from hyprmod.pages.scope_recovery import ScopeRecoveryPage
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


class RecoveryWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._restore_owner: str | None = None
        self.connect("close-request", lambda *_args: self.restore_writing)

    @property
    def restore_writing(self) -> bool:
        return self._restore_owner is not None

    def restore_permission(self) -> None:
        if self.restore_writing:
            raise ValueError("Another restoration or recovery owns this window")

    def begin_restore(self, owner: str) -> None:
        self.restore_permission()
        self._restore_owner = owner

    def finish_restore(self, owner: str, invalidate: bool) -> None:
        # Legacy Backups also finishes refused attempts; only the owner can release.
        if self._restore_owner != owner:
            return
        if invalidate:
            config.invalidate_cache()
        self._restore_owner = None


class HyprModApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APPLICATION_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._config_error_window: Adw.ApplicationWindow | None = None
        self._recovery_backups: BackupsPage | None = None
        self._integration_shown = False
        self._startup_cancel: threading.Event | None = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        icon_dir = str(Path(__file__).resolve().parent / "data" / "icons")
        display = Gdk.Display.get_default()
        if display is not None:
            theme = Gtk.IconTheme.get_for_display(display)
            paths = theme.get_search_path() or []
            theme.set_search_path([icon_dir, *paths])

    def do_activate(self):
        if self._config_error_window is not None:
            self._config_error_window.present()
            return
        win = self.props.active_window
        if isinstance(win, HyprModWindow):
            win.present()
            return
        self._check_startup()

    def _check_startup(self) -> None:
        if self._startup_cancel is not None:
            return
        if isinstance(self._config_error_window, RecoveryWindow):
            if self._config_error_window.restore_writing:
                self._config_error_window.present()
                return
        checking = Adw.ApplicationWindow(application=self, title="Attune")
        checking.set_default_size(700, 500)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(
            EmptyState(
                title="Checking Attune Layout",
                description="Read-only startup assessment. No state is created or repaired.",
                icon_name="system-search-symbolic",
            )
        )
        checking.set_content(view)
        self._dismiss_config_error()
        self._config_error_window = checking
        cancel = threading.Event()
        self._startup_cancel = cancel

        def closed(
            *_args, cancel=cancel, app_ref=weakref.ref(self), window_ref=weakref.ref(checking)
        ) -> bool:
            cancel.set()
            app = app_ref()
            if app is not None:
                if app._startup_cancel is cancel:
                    app._startup_cancel = None
                if app._config_error_window is window_ref():
                    app._config_error_window = None
            return False

        checking.connect("close-request", closed)
        checking.connect("destroy", closed)
        checking.connect("unrealize", closed)
        config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))

        def complete(
            assessment: scoped_recovery.LayoutAssessment | None, error: str | None
        ) -> bool:
            if self._startup_cancel is not cancel or cancel.is_set():
                return GLib.SOURCE_REMOVE
            self._startup_cancel = None
            if assessment is not None and assessment.mode == "legacy-clear" and error is None:
                self._open_editor()
            else:
                self._show_config_error(
                    error
                    or "Scoped evidence requires explicit recovery. The legacy editor is locked.",
                    assessment=assessment,
                )
            return GLib.SOURCE_REMOVE

        def assess() -> None:
            try:
                assessment = scoped_recovery.run_assess(
                    config_root, state_root, cancel_event=cancel, timeout=15
                )
            except Exception as exc:
                GLib.idle_add(complete, None, str(exc))
            else:
                GLib.idle_add(complete, assessment, None)

        checking.present()
        try:
            threading.Thread(target=assess, daemon=False).start()
        except Exception as exc:
            complete(None, str(exc))

    def _open_editor(self) -> None:
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

    def _show_config_error(
        self, message: str, *, assessment: scoped_recovery.LayoutAssessment | None = None
    ) -> None:
        """Put the config-error window up in place of the main window.

        Built before the previous one goes so the app never drops to zero
        windows, which would quit it mid-retry.
        """
        error_window = RecoveryWindow(application=self, title="Attune")
        error_window.set_default_size(700, 500)
        view = Adw.ToolbarView()
        recovery_header = Adw.HeaderBar()
        view.add_top_bar(recovery_header)
        stack = Gtk.Stack()
        stack.add_named(view, "recovery")

        health_page = HealthPage(config.managed_path())
        health_page.bind_lifecycle(error_window)
        backups_page = BackupsPage(
            config.managed_path(),
            restore_permission=error_window.restore_permission,
            begin_restore=lambda: error_window.begin_restore("backups"),
            finish_restore=lambda invalidate: error_window.finish_restore("backups", invalidate),
        )
        backups_page.bind_lifecycle(error_window)
        scope_page = ScopeRecoveryPage(
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")),
            Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")),
            restore_permission=error_window.restore_permission,
            begin_restore=lambda: error_window.begin_restore("scope"),
            finish_restore=lambda invalidate: error_window.finish_restore("scope", invalidate),
        )
        scope_page.bind_lifecycle(error_window)

        def scope_assessed(result: scoped_recovery.LayoutAssessment) -> None:
            if result.mode != "legacy-clear":
                config.invalidate_cache()

        scope_page.on_assessment = scope_assessed

        def open_scope() -> None:
            stack.set_visible_child_name("scope-recovery")
            scope_page.ensure_loaded()

        scope_header = Adw.HeaderBar()
        scope_header.set_title_widget(Adw.WindowTitle(title="Scope Recovery"))
        back = Gtk.Button(label="Back")
        back.connect("clicked", lambda _button: stack.set_visible_child_name("recovery"))
        scope_header.pack_start(back)
        stack.add_named(scope_page.build(scope_header), "scope-recovery")
        if assessment is not None:
            scope_page.seed_assessment(assessment)
        scope_button = Gtk.Button(label="Scope Recovery")
        scope_button.connect("clicked", lambda _button: open_scope())
        recovery_header.pack_start(scope_button)

        def open_backups() -> None:
            if stack.get_child_by_name("backups") is None:
                header = Adw.HeaderBar()
                header.set_title_widget(Adw.WindowTitle(title="Legacy Backups (v1)"))
                back = Gtk.Button(label="Back")
                back.connect("clicked", lambda _button: stack.set_visible_child_name("recovery"))
                header.pack_start(back)
                stack.add_named(backups_page.build(header), "backups")
            stack.set_visible_child_name("backups")
            backups_page.ensure_loaded()

        backups_button = Gtk.Button(label="Legacy Backups (v1)")
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
                title="Attune Recovery",
                description=f"{GLib.markup_escape_text(message)}\n\nRead-only shell. "
                "Recovery requires a separate review "
                "and explicit commit. Nothing is activated or migrated automatically.",
                icon_name="dialog-warning-symbolic",
                primary_action=("Retry Startup Check", self._check_startup),
                secondary_action=("Open Health", open_health),
            )
        )
        error_window.set_content(stack)
        self._dismiss_config_error()
        self._recovery_backups = backups_page
        self._config_error_window = error_window

        def closed(*_args) -> None:
            if self._config_error_window is error_window:
                self._config_error_window = None
                self._recovery_backups = None

        error_window.connect("destroy", closed)
        error_window.connect("unrealize", closed)
        error_window.present()

    def _dismiss_config_error(self) -> None:
        if (
            isinstance(self._config_error_window, RecoveryWindow)
            and self._config_error_window.restore_writing
        ):
            return
        if self._startup_cancel is not None:
            self._startup_cancel.set()
            self._startup_cancel = None
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
