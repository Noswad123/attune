"""Backup inspection with separately reviewed restoration and text recovery."""

import threading
import weakref
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from hyprmod.core import backups, recovery, restoration
from hyprmod.ui import clear_children, make_page_layout
from hyprmod.ui.diff import ConfigDiffWidget


class BackupsPage:
    def __init__(
        self,
        output_path: Path,
        *,
        restore_permission: Callable[[], None] | None = None,
        begin_restore: Callable[[], None] | None = None,
        finish_restore: Callable[[bool], None] | None = None,
    ):
        # Permission/begin raise to refuse. Finish receives whether cached editor state is unsafe.
        self._output_path = output_path
        self._restore_permission = restore_permission
        self._begin_restore = begin_restore
        self._finish_restore = finish_restore
        self.restore_writing = False
        self._draft: restoration.RestoreDraft | recovery.RecoveryDraft | None = None
        self._recovery_ack: Gtk.CheckButton | None = None
        self._review: Adw.Dialog | None = None
        self._window: Gtk.Window | None = None
        self._listing: backups.BackupListing | None = None
        self._started = False
        self._loading = False
        self._closed = False
        self._stale = False
        self._generation = 0
        self._cancel_event = threading.Event()

    def build(self, header: Adw.HeaderBar) -> Adw.ToolbarView:
        toolbar, _, content, _ = make_page_layout(header=header)
        self._refresh_button = Gtk.Button(label="Refresh")
        self._refresh_button.connect("clicked", lambda _button: self.refresh())
        header.pack_end(self._refresh_button)
        content.append(
            Gtk.Label(
                label="Content-addressed backups, not chronological save history.\n"
                "Hash lexical order. At most 64 candidates are inspected.\n"
                "Valid means content hash and canonical format verified, not guaranteed "
                "restorable or semantically correct. "
                "Compare is inspection only. Review Restoration prepares a separate exact draft.\n"
                "Review Recovery separately preserves and replaces foreign or invalid text.\n"
                "Attune sends no live-apply or reload commands; "
                "Hyprland may auto-reload watched files",
                xalign=0,
                wrap=True,
                use_markup=False,
            )
        )
        self._status = Gtk.Label(label="Not observed yet", xalign=0, wrap=True, use_markup=False)
        content.append(self._status)
        self._rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.append(self._rows)
        self._comparison_status = Gtk.Label(xalign=0, wrap=True, use_markup=False)
        content.append(self._comparison_status)
        self._diff = ConfigDiffWidget()
        self._diff.set_visible(False)
        content.append(self._diff)
        return toolbar

    def ensure_loaded(self) -> None:
        if not self._started:
            self.refresh()

    def bind_lifecycle(self, window: Gtk.Window) -> None:
        self._window = window
        window.connect("close-request", self._on_close_request)
        window.connect("unrealize", self.close)
        window.connect("destroy", self.close)
        application = window.get_application()
        if application is not None:

            def removed(app: Gtk.Application, removed_window: Gtk.Window) -> None:
                if removed_window is window:
                    self.close()
                    app.disconnect(handler)

            handler = application.connect("window-removed", removed)

    def _on_close_request(self, *_args) -> bool:
        if self.restore_writing:
            self._comparison_status.set_label(
                "Restoration or recovery is running. Wait for its outcome before closing."
            )
            return True
        return False

    def refresh(self) -> None:
        if self._closed or self._loading:
            return
        self._stale = self._listing is not None
        self._status.set_label("Loading backups... Previous rows, if any, are stale.")
        self._start(None)

    def compare(self, name: str) -> None:
        if self._closed or self._loading or self._stale or self._listing is None:
            return
        if not any(row.name == name and row.status == "valid" for row in self._listing.backups):
            return
        self._start(name)

    def review_restoration(self, name: str) -> None:
        self._prepare_review(name, recover=False)

    def review_recovery(self, name: str) -> None:
        self._prepare_review(name, recover=True)

    def _prepare_review(self, name: str, *, recover: bool) -> None:
        if self._closed or self._loading or self._stale or self._listing is None:
            return
        if not any(row.name == name and row.status == "valid" for row in self._listing.backups):
            return
        try:
            if self._restore_permission is not None:
                self._restore_permission()
        except Exception as exc:
            self._comparison_status.set_label(
                f"{'Recovery' if recover else 'Restoration'} refused: {exc}. No changes were made."
            )
            return
        self._start(name, prepare=True, recover=recover)

    def _start(self, name: str | None, *, prepare: bool = False, recover: bool = False) -> None:
        self._started = True
        self._loading = True
        self._generation += 1
        generation = self._generation
        self._refresh_button.set_sensitive(False)
        self._rows.set_sensitive(False)
        self._diff.set_visible(False)
        self._diff.set_precomputed_diff(
            "", added_lines=0, removed_lines=0, title="BACKUP -> CURRENT"
        )
        self._comparison_status.set_label(
            f"Preparing {name}: CURRENT -> {'RECOVERY BACKUP' if recover else 'BACKUP'}. "
            "Read-only validation..."
            if prepare
            else f"Comparing {name}: BACKUP -> CURRENT..."
            if name
            else "Select a valid backup to compare."
        )
        page_ref = weakref.ref(self)
        path = self._output_path
        cancel_event = self._cancel_event

        def complete(
            result: backups.BackupListing
            | backups.BackupComparison
            | restoration.RestoreDraft
            | recovery.RecoveryDraft
            | None,
            error: str | None,
        ) -> bool:
            page = page_ref()
            if page is None or page._closed or page._generation != generation:
                return GLib.SOURCE_REMOVE
            # Invalidate even a duplicate queued completion before accepting another operation.
            page._generation += 1
            expected = recovery.RecoveryDraft if recover else restoration.RestoreDraft
            if isinstance(result, (restoration.RestoreDraft, recovery.RecoveryDraft)) and (
                not prepare or type(result) is not expected
            ):
                result = None
                error = "Preparation returned the wrong draft type"
            page._loading = isinstance(result, (restoration.RestoreDraft, recovery.RecoveryDraft))
            page._refresh_button.set_sensitive(not page._loading)
            if isinstance(result, backups.BackupListing):
                page._listing = result
                page._stale = result.status == "unavailable"
                page._render_listing(result)
            elif isinstance(result, backups.BackupComparison):
                page._render_comparison(result)
            elif isinstance(result, (restoration.RestoreDraft, recovery.RecoveryDraft)):
                try:
                    page._show_restore_review(result)
                except Exception as exc:
                    page.cancel_restoration()
                    page._comparison_status.set_label(
                        f"Could not show review: {exc}. No changes were made."
                    )
            elif name is None:
                previous = (
                    f" Stale rows retained from {page._listing.observed_at}; comparison disabled."
                    if page._listing is not None
                    else " No observation available."
                )
                page._status.set_label(f"Refresh failed: {error}.{previous}")
            else:
                operation = (
                    "Recovery preparation"
                    if recover
                    else "Restoration preparation"
                    if prepare
                    else "Comparison"
                )
                page._comparison_status.set_label(
                    f"{operation} failed for {name}: {error}. No diff. No changes were made."
                )
            page._rows.set_sensitive(not page._stale and not page._loading)
            return GLib.SOURCE_REMOVE

        def collect() -> None:
            try:
                if name is None:
                    result = backups.run_list(path, cancel_event=cancel_event)
                elif prepare:
                    if recover:
                        result = recovery.run_prepare(path, name, cancel_event=cancel_event)
                    else:
                        result = restoration.run_prepare(path, name, cancel_event=cancel_event)
                else:
                    result = backups.run_compare(path, name, cancel_event=cancel_event)
            except Exception as exc:
                GLib.idle_add(complete, None, str(exc))
            else:
                GLib.idle_add(complete, result, None)

        try:
            threading.Thread(target=collect, daemon=False).start()
        except RuntimeError as exc:
            GLib.idle_add(complete, None, str(exc))

    @staticmethod
    def _metadata(info: backups.BackupInfo | backups.CurrentOutput) -> str:
        fields = [f"{info.status}: {info.detail}"]
        if info.sha256 is not None:
            fields.append(f"SHA-256: {info.sha256}")
        if info.size_bytes is not None:
            fields.append(f"Size: {info.size_bytes} bytes")
        if info.modified_ns is not None:
            modified = datetime.fromtimestamp(info.modified_ns / 1_000_000_000, UTC).isoformat()
            fields.append(f"Filesystem modification: {modified} (not last save)")
        if info.summary is not None:
            summary = info.summary
            fields.append(
                f"Canonical counts: {summary.scalars} scalars, {summary.monitors} monitors, "
                f"{summary.animations} animations, {summary.beziers} Beziers"
            )
        return "\n".join(fields)

    def _render_listing(self, listing: backups.BackupListing) -> None:
        details = [
            f"Observed: {listing.observed_at}. Listing: {listing.status}.",
            f"Directory: {listing.directory}",
            f"Showing {len(listing.backups)} candidates (maximum 64), in hash lexical order.",
            *listing.notes,
        ]
        if not listing.backups:
            details.append("No backup candidates available. Nothing was created.")
        self._status.set_label("\n".join(details))
        clear_children(self._rows)
        for info in listing.backups:
            group = Adw.PreferencesGroup()
            row = Adw.ActionRow(title=info.name)
            row.set_use_markup(False)
            row.set_title_lines(0)
            row.set_subtitle(self._metadata(info))
            row.set_subtitle_lines(0)
            if info.status == "valid":
                button = Gtk.Button(label="Compare", valign=Gtk.Align.CENTER)
                button.connect("clicked", lambda _button, name=info.name: self.compare(name))
                row.add_suffix(button)
                row.set_activatable_widget(button)
                restore = Gtk.Button(label="Review Restoration", valign=Gtk.Align.CENTER)
                restore.connect(
                    "clicked", lambda _button, name=info.name: self.review_restoration(name)
                )
                row.add_suffix(restore)
                recover = Gtk.Button(label="Review Recovery", valign=Gtk.Align.CENTER)
                recover.connect(
                    "clicked", lambda _button, name=info.name: self.review_recovery(name)
                )
                row.add_suffix(recover)
            group.add(row)
            self._rows.append(group)

    def _render_comparison(self, result: backups.BackupComparison) -> None:
        current = result.current
        details = [
            f"Observed: {result.observed_at}. BACKUP -> CURRENT. {result.status}.",
            f"Backup: {result.backup.name}",
            self._metadata(result.backup),
            f"Current lexical path: {current.lexical_path}",
            f"Current resolved path: {current.resolved_path or 'Unavailable'}",
            self._metadata(current),
            *result.notes,
        ]
        if current.status == "missing":
            details.append("Current output is missing: comparing BACKUP to empty CURRENT.")
        if result.status != "compared":
            details.append("Warning: no diff available. No changes were made.")
        else:
            if result.truncated:
                details.append(
                    "Warning: diff truncated. Counts cover full inputs, not just shown lines."
                )
            self._diff.set_precomputed_diff(
                result.diff,
                added_lines=result.added_lines or 0,
                removed_lines=result.removed_lines or 0,
                title="BACKUP -> CURRENT",
                empty_message=(
                    "Diff truncated before displayable lines"
                    if result.truncated
                    else "No textual differences between backup and current output"
                ),
            )
            self._diff.set_visible(True)
        self._comparison_status.set_label("\n".join(details))

    def _show_restore_review(
        self, draft: restoration.RestoreDraft | recovery.RecoveryDraft
    ) -> None:
        self._draft = draft
        self._recovery_ack = None
        recover = type(draft) is recovery.RecoveryDraft
        direction = "CURRENT -> RECOVERY BACKUP" if recover else "CURRENT -> BACKUP"
        warning = (
            f"Original status: {draft.current_status}\n"
            f"Private preservation path: {draft.preservation_path}\n"
            "Foreign/invalid TEXT will be replaced only after exact original bytes are verified "
            "preserved at this private path. The preserved .bin is manual evidence, "
            "NOT a canonical rollback backup or executable Lua.\n"
            "Candidate syntax is checked compile-only; the original is not compiled and no Lua "
            "is executed.\n"
            if type(draft) is recovery.RecoveryDraft
            else "Rollback: a backup of current output will be created before replacement, "
            "unless the output is unchanged.\n"
        )
        dialog = Adw.Dialog(
            title="Review Recovery" if recover else "Review Restoration",
            content_width=800,
            content_height=650,
        )
        self._review = dialog
        toolbar, _, content, _ = make_page_layout(header=Adw.HeaderBar())
        content.append(
            Gtk.Label(
                label=f"Observed: {draft.observed_at}\n"
                f"Source: {draft.backup_root}/{draft.backup_name}\n"
                f"Selected source SHA-256 / proposed: {draft.proposed_sha256}\n"
                f"Current SHA-256: {draft.previous_sha256}\n"
                f"Lexical output: {draft.lexical_path}\nResolved output: {draft.resolved_path}\n"
                f"{direction}. Complete exact diff.\n"
                f"{warning}"
                "Attune sends no live-apply or reload commands; "
                "Hyprland may auto-reload watched files",
                xalign=0,
                wrap=True,
                selectable=True,
                use_markup=False,
            )
        )
        diff = ConfigDiffWidget()
        diff.set_precomputed_diff(
            draft.diff,
            added_lines=draft.added_lines,
            removed_lines=draft.removed_lines,
            title=direction,
        )
        content.append(diff)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _button: self.cancel_restoration())
        content.append(cancel)
        restore = Gtk.Button(
            label="Preserve and Recover Reviewed Output" if recover else "Restore Reviewed Output"
        )
        restore.add_css_class("destructive-action")
        restore.connect("clicked", lambda _button: self.restore_reviewed())
        if recover:
            ack = Gtk.CheckButton(
                label="I acknowledge replacement of the reviewed text "
                "and possible watcher auto-reload"
            )
            self._recovery_ack = ack
            restore.set_sensitive(False)
            ack.connect("toggled", lambda button: restore.set_sensitive(button.get_active()))
            content.append(ack)
        content.append(restore)
        dialog.set_child(toolbar)
        dialog.connect("closed", self._on_review_closed)
        dialog.present(self._window)

    def _on_review_closed(self, _dialog: Adw.Dialog) -> None:
        if _dialog is not self._review:
            return
        self._review = None
        self.cancel_restoration()

    def cancel_restoration(self) -> None:
        if self.restore_writing:
            return
        self._generation += 1
        self._draft = None
        self._recovery_ack = None
        review = self._review
        self._review = None
        if review is not None:
            review.close()
        self._loading = False
        self._refresh_button.set_sensitive(True)
        self._rows.set_sensitive(not self._stale)

    def restore_reviewed(self) -> None:
        if self._closed or self.restore_writing or self._draft is None:
            return
        draft = self._draft
        recover = type(draft) is recovery.RecoveryDraft
        if recover and (self._recovery_ack is None or not self._recovery_ack.get_active()):
            return
        operation = "Recovery" if recover else "Restoration"
        self._draft = None  # Every attempt consumes the review, including refusals.
        try:
            if self._restore_permission is not None:
                self._restore_permission()
            if self._begin_restore is not None:
                self._begin_restore()
        except Exception as exc:
            try:
                if self._finish_restore is not None:
                    self._finish_restore(False)
            except Exception as finish_error:
                self._comparison_status.set_label(
                    f"{operation} refused: {exc}. Editor unlock failed: {finish_error}. "
                    "No changes were made. Restart Attune."
                )
            else:
                self._comparison_status.set_label(
                    f"{operation} refused: {exc}. No changes were made."
                )
            finally:
                self.cancel_restoration()
            return
        self.restore_writing = True
        self._generation += 1
        generation = self._generation
        if self._review is not None:
            self._review.set_can_close(False)
            child = self._review.get_child()
            if child is not None:
                child.set_sensitive(False)
        self._comparison_status.set_label(
            f"{operation} of reviewed output running. Wait for the writer outcome."
        )

        def complete(
            result: restoration.RestoreResult | recovery.RecoveryResult | None,
            error: str | None,
            uncertain: bool,
        ) -> bool:
            # Commit outcomes must survive close attempts and preparation generations.
            if self._generation != generation:
                return GLib.SOURCE_REMOVE
            self._generation += 1
            invalidate = uncertain or (
                result is not None and result.status in ("restored", "recovered")
            )
            notification_error = ""
            try:
                if self._finish_restore is not None:
                    self._finish_restore(invalidate)
            except Exception as exc:
                notification_error = f" Editor notification failed: {exc}. Inspect/restart Attune."
            finally:
                self.restore_writing = False
                if self._review is not None:
                    self._review.set_can_close(True)
                self.cancel_restoration()
            if isinstance(result, recovery.RecoveryResult):
                message = (
                    f"Recovered: {result.resolved_path}. Preserved original: "
                    f"{result.preservation_path}. Manual evidence only, not canonical rollback "
                    "or executable Lua. Restart Attune to load recovered disk state."
                )
            elif result is not None:
                message = (
                    f"Restored: {result.resolved_path}. Rollback backup: {result.backup_path}. "
                    "Restart Attune to load restored disk state."
                    if result.status == "restored"
                    else "Output unchanged. No write or backup was needed."
                )
            elif uncertain:
                message = (
                    f"{operation} failed: {error}. Output may have changed; inspect/restart Attune."
                )
            else:
                message = f"{operation} failed: {error}. No output replacement occurred."
                if recover:
                    message += " A preserved copy or state files may already exist."
            self._comparison_status.set_label(
                message + notification_error + f" A fresh {operation.lower()} review is required."
            )
            return GLib.SOURCE_REMOVE

        def commit() -> None:
            try:
                if type(draft) is recovery.RecoveryDraft:
                    result = recovery.commit_recovery(draft, cancel_event=self._cancel_event)
                elif type(draft) is restoration.RestoreDraft:
                    result = restoration.commit_restore(draft, cancel_event=self._cancel_event)
                else:
                    raise TypeError("Unsupported review draft type")
            except (restoration.RestoreFailure, recovery.RecoveryFailure) as exc:
                GLib.idle_add(complete, None, str(exc), exc.may_have_written)
            except Exception as exc:
                GLib.idle_add(complete, None, str(exc), True)
            else:
                GLib.idle_add(complete, result, None, False)

        try:
            threading.Thread(target=commit, daemon=False).start()
        except Exception as exc:
            complete(None, str(exc), False)

    def close(self, *_args) -> None:
        if self.restore_writing:
            return
        # Interpreter shutdown waits for bounded child cleanup; never join on GTK.
        self._closed = True
        self._generation += 1
        self._cancel_event.set()
        if self._review is not None:
            self._review.close()
        self._draft = None
        self._recovery_ack = None
