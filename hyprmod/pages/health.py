"""Read-only diagnostics, reusable without an editor window."""

import threading
import weakref
from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from hyprmod.core import health
from hyprmod.core.diagnostics import build_diagnostics_report
from hyprmod.ui import clear_children, make_page_layout


class HealthPage:
    def __init__(self, output_path: Path):
        self._output_path = output_path
        self._snapshot: health.HealthSnapshot | None = None
        self._started = False
        self._loading = False
        self._closed = False
        self._stale = False
        self._cancel_event = threading.Event()
        self._launch_cancel = Gio.Cancellable()

    def build(self, header: Adw.HeaderBar) -> Adw.ToolbarView:
        toolbar, _, content, _ = make_page_layout(header=header)
        self._toolbar = toolbar
        self._refresh_button = Gtk.Button(label="Refresh")
        self._refresh_button.connect("clicked", lambda _button: self.refresh())
        header.pack_end(self._refresh_button)
        self._preview_button = Gtk.Button(label="Preview Report", sensitive=False)
        self._preview_button.connect("clicked", lambda _button: self.preview_report())
        header.pack_end(self._preview_button)
        actions = Gtk.Box(spacing=12)
        for label, folder in (("Open Output", False), ("Open Folder", True)):
            button = Gtk.Button(label=label)
            button.connect(
                "clicked", lambda _button, folder=folder: self.open_output(folder=folder)
            )
            actions.append(button)
        content.append(actions)
        self._local_error = Gtk.Label(xalign=0, wrap=True, selectable=True, visible=False)
        content.append(self._local_error)
        self._status = Gtk.Label(label="Not observed yet", xalign=0, wrap=True, selectable=True)
        content.append(self._status)
        content.append(
            Gtk.Label(
                label="Read-only observations. Output presence does not establish runtime loading. "
                "Backup candidates are not validated as restorable.",
                xalign=0,
                wrap=True,
            )
        )
        self._checks = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.append(self._checks)
        return toolbar

    def preview_report(self) -> None:
        if self._closed or self._loading or self._snapshot is None or not self._snapshot.checks:
            return
        parent = self._toolbar.get_root()
        if not isinstance(parent, Gtk.Window):
            return
        report = build_diagnostics_report(self._snapshot, stale=self._stale)
        dialog = Adw.Dialog(title="Diagnostics Preview", content_width=640, content_height=480)
        layout = Adw.ToolbarView()
        header = Adw.HeaderBar()
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _button: dialog.close())
        header.pack_start(cancel)
        copy = Gtk.Button(label="Copy Report")

        def copy_report(_button: Gtk.Button) -> None:
            if not self._closed:
                dialog.get_clipboard().set(report)
            dialog.close()

        copy.connect("clicked", copy_report)
        header.pack_end(copy)
        layout.add_top_bar(header)
        # Text selection can write GTK's primary clipboard without the Copy action.
        text = Gtk.Label(
            label=report,
            use_markup=False,
            selectable=False,
            wrap=True,
            xalign=0,
            yalign=0,
            css_classes=["monospace"],
        )
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.set_child(text)
        layout.set_content(scroll)
        dialog.set_child(layout)
        dialog.present(parent)

    def open_output(self, *, folder: bool = False) -> None:
        if self._closed:
            return
        self._local_error.set_visible(False)
        path = self._output_path.parent if folder else self._output_path
        file = Gio.File.new_for_path(str(path))
        mime = "inode/directory" if folder else "text/plain"

        def failed(message: str) -> None:
            if not self._closed:
                self._local_error.set_label(message)
                self._local_error.set_visible(True)

        def launched(app: Gio.AppInfo, result: Gio.AsyncResult) -> None:
            try:
                if not app.launch_uris_finish(result):
                    failed("Could not open the selected path. Check your default application.")
            except GLib.Error:
                failed("Could not open the selected path. Check your default application.")

        def associated(_source: object, result: Gio.AsyncResult) -> None:
            if self._closed:
                return
            try:
                app = Gio.AppInfo.get_default_for_type_finish(result)
                if app is None:
                    failed(f"No default {mime} application. Configure one and try again.")
                    return
                app.launch_uris_async([file.get_uri()], None, self._launch_cancel, launched)
            except GLib.Error:
                failed(f"Cannot find or launch a default {mime} application. Configure one.")

        def inspected(source: Gio.File, result: Gio.AsyncResult) -> None:
            if self._closed:
                return
            try:
                info = source.query_info_finish(result)
                expected = Gio.FileType.DIRECTORY if folder else Gio.FileType.REGULAR
                if info.get_file_type() != expected:
                    failed("Select an existing output file or folder. Nothing was created.")
                    return
                Gio.AppInfo.get_default_for_type_async(mime, False, self._launch_cancel, associated)
            except GLib.Error:
                failed("Cannot access the output file or folder. Create or select it, then retry.")

        file.query_info_async(
            "standard::type",
            Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_DEFAULT,
            self._launch_cancel,
            inspected,
        )

    def ensure_loaded(self) -> None:
        if not self._started:
            self.refresh()

    def bind_lifecycle(self, window: Gtk.Window) -> None:
        window.connect("unrealize", self.close)
        window.connect("destroy", self.close)
        application = window.get_application()
        if application is not None:
            # GTK4 destroy() removes even never-realized windows from the application;
            # the widget destroy signal can be delayed until final disposal.
            def removed(app: Gtk.Application, removed_window: Gtk.Window) -> None:
                if removed_window is window:
                    self.close()
                    app.disconnect(handler)

            handler = application.connect("window-removed", removed)

    def refresh(self) -> None:
        if self._closed or self._loading:
            return
        self._started = True
        self._loading = True
        self._refresh_button.set_sensitive(False)
        self._preview_button.set_sensitive(False)
        previous = (
            f" Previous observation: {self._snapshot.observed_at} (stale)."
            if self._snapshot is not None
            else ""
        )
        self._status.set_label(f"Loading health observations...{previous}")
        page_ref = weakref.ref(self)
        path = self._output_path
        cancel_event = self._cancel_event

        def complete(snapshot: health.HealthSnapshot | None, error: str | None) -> bool:
            page = page_ref()
            if page is None or page._closed:
                return GLib.SOURCE_REMOVE
            page._loading = False
            page._refresh_button.set_sensitive(True)
            if snapshot is None:
                page._stale = page._snapshot is not None
                previous = (
                    f" Stale observation retained: {page._snapshot.observed_at}."
                    if page._snapshot is not None
                    else " No observation available."
                )
                page._status.set_label(f"Refresh failed: {error}.{previous}")
            else:
                page._stale = False
                page._snapshot = snapshot
                page._status.set_label(f"Observed: {snapshot.observed_at}")
                clear_children(page._checks)
                for check in snapshot.checks:
                    group = Adw.PreferencesGroup(title=check.title)
                    row = Adw.ActionRow(title=check.status.capitalize())
                    row.set_use_markup(False)
                    row.set_subtitle("\n".join((check.summary, *check.details)))
                    row.set_subtitle_lines(0)
                    group.add(row)
                    page._checks.append(group)
            page._preview_button.set_sensitive(
                page._snapshot is not None and bool(page._snapshot.checks)
            )
            return GLib.SOURCE_REMOVE

        def collect() -> None:
            try:
                snapshot = health.run_snapshot(path, cancel_event=cancel_event)
            except Exception as exc:
                GLib.idle_add(complete, None, str(exc))
            else:
                GLib.idle_add(complete, snapshot, None)

        try:
            threading.Thread(target=collect, daemon=False).start()
        except RuntimeError as exc:
            GLib.idle_add(complete, None, str(exc))

    def close(self, *_args) -> None:
        # No UI join: interpreter shutdown waits for the worker's bounded process cleanup.
        self._closed = True
        self._cancel_event.set()
        self._launch_cancel.cancel()
