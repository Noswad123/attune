"""Dedicated saved/draft keybindings and a read-only runtime inventory."""

import os
import threading
import weakref
from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path

from gi.repository import Adw, GLib, Gtk
from hyprland_socket import Bind as RawBind

from hyprmod.binds import (
    DISPATCHER_CATEGORIES,
    OPAQUE_LUA_DISPATCHER,
    categorize_bind,
    format_bind_action,
    live_bind_to_data,
)
from hyprmod.binds.dialog import BindEditDialog
from hyprmod.core import bindings
from hyprmod.core.bindings import BindingsBaseline, BindingsConfig
from hyprmod.core.ownership import SavedList
from hyprmod.core.pending import PendingChange
from hyprmod.core.undo import SavedListSnapshot
from hyprmod.pages.section import SectionPage
from hyprmod.ui import clear_children, make_inline_hint, make_page_layout
from hyprmod.ui.icons import BINDS_ICON


class ManagedBindingsPage(SectionPage):
    def __init__(self, window, on_dirty_changed=None, push_undo=None):
        super().__init__(window, on_dirty_changed, push_undo)
        self.baseline: BindingsBaseline | None = None
        self.load_error: str | None = None
        self.locked = False
        self._owned = SavedList[str]([], key=str)
        self._runtime: tuple[RawBind, ...] = ()
        self._inventory_error: str | None = "Not observed"
        self._started = False
        self._loading = False
        self._closed = False
        self._generation = 0
        self._cancel = threading.Event()
        self._content_box: Gtk.Box | None = None
        self._add_button: Gtk.Button | None = None
        self._search_term = ""
        self._config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self._state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))

    def build(self, header: Adw.HeaderBar | None = None) -> Adw.ToolbarView:
        header = header or Adw.HeaderBar()
        self._add_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add keybinding")
        self._add_button.connect("clicked", lambda _button: self._open_dialog())
        header.pack_start(self._add_button)
        toolbar, page_box, self._content_box, _scrolled = make_page_layout(header=header)
        search = Gtk.SearchEntry(
            placeholder_text="Search shortcuts, actions, categories or origins"
        )
        search.connect("search-changed", self._search_changed)
        page_box.prepend(search)
        toolbar.connect("map", lambda _widget: self.ensure_loaded())
        self._rebuild_list()
        return toolbar

    def bind_lifecycle(self, window):
        window.connect("unrealize", self.close)
        window.connect("destroy", self.close)
        application = window.get_application()
        if application is not None:

            def removed(app, removed_window):
                if removed_window is window:
                    self.close()
                    app.disconnect(handler)

            handler = application.connect("window-removed", removed)

    def close(self, *_args):
        self._closed = True
        self._generation += 1
        self._cancel.set()

    def ensure_loaded(self):
        if self._started or self._loading or self._closed or self.locked:
            return
        self._started = self._loading = True
        generation, cancel = self._generation, self._cancel
        config_root, state_root = self._config_root, self._state_root
        hypr = self._window.hypr
        page_ref = weakref.ref(self)
        self._rebuild_list()

        def complete(baseline, error, runtime, inventory_error):
            page = page_ref()
            if page is None:
                return GLib.SOURCE_REMOVE
            page._loading = False
            if page._closed or generation != page._generation or cancel.is_set():
                return GLib.SOURCE_REMOVE
            page._runtime = runtime
            page._inventory_error = inventory_error
            if not page.locked:
                if error is not None:
                    page.invalidate(error)
                else:
                    page.baseline = baseline
                    page._owned = SavedList(list(baseline.config.lines), key=str)
            page._rebuild_list()
            return GLib.SOURCE_REMOVE

        def collect():
            baseline, error = None, None
            runtime, inventory_error = (), None
            try:
                baseline = bindings.run_observe(config_root, state_root, cancel_event=cancel)
                if type(baseline) is not BindingsBaseline or (
                    baseline.config_root,
                    baseline.state_root,
                ) != (str(config_root), str(state_root)):
                    raise ValueError("Unexpected bindings observation context")
            except Exception as exc:
                error = str(exc) or type(exc).__name__
            if not cancel.is_set():
                try:
                    if hypr.online is not True:
                        raise ValueError("Compositor is offline or availability is unknown")
                    observed = hypr.get_binds()
                    # The installed client also returns [] on IPC failure.
                    if not observed:
                        raise ValueError("No runtime entries reported; availability is unverified")
                    if len(observed) > 10000 or any(type(b) is not RawBind for b in observed):
                        raise ValueError("Unsupported or oversized runtime inventory")
                    runtime = tuple(observed)
                except Exception as exc:
                    inventory_error = str(exc) or type(exc).__name__
            GLib.idle_add(complete, baseline, error, runtime, inventory_error)

        try:
            threading.Thread(target=collect, daemon=False).start()
        except RuntimeError as exc:
            complete(None, str(exc), (), "Runtime inventory unavailable")

    def get_config(self) -> BindingsConfig:
        return BindingsConfig(tuple(self._owned))

    def adopt_saved(self, baseline: BindingsBaseline):
        if self.locked or type(baseline) is not BindingsBaseline or baseline.status != "owned":
            raise ValueError("Bindings baseline cannot be adopted")
        if (
            self.baseline is None
            or (
                baseline.config_root,
                baseline.state_root,
                baseline.lexical_path,
                baseline.resolved_path,
            )
            != (
                self.baseline.config_root,
                self.baseline.state_root,
                self.baseline.lexical_path,
                self.baseline.resolved_path,
            )
            or baseline.config != self.get_config()
        ):
            raise ValueError("Saved bindings differ from the exact draft or route")
        self.baseline = baseline
        self.mark_saved()
        self._notify_dirty()

    def invalidate(self, message):
        self.locked = True
        self.load_error = message
        self._rebuild_list()

    def _require_edit(self):
        if not self._window.editor_edit_allowed() or self.locked or self._closed:
            raise ValueError(self.load_error or "Keybindings editor is locked")
        if self.baseline is None:
            raise ValueError("Wait for the bindings observation before editing")

    def _validate_change(self, line: str, index: int | None = None) -> str:
        self._require_edit()
        parsed = bindings.validate_line(line)
        lines = list(self._owned)
        unchanged_combo = index is not None and bindings.combo(lines[index]) == parsed.combo
        if not unchanged_combo and any(
            live_bind_to_data(raw).combo == parsed.combo for raw in self._runtime
        ):
            raise ValueError("Shortcut conflicts with an external runtime binding (read-only)")
        if index is None:
            lines.append(parsed.to_line())
        else:
            lines[index] = parsed.to_line()
        BindingsConfig(tuple(lines))
        return parsed.to_line()

    def add_line(self, line: str):
        canonical = self._validate_change(line)
        with self._undo_track():
            self._owned.append_new(canonical)
        self._changed()

    def edit_line(self, index: int, line: str):
        if not 0 <= index < len(self._owned):
            raise ValueError("Binding no longer exists")
        canonical = self._validate_change(line, index)
        with self._undo_track():
            self._owned[index] = canonical
        self._changed()

    def delete_at(self, index: int):
        self._require_edit()
        if not 0 <= index < len(self._owned):
            raise ValueError("Binding no longer exists")
        with self._undo_track():
            self._owned.pop_at(index)
        self._changed()

    def _changed(self):
        self._rebuild_list()
        self._notify_dirty()

    def _capture_undo(self):
        return self._owned.snapshot()

    def _undo_key(self):
        return list(self._owned)

    def _build_undo_entry(self, old, new):
        return SavedListSnapshot("_managed_bindings_page", old[0], new[0], old[1], new[1])

    def restore_snapshot(self, items, baselines):
        self._require_edit()
        checked = BindingsConfig(tuple(items))
        if list(checked.lines) != items or len(items) != len(baselines):
            raise ValueError("Invalid bindings snapshot")
        if any(b is not None and b not in self._owned.saved for b in baselines):
            raise ValueError("Snapshot refers to a different saved baseline")
        self._owned.restore(list(items), list(baselines))
        self._changed()

    def is_dirty(self) -> bool:
        return self._owned.is_dirty()

    def mark_saved(self):
        if self.locked or self.baseline is None or self.baseline.config != self.get_config():
            raise ValueError("Only a verified exact bindings baseline can be marked saved")
        self._owned.mark_saved()
        self._rebuild_list()

    def discard(self):
        self._owned.discard_all()
        self._changed()

    def pending_change_count(self) -> int:
        return sum(1 for _change in self.iter_pending_changes())

    def iter_pending_changes(self) -> Iterator[PendingChange]:
        if not self.is_dirty():
            return
        represented = set()
        for index, line in enumerate(self._owned):
            baseline = self._owned.get_baseline(index)
            if baseline is not None:
                represented.add(baseline)
            if baseline == line:
                continue
            bind = bindings.validate_line(line)
            yield PendingChange(
                category="Keybindings",
                title=bind.format_shortcut(),
                subtitle=line if baseline is None else f"{baseline} -> {line}",
                kind="added" if baseline is None else "modified",
                revert=lambda i=index: self._revert_item(i),
                navigate_to="binds",
                icon=BINDS_ICON,
            )
        for line in self._owned.saved:
            if line not in represented:
                yield PendingChange(
                    category="Keybindings",
                    title=bindings.validate_line(line).format_shortcut(),
                    subtitle=f"Removed: {line}",
                    kind="removed",
                    revert=lambda saved=line: self._restore_deleted(saved),
                    navigate_to="binds",
                    icon=BINDS_ICON,
                )

    def _revert_item(self, index):
        self._require_edit()
        baseline = self._owned.get_baseline(index)
        if baseline is None:
            self.delete_at(index)
        else:
            lines = list(self._owned)
            lines[index] = baseline
            BindingsConfig(tuple(lines))
            # Restoring this exact owned baseline does not claim an external binding.
            with self._undo_track():
                self._owned.discard_at(index)
            self._changed()

    def _restore_deleted(self, line):
        self._require_edit()
        BindingsConfig((*self.get_config().lines, line))
        with self._undo_track():
            self._owned.restore_deleted(line)
        self._changed()

    def _open_dialog(self, index: int | None = None):
        try:
            self._require_edit()
        except ValueError as exc:
            self._window.show_toast(str(exc), 5)
            return
        original = self._owned[index] if index is not None else None

        def apply(bind):
            try:
                if index is None:
                    self.add_line(bind.to_line())
                else:
                    if index >= len(self._owned) or self._owned[index] != original:
                        raise ValueError("Draft changed while the dialog was open; reopen it")
                    self.edit_line(index, bind.to_line())
            except ValueError as exc:
                self._window.show_toast(str(exc), 5)
                return False
            return True

        BindEditDialog(
            bind=bindings.validate_line(original) if original is not None else None,
            window=self._window,
            on_apply=apply,
            draft_only=True,
        ).present(self._window)

    def _search_changed(self, entry):
        self._search_term = entry.get_text().strip().casefold()
        self._rebuild_list()

    def _rebuild_list(self):
        if self._content_box is None:
            return
        clear_children(self._content_box)
        if self._add_button is not None:
            self._add_button.set_sensitive(self.baseline is not None and not self.locked)
        status = (
            "Reading saved keybindings..."
            if self._loading
            else "Not observed. Open Keybindings to read saved bindings."
            if not self._started
            else "Managed editing disabled: " + self.load_error
            if self.load_error
            else "Draft and saved file only. Saved does not mean loaded by Hyprland."
        )
        self._content_box.append(make_inline_hint(status))
        self._content_box.append(
            make_inline_hint(
                f"Only {bindings.BASENAME} is managed. No live preview, overrides or automatic "
                "loader changes. Review and Save through Pending Changes. After Save, manually "
                "arrange your Lua loader to load this file if desired. "
                "Foreign output requires manual remediation."
            )
        )
        inventory = (
            f"Runtime inventory UNKNOWN: {self._inventory_error}. Conflicts are not fully known."
            if self._inventory_error
            else "Runtime observation only. All runtime bindings are external and read-only; "
            "matching a managed shortcut does not prove ownership or loading."
        )
        self._content_box.append(make_inline_hint(inventory))
        groups = {}
        visible_categories = set()
        for category in DISPATCHER_CATEGORIES:
            groups[category["id"]] = Adw.PreferencesGroup(title=category["label"])
        for index, line in enumerate(self._owned):
            bind = bindings.validate_line(line)
            category = categorize_bind(bind.bind_type, bind.dispatcher)
            origin = (
                "Managed draft (pending)" if self._owned.is_item_dirty(index) else "Managed saved"
            )
            overlap = any(live_bind_to_data(raw).combo == bind.combo for raw in self._runtime)
            subtitle = f"{origin}: {format_bind_action(bind.bind_type, bind.dispatcher, bind.arg)}"
            if overlap:
                subtitle += ". Observed runtime overlap, unknown origin; draft edits only"
            row = self._row(bind.format_shortcut(), subtitle, category)
            if not self.locked:
                if BindEditDialog.can_represent(bind):
                    edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER)
                    edit.connect("clicked", lambda _button, i=index: self._open_dialog(i))
                    row.add_suffix(edit)
                delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
                delete.connect("clicked", lambda _button, i=index: self._delete_clicked(i))
                row.add_suffix(delete)
            groups.get(category, groups["advanced"]).add(row)
            if row.get_visible():
                visible_categories.add(category if category in groups else "advanced")
        for raw in self._runtime:
            bind = live_bind_to_data(raw)
            category = categorize_bind(bind.bind_type, bind.dispatcher)
            action = (
                f"Opaque Lua callback, runtime reference {raw.arg}"
                if raw.dispatcher == OPAQUE_LUA_DISPATCHER
                else f"{raw.dispatcher}: {raw.arg}"
            )
            flags = ", ".join(
                field.name
                for field in fields(raw)
                if type(getattr(raw, field.name)) is bool and getattr(raw, field.name)
            )
            subtitle = f"External runtime (read-only): {action}. Submap: {raw.submap or 'global'}"
            if flags:
                subtitle += f". Flags: {flags}"
            if raw.description:
                subtitle += f". Description: {raw.description}"
            if raw.keycode:
                subtitle += f". Keycode: {raw.keycode}"
            title = (
                f"{raw.description} | {bind.format_shortcut()}"
                if raw.description
                else bind.format_shortcut()
            )
            row = self._row(title, subtitle, category)
            row.add_suffix(Gtk.Image(icon_name="changes-prevent-symbolic"))
            groups.get(category, groups["advanced"]).add(row)
            if row.get_visible():
                visible_categories.add(category if category in groups else "advanced")
        for category, group in groups.items():
            if category in visible_categories:
                self._content_box.append(group)

    def _row(self, title, subtitle, category):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        row.set_use_markup(False)
        row.set_subtitle_lines(0)
        category_label = next(
            (c["label"] for c in DISPATCHER_CATEGORIES if c["id"] == category), category
        )
        row.set_visible(self._search_term in f"{title} {subtitle} {category_label}".casefold())
        return row

    def _delete_clicked(self, index):
        try:
            self.delete_at(index)
        except ValueError as exc:
            self._window.show_toast(str(exc), 5)
