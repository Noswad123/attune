"""Editable source data, independent of runtime inventory and authored actions."""

import hashlib
import os
import threading
from dataclasses import replace
from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from hyprmod.core import source_bindings as source
from hyprmod.core.ownership import SavedList
from hyprmod.core.pending import PendingChange
from hyprmod.core.undo import SavedListSnapshot
from hyprmod.pages.section import SectionPage
from hyprmod.ui import clear_children, make_inline_hint, make_page_layout
from hyprmod.ui.diff import ConfigDiffWidget
from hyprmod.ui.icons import BINDS_ICON


class SourceBindingsPage(SectionPage):
    def __init__(self, window, on_dirty_changed=None, push_undo=None):
        super().__init__(window, on_dirty_changed, push_undo)
        self.baseline: source.SourceBaseline | None = None
        self.load_error: str | None = None
        self.locked = False
        self._owned = SavedList[source.SourceBinding]([], key=lambda b: b)
        self._config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self._path = self._config_root / "hypr/keybindings.tsv"
        self._state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        self._prepared_path = Path(__file__).absolute().parents[2] / (
            "integrations/hyprland/jdawson/keybindings.tsv"
        )
        self._selected = False
        self._started = False
        self._closed = False
        self._generation = 0
        self._read_cancel: threading.Event | None = None
        self._review: source.SourceReview | None = None
        self._saving = False
        self._search_term = ""
        self._content_box: Gtk.Box | None = None
        self._review_box: Gtk.Box | None = None
        self._save_button: Gtk.Button | None = None

    def build(self, header=None):
        toolbar, page_box, content, _ = make_page_layout(header=header)
        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        choose = Gtk.Button(label="Open Source Mappings...")
        choose.connect("clicked", self._choose_file)
        controls.append(choose)
        prepared = Gtk.Button(label="Open Prepared Source Mappings")
        prepared.set_tooltip_text(
            "Open the offline prepared bundle's data only. Nothing is installed or activated."
        )
        prepared.connect("clicked", lambda _b: self._open_clicked(self._prepared_path))
        controls.append(prepared)
        review = Gtk.Button(label="Review Source Shortcuts...")
        review.connect("clicked", lambda _b: self.review_changes())
        controls.append(review)
        content.append(controls)
        search = Gtk.SearchEntry(placeholder_text="Search descriptions, shortcuts, IDs or context")
        search.connect("search-changed", self._search_changed)
        page_box.prepend(search)
        self._review_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.append(self._review_box)
        self._save_button = Gtk.Button(label="Save Reviewed Source Shortcuts")
        self._save_button.set_visible(False)
        self._save_button.connect("clicked", self._save_reviewed)
        content.append(self._save_button)
        content.append(self._content_box)
        toolbar.connect("map", lambda _w: self.ensure_loaded())
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
        self._invalidate_review()

    def _invalidate_review(self):
        self._generation += 1
        self._review = None
        if self._read_cancel is not None:
            self._read_cancel.set()
        if self._review_box is not None:
            clear_children(self._review_box)
        if self._save_button is not None:
            self._save_button.set_visible(False)

    def ensure_loaded(self):
        if self._started or self._closed or self.locked or self._read_cancel is not None:
            return
        self._started = True
        self._start_read(False)

    def open_path(self, path: Path):
        if self._closed or self.locked or self._saving or not self._window.editor_edit_allowed():
            raise ValueError("Source editor is locked")
        if self.is_dirty():
            raise ValueError("Discard source shortcut changes before choosing another source")
        if self._read_cancel is not None:
            raise ValueError("Wait for the current source read to finish")
        path = Path(os.path.abspath(path))
        if path.name != source.BASENAME:
            raise ValueError("Select an existing keybindings.tsv in the source mappings format")
        self._invalidate_review()
        self._path = path
        self._selected = True
        self._started = True
        self.baseline = None
        self.load_error = None
        self._owned = SavedList([], key=lambda b: b)
        self._window.clear_source_bindings_undo()
        self._start_read(False)

    def _open_clicked(self, path):
        try:
            self.open_path(path)
        except ValueError as exc:
            self._window.show_toast(str(exc), 5)

    def _choose_file(self, _button):
        dialog = Gtk.FileDialog(title="Open source mappings: keybindings.tsv")
        filter_ = Gtk.FileFilter(name="Source mappings (keybindings.tsv)")
        filter_.add_pattern(source.BASENAME)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_)
        dialog.set_filters(filters)

        def selected(chooser, result):
            try:
                file = chooser.open_finish(result)
                path = file.get_path() if file is not None else None
                if path is not None:
                    self._open_clicked(Path(path))
            except GLib.Error:
                pass

        dialog.open(self._window, None, selected)

    def review_changes(self):
        try:
            self._require_edit()
            self._invalidate_review()
            self._start_read(True)
        except ValueError as exc:
            self._window.show_toast(str(exc), 5)

    def _start_read(self, review_mode):
        cancel = threading.Event()
        self._read_cancel = cancel
        generation, path, state = self._generation, self._path, self._state_root
        config_root = self._config_root
        baseline = self.baseline
        proposed = self.get_config() if review_mode else None
        self._rebuild_list()

        def complete(result, error):
            if self._read_cancel is not cancel:
                return GLib.SOURCE_REMOVE
            self._read_cancel = None
            if self._closed:
                return GLib.SOURCE_REMOVE
            if cancel.is_set() or generation != self._generation:
                self._rebuild_list()
                return GLib.SOURCE_REMOVE
            if review_mode:
                if self.baseline is not baseline or self.get_config() != proposed:
                    return GLib.SOURCE_REMOVE
                if error is None and (
                    type(result) is not source.SourceReview
                    or baseline is None
                    or not source.same_source(baseline, result.baseline)
                    or result.proposed != proposed
                ):
                    error = "Unexpected source review context"
                if error is None and not self.locked:
                    self._review = result
                    self._render_review(result)
                else:
                    self._window.show_toast(f"Cannot review source shortcuts: {error}", 5)
            else:
                if error is None and (
                    type(result) is not source.SourceBaseline
                    or (result.lexical_path, result.state_root, result.config_root)
                    != (str(path), str(state), str(config_root))
                    or path != self._path
                ):
                    error = "Unexpected source observation context"
                if error is not None:
                    self.load_error = error
                else:
                    self.baseline = result
                    self.load_error = None
                    self._owned = SavedList(list(result.config.bindings), key=lambda b: b)
            self._rebuild_list()
            return GLib.SOURCE_REMOVE

        def work():
            try:
                if review_mode:
                    if baseline is None or proposed is None:
                        raise ValueError("Source review requires a loaded baseline")
                    result = source.run_prepare_review(baseline, proposed, cancel_event=cancel)
                else:
                    result = source.run_observe(
                        path, state, config_root=config_root, cancel_event=cancel
                    )
                expected = source.SourceReview if review_mode else source.SourceBaseline
                if type(result) is not expected:
                    raise ValueError("Unexpected source worker result type")
                result.__post_init__()
            except Exception as exc:
                GLib.idle_add(complete, None, str(exc) or type(exc).__name__)
            else:
                GLib.idle_add(complete, result, None)

        try:
            threading.Thread(target=work, daemon=False).start()
        except Exception as exc:
            complete(None, str(exc))

    def get_config(self) -> source.SourceConfig:
        return source.SourceConfig(source.CATALOG, tuple(self._owned))

    def _require_edit(self):
        if self._closed or self.locked or self._saving or not self._window.editor_edit_allowed():
            raise ValueError(self.load_error or "Source shortcuts are locked")
        if self.baseline is None:
            raise ValueError("Open an existing source mappings file before editing")
        if self._read_cancel is not None:
            raise ValueError("Wait for the current source read to finish")

    def _check_proposal(self, proposed):
        if self.baseline is None:
            raise ValueError("Source baseline unavailable")

        if source.fixed_metadata(proposed) != source.fixed_metadata(self.baseline.config):
            raise ValueError("Source IDs, context, submap, base flags and order are read-only")

    def edit_binding(self, index: int, key: str, description: str, *, enabled: bool | None = None):
        self._require_edit()
        if not 0 <= index < len(self._owned):
            raise ValueError("Source shortcut no longer exists")
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("Enabled must be a boolean")
        rows = list(self._owned)
        original = rows[index]
        active = (original.enabled if original.assigned else True) if enabled is None else enabled
        if not key.strip():
            key = ""
        flags = tuple(f for f in original.flags if f != "disabled")
        if key and not active:
            flags = tuple(sorted((*flags, "disabled")))
        rows[index] = replace(original, key=key, description=description, flags=flags)
        self._check_proposal(source.SourceConfig(source.CATALOG, tuple(rows)))
        with self._undo_track():
            self._owned[index] = rows[index]
        self._changed()

    def set_enabled(self, index: int, enabled: bool):
        self._require_edit()
        if type(enabled) is not bool:
            raise ValueError("Enabled must be a boolean")
        if not 0 <= index < len(self._owned):
            raise ValueError("Source shortcut no longer exists")
        row = self._owned[index]
        if not row.assigned:
            raise ValueError("Enter a shortcut first")
        self.edit_binding(index, row.key, row.description, enabled=enabled)

    def _toggle_enabled(self, index, enabled):
        try:
            self.set_enabled(index, enabled)
        except ValueError as exc:
            self._window.show_toast(str(exc), 5)

    def _open_dialog(self, index):
        try:
            self._require_edit()
        except ValueError as exc:
            self._window.show_toast(str(exc), 5)
            return
        original = self._owned[index]
        baseline = self.baseline
        dialog = Adw.Dialog(title="Edit Source Shortcut", content_width=480)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=18,
            margin_bottom=18,
            margin_start=18,
            margin_end=18,
        )
        group = Adw.PreferencesGroup(description="Authored Lua action (unchanged)")
        key = Adw.EntryRow(title="Shortcut", text=original.key)
        description = Adw.EntryRow(title="Description", text=original.description)
        enabled = Adw.SwitchRow(
            title="Enabled",
            subtitle="Applies when a shortcut is assigned",
            active=original.enabled or not original.assigned,
        )
        group.add(key)
        group.add(description)
        group.add(enabled)
        box.append(group)
        box.append(
            make_inline_hint(
                "Leave Shortcut empty for no assignment. "
                "Disable keeps the assigned shortcut stored and off."
            )
        )
        apply = Gtk.Button(label="Update Pending")

        def update(_button):
            try:
                self._require_edit()
                if self.baseline is not baseline or self._owned[index] != original:
                    raise ValueError("Draft changed while dialog was open; reopen it")
                self.edit_binding(
                    index, key.get_text(), description.get_text(), enabled=enabled.get_active()
                )
            except ValueError as exc:
                self._window.show_toast(str(exc), 5)
                return
            dialog.close()

        apply.connect("clicked", update)
        box.append(apply)
        toolbar.set_content(box)
        dialog.set_child(toolbar)
        dialog.present(self._window)

    def _capture_undo(self):
        return self._owned.snapshot()

    def _undo_key(self):
        return list(self._owned)

    def _build_undo_entry(self, old, new):
        return SavedListSnapshot("_source_bindings_page", old[0], new[0], old[1], new[1])

    def restore_snapshot(self, items, baselines):
        self._require_edit()
        self._check_proposal(source.SourceConfig(source.CATALOG, tuple(items)))
        if list(baselines) != self._owned.saved:
            raise ValueError("Snapshot belongs to a different source baseline")
        self._owned.restore(list(items), list(baselines))
        self._changed()

    def is_dirty(self):
        return self._owned.is_dirty()

    def mark_saved(self):
        if self.locked or self.baseline is None or self.baseline.config != self.get_config():
            raise ValueError("Only an exact verified source baseline may be saved")
        self._owned.mark_saved()
        self._changed()

    def adopt_saved(self, baseline):
        prior = self.baseline
        if (
            type(baseline) is not source.SourceBaseline
            or prior is None
            or (
                baseline.lexical_path,
                baseline.resolved_path,
                baseline.state_root,
                baseline.config_root,
                baseline.config,
            )
            != (
                prior.lexical_path,
                prior.resolved_path,
                prior.state_root,
                prior.config_root,
                self.get_config(),
            )
        ):
            raise ValueError("Saved source differs from selected route or draft")
        self.baseline = baseline
        self.mark_saved()

    def invalidate(self, message):
        self.locked = True
        self.load_error = message
        self._invalidate_review()
        self._rebuild_list()

    def discard(self):
        if not self.is_dirty() or self.locked:
            return
        self._require_edit()
        self._owned.discard_all()
        self._changed()

    def _changed(self):
        self._invalidate_review()
        self._rebuild_list()
        self._notify_dirty()

    def iter_pending_changes(self):
        for index, row in enumerate(self._owned):
            old = self._owned.get_baseline(index)
            if old is not None and old != row:
                if old.assigned and not row.assigned:
                    title, kind = f"Clear shortcut: {row.description}", "removed"
                elif not old.assigned and row.assigned:
                    title, kind = f"Assign shortcut: {row.description}", "added"
                else:
                    title = (
                        f"{'Disable' if not row.enabled else 'Enable'}: {row.description}"
                        if old.enabled != row.enabled
                        else row.description
                    )
                    kind = "modified"
                old_status = (
                    "Unassigned" if not old.assigned else "Enabled" if old.enabled else "Disabled"
                )
                new_status = (
                    "Unassigned" if not row.assigned else "Enabled" if row.enabled else "Disabled"
                )
                yield PendingChange(
                    category="Source Shortcuts",
                    title=title,
                    subtitle=(
                        f"{old_status}: "
                        f"{old.key}: {old.description} -> "
                        f"{new_status}: "
                        f"{row.key}: {row.description}"
                    ),
                    kind=kind,
                    navigate_to="binds",
                    icon=BINDS_ICON,
                    revert=lambda i=index, b=old: self.edit_binding(
                        i, b.key, b.description, enabled=b.enabled
                    ),
                )

    def _search_changed(self, entry):
        self._search_term = entry.get_text().strip().casefold()
        self._rebuild_list()

    def _rebuild_list(self):
        if self._content_box is None:
            return
        clear_children(self._content_box)
        status = (
            "Selected source data; activation/loading unverified"
            if self._selected
            else ("Declared on disk; activation/loading unverified")
        )
        self._content_box.append(make_inline_hint(f"{status}\n{self._path}"))
        self._content_box.append(
            make_inline_hint(
                "Shortcuts, descriptions and Enabled are editable. "
                "Leave Shortcut empty for no assignment. "
                "Disable retains the key for restoring and frees it for another enabled shortcut. "
                "Authored Lua actions stay unchanged. "
                "Attune does not install a loader or send reload IPC. No Lua execution."
            )
        )
        if self.load_error:
            self._content_box.append(
                make_inline_hint(
                    f"Cannot load source mappings: {self.load_error}. "
                    "Choose an existing keybindings.tsv "
                    "or use Open Prepared Source Mappings. Nothing is copied or installed."
                )
            )
        if self._read_cancel is not None:
            self._content_box.append(
                make_inline_hint("Reading source mappings / preparing review...")
            )
        assigned = sum(b.assigned for b in self._owned)
        disabled = sum(b.assigned and not b.enabled for b in self._owned)
        self._content_box.append(
            make_inline_hint(
                f"{len(self._owned)} keybindings | {assigned} shortcut fields set | "
                f"{disabled} disabled"
            )
        )
        group = Adw.PreferencesGroup(title="Keybindings")
        self._content_box.append(group)
        for index, binding in enumerate(self._owned):
            binding_status = (
                "Unassigned"
                if not binding.assigned
                else "Enabled"
                if binding.enabled
                else "Disabled"
            )
            metadata = (
                f"{binding.id} | Context: {binding.context} | Native submap: "
                f"{binding.submap or 'global'} | Flags: {', '.join(binding.flags) or 'none'}"
            )
            row = Adw.ActionRow(
                title=f"{binding.description}  |  {binding.key}",
                subtitle=f"{binding_status} | Authored Lua action (unchanged)\n{metadata}",
            )
            row.set_use_markup(False)
            row.set_subtitle_lines(0)
            row.set_visible(
                self._search_term
                in (f"{binding_status} {binding.description} {binding.key} {metadata}".casefold())
            )
            edit = Gtk.Button(
                icon_name="document-edit-symbolic",
                valign=Gtk.Align.CENTER,
                tooltip_text="Edit shortcut and description",
            )
            edit.set_sensitive(not self.locked and not self._saving)
            edit.connect("clicked", lambda _b, i=index: self._open_dialog(i))
            row.add_suffix(edit)
            toggle = Gtk.Button(
                label="Disable" if binding.enabled else "Enable", valign=Gtk.Align.CENTER
            )
            toggle.set_sensitive(binding.assigned and not self.locked and not self._saving)
            if not binding.assigned:
                toggle.set_tooltip_text("Edit Shortcut to enter a shortcut first")
            toggle.connect(
                "clicked",
                lambda _b, i=index, active=binding.enabled: self._toggle_enabled(i, not active),
            )
            row.add_suffix(toggle)
            group.add(row)

    def _render_review(self, review):
        box, button = self._review_box, self._save_button
        if box is None or button is None:
            return
        clear_children(box)
        box.append(
            Gtk.Label(
                label=f"Source TSV only: {review.baseline.lexical_path}\n"
                f"Resolved: {review.baseline.resolved_path}\n"
                f"SHA256: {review.baseline.sha256} -> "
                f"{hashlib.sha256(review.proposed_text.encode()).hexdigest()}\n"
                f"Review: {review.review_hash}\n"
                "Attune does not install a loader or send reload IPC. "
                "Saving an already-integrated or watched file may trigger an immediate reload. "
                "Loading/activation is unverified. "
                "Additional bindings and appearance/displays must be saved separately.",
                xalign=0,
                wrap=True,
                selectable=True,
            )
        )
        diff = ConfigDiffWidget()
        diff.set_precomputed_diff(
            review.diff,
            added_lines=review.added_lines,
            removed_lines=review.removed_lines,
            title="Source Shortcuts",
        )
        box.append(diff)
        button.set_visible(True)
        button.set_sensitive(True)

    def _save_reviewed(self, _button=None):
        review = self._review
        self._invalidate_review()
        if review is None:
            return
        try:
            self._require_edit()
            if (
                self.baseline is None
                or not source.same_source(self.baseline, review.baseline)
                or review.proposed != self.get_config()
            ):
                raise ValueError("Source draft changed; review again")
            if not self._window.begin_source_bindings_save():
                return
        except ValueError as exc:
            self._window.show_toast(str(exc), 5)
            return
        self._saving = True
        completed = False

        def finish(result, error, delegated):
            nonlocal completed
            if completed:
                return GLib.SOURCE_REMOVE
            completed = True
            self._saving = False
            uncertain = delegated and (
                error is not None or result is None or result.may_have_written
            )
            # Retire this attempt and release only our owner before fallible notifications.
            self._window.finish_source_bindings_save()
            try:
                if error is None and result is not None and result.outcome in {"saved", "no-op"}:
                    try:
                        self.adopt_saved(result.baseline)
                    except Exception as exc:
                        message = f"Saved source could not be adopted: {exc}. Reopen Attune."
                        self.invalidate(message)
                        self._window.show_toast(message, 5)
                        return GLib.SOURCE_REMOVE
                    self._window.clear_source_bindings_undo()
                    self._window.show_toast(
                        "Source shortcuts saved on disk; loading unverified.", 5
                    )
                else:
                    reason = error or (result.error if result is not None else "setup failed")
                    message = f"Source shortcuts not saved: {reason}. Draft retained."
                    if uncertain:
                        self.invalidate(message + " Disk may have changed; reopen Attune.")
                    self._window.show_toast(message, 5)
            finally:
                self._rebuild_list()
                self._notify_dirty()
            return GLib.SOURCE_REMOVE

        def work():
            try:
                result = source.persist_reviewed(review, review.proposed)
                if type(result) is not source.SourceSaveResult:
                    raise ValueError("Unexpected source save result")
                result.__post_init__()
                fresh = result.baseline
                if result.outcome in {"saved", "no-op"}:
                    if type(fresh) is not source.SourceBaseline or (
                        fresh.lexical_path,
                        fresh.resolved_path,
                        fresh.state_root,
                        fresh.config_root,
                        fresh.text,
                        fresh.config,
                    ) != (
                        review.baseline.lexical_path,
                        review.baseline.resolved_path,
                        review.baseline.state_root,
                        review.baseline.config_root,
                        review.proposed_text,
                        review.proposed,
                    ):
                        raise ValueError("Saved source differs from reviewed route/data")
                GLib.idle_add(finish, result, None, True)
            except Exception as exc:
                GLib.idle_add(finish, None, str(exc) or type(exc).__name__, True)

        try:
            self._rebuild_list()
            threading.Thread(target=work, daemon=False).start()
        except Exception as exc:
            finish(None, str(exc), False)
