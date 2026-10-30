"""Explicit scoped journal recovery, separate from v1 backup restoration."""

import threading
import weakref
from collections.abc import Callable
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from hyprmod.core import scoped_recovery
from hyprmod.core.transaction_publication import PublicationResult
from hyprmod.ui import clear_children, make_page_layout
from hyprmod.ui.diff import ConfigDiffWidget


class ScopeRecoveryPage:
    def __init__(
        self,
        config_root: Path,
        state_root: Path,
        *,
        restore_permission: Callable[[], None] | None = None,
        begin_restore: Callable[[], None] | None = None,
        finish_restore: Callable[[bool], None] | None = None,
    ):
        self._config_root = config_root
        self._state_root = state_root
        self._restore_permission = restore_permission
        self._begin_restore = begin_restore
        self._finish_restore = finish_restore
        self.on_assessment: Callable[[scoped_recovery.LayoutAssessment], None] | None = None
        self.on_assessment_error: Callable[[str], None] | None = None
        self._assessment: scoped_recovery.LayoutAssessment | None = None
        self._draft: scoped_recovery.ScopedRecoveryDraft | None = None
        self._loading = False
        self._started = False
        self._closed = False
        self._generation = 0
        self._read_token: object | None = None
        self._writing = False
        self._cancel_event = threading.Event()
        self.scope_may_have_changed = False
        self.journal_may_have_changed = False

    @property
    def restore_writing(self) -> bool:
        return self._writing

    def build(self, header: Adw.HeaderBar | None = None) -> Adw.ToolbarView:
        toolbar, _, content, _ = make_page_layout(header=header)
        content.append(
            Gtk.Label(
                label="Scope Recovery inspects the registry and private transaction evidence. "
                "This is not a split editor, scope backup restore, migration, or activation. "
                "Canonical hashes do not establish runtime loading or Lua semantics. "
                "Nothing is converted or repaired implicitly. Attune sends no reload IPC; "
                "Hyprland may auto-reload watched files. "
                "Separate scope renames are not pair-atomic.",
                xalign=0,
                wrap=True,
                use_markup=False,
            )
        )
        self._refresh = Gtk.Button(label="Refresh Scope Assessment")
        self._refresh.connect("clicked", lambda _button: self.refresh())
        content.append(self._refresh)
        self._status = Gtk.Label(label="Not observed yet", xalign=0, wrap=True, selectable=True)
        content.append(self._status)
        self._rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.append(self._rows)
        self._feedback = Gtk.Label(xalign=0, wrap=True, selectable=True, use_markup=False)
        content.append(self._feedback)
        self._review = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.append(self._review)
        self._cancel = Gtk.Button(label="Cancel Assessment or Review")
        self._cancel.connect("clicked", lambda _button: self.cancel_review())
        content.append(self._cancel)
        self._commit = Gtk.Button(label="Commit Reviewed Scope Recovery")
        self._commit.add_css_class("destructive-action")
        self._commit.set_sensitive(False)
        self._commit.connect("clicked", lambda _button: self.commit_reviewed())
        content.append(self._commit)
        return toolbar

    def bind_lifecycle(self, window: Gtk.Window) -> None:
        window.connect("close-request", self._on_close_request)
        window.connect("unrealize", self.close)
        window.connect("destroy", self.close)
        app = window.get_application()
        if app is not None:

            def removed(application: Gtk.Application, removed_window: Gtk.Window) -> None:
                if removed_window is window:
                    self.close()
                    application.disconnect(handler)

            handler = app.connect("window-removed", removed)

    def _on_close_request(self, *_args) -> bool:
        if self._writing:
            self._feedback.set_label("Scope recovery is writing. Wait for its worker outcome.")
        return self._writing

    def ensure_loaded(self) -> None:
        if not self._started:
            self.refresh()

    def seed_assessment(self, assessment: scoped_recovery.LayoutAssessment) -> None:
        if self._loading or self._writing or self._closed:
            return
        if (assessment.config_root, assessment.state_root) != (
            str(self._config_root),
            str(self._state_root),
        ):
            raise ValueError("Assessment context differs from page context")
        self._started = True
        self._assessment = assessment
        if self.on_assessment is not None:
            self.on_assessment(assessment)
        self._render_assessment(assessment)

    def _render_assessment(self, assessment: scoped_recovery.LayoutAssessment) -> None:
        details = [
            f"Mode: {assessment.mode}. Registry: {assessment.registry_condition}.",
            f"Config root: {assessment.config_root}\nState root: {assessment.state_root}",
            f"Transaction rows: {len(assessment.transactions)} (maximum 32). "
            f"Truncated: {assessment.truncated}",
            *assessment.notes,
        ]
        if assessment.registry_error:
            details.append(assessment.registry_error)
        for scope in assessment.canonical_pair:
            details.append(
                f"{scope.scope}: SHA-256 {scope.source_sha256}\n"
                f"Canonical content ID: {scope.content_id}"
            )
        self._status.set_label("\n".join(details))
        clear_children(self._rows)
        for row in assessment.transactions:
            group = Adw.PreferencesGroup(title=row.transaction_id)
            direction = "rollback" if row.rollback_direction else "forward"
            label = Gtk.Label(
                label=f"Validity: {row.validity}. Actual status: {row.actual_status}.\n"
                f"Advisory phase: {row.phase or 'unknown'}. "
                f"Recorded direction: {direction if row.validity == 'verified' else 'unknown'}.\n"
                + "\n".join(row.notes),
                xalign=0,
                wrap=True,
                selectable=True,
                use_markup=False,
            )
            group.add(label)
            for action in scoped_recovery.ACTIONS:
                button = Gtk.Button(label=f"Review {action}")
                button.connect(
                    "clicked",
                    lambda _button, tx=row.transaction_id, a=action: self.prepare_action(tx, a),
                )
                group.add(button)
            self._rows.append(group)

    def refresh(self) -> None:
        if not self._closed and not self._loading and not self._writing:
            self._start_read(None, None)

    def prepare_action(self, transaction_id: str, action: str) -> None:
        if self._closed or self._loading or self._writing or self._assessment is None:
            return
        if action not in scoped_recovery.ACTIONS or not any(
            row.transaction_id == transaction_id for row in self._assessment.transactions
        ):
            return
        try:
            if self._restore_permission is not None:
                self._restore_permission()
        except Exception as exc:
            self.cancel_review()
            self._feedback.set_label(f"Preparation refused: {exc}. No changes were made.")
            return
        self._start_read(transaction_id, action)

    def _start_read(self, transaction_id: str | None, action: str | None) -> None:
        self.cancel_review()
        self._started = True
        self._loading = True
        generation = self._generation
        token = object()
        self._read_token = token
        self._refresh.set_sensitive(False)
        self._rows.set_sensitive(False)
        self._feedback.set_label(
            "Read-only assessment..."
            if action is None
            else f"Preparing {action} for {transaction_id}. Read-only validation..."
        )
        page_ref = weakref.ref(self)
        cancel = self._cancel_event
        config_root, state_root = self._config_root, self._state_root

        def complete(result, error: str | None) -> bool:
            page = page_ref()
            if page is None or page._closed:
                return GLib.SOURCE_REMOVE
            if page._read_token is not token:
                return GLib.SOURCE_REMOVE
            page._read_token = None
            if generation != page._generation:
                if page._loading:
                    page._loading = False
                    page._refresh.set_sensitive(True)
                    page._rows.set_sensitive(True)
                return GLib.SOURCE_REMOVE
            page._generation += 1
            page._loading = False
            page._refresh.set_sensitive(True)
            page._rows.set_sensitive(True)
            if error is not None:
                if action is None:
                    page._assessment = None
                    clear_children(page._rows)
                    if page.on_assessment_error is not None:
                        page.on_assessment_error(error)
                page._feedback.set_label(f"Read-only operation refused: {error}. No changes made.")
            elif isinstance(result, scoped_recovery.LayoutAssessment):
                try:
                    page.seed_assessment(result)
                except Exception as exc:
                    page._assessment = None
                    clear_children(page._rows)
                    page._feedback.set_label(f"Assessment unavailable: {exc}. No changes made.")
                else:
                    page._feedback.set_label(
                        "Assessment complete. Choose a transaction and action."
                    )
            elif isinstance(result, scoped_recovery.ScopedRecoveryDraft):
                try:
                    page._show_review(result)
                except Exception as exc:
                    page.cancel_review()
                    page._feedback.set_label(
                        f"Could not show complete review: {exc}. No changes made."
                    )
            return GLib.SOURCE_REMOVE

        def collect() -> None:
            try:
                if transaction_id is None or action is None:
                    result = scoped_recovery.run_assess(
                        config_root, state_root, cancel_event=cancel
                    )
                else:
                    result = scoped_recovery.run_prepare_action(
                        config_root, state_root, transaction_id, action, cancel_event=cancel
                    )
            except Exception as exc:
                GLib.idle_add(complete, None, str(exc))
            else:
                GLib.idle_add(complete, result, None)

        try:
            threading.Thread(target=collect, daemon=False).start()
        except Exception as exc:
            complete(None, str(exc))

    def _show_review(self, draft: scoped_recovery.ScopedRecoveryDraft) -> None:
        clear_children(self._review)
        plan = draft.plan
        self._review.append(
            Gtk.Label(
                label=f"CURRENT -> GOAL: {draft.action}, transaction {draft.transaction_id}\n"
                f"Observed: {plan.observed_at}\nReview identity: {plan.review_hash}\n"
                f"Snapshot: {draft.snapshot_id}\nOriginal review: {draft.original_review_hash}\n"
                f"Private evidence: {draft.private_digest}\n"
                f"Installation evidence: {plan.evidence.evidence_hash}\n{plan.notice}",
                xalign=0,
                wrap=True,
                selectable=True,
                use_markup=False,
            )
        )
        for scope in plan.scopes:
            self._review.append(
                Gtk.Label(
                    label=f"{scope.scope.value}: CURRENT -> GOAL\n"
                    f"Lexical: {scope.lexical_path}\nResolved: {scope.resolved_path}\n"
                    f"CURRENT SHA-256: {scope.previous_sha256}\n"
                    f"GOAL SHA-256: {scope.proposed_sha256}\n"
                    f"CURRENT content ID: {scope.previous_content_id}\n"
                    f"GOAL content ID: {scope.proposed_content_id}\n"
                    f"Diff SHA-256: {scope.diff_sha256}",
                    xalign=0,
                    wrap=True,
                    selectable=True,
                    use_markup=False,
                )
            )
            diff = ConfigDiffWidget()
            diff.set_precomputed_diff(
                scope.diff,
                added_lines=scope.added_lines,
                removed_lines=scope.removed_lines,
                title=f"{scope.scope.value}: CURRENT -> GOAL",
            )
            self._review.append(diff)
        self._draft = draft
        self._commit.set_sensitive(True)
        self._feedback.set_label(
            "Both scopes reviewed above, including unchanged scopes. "
            "Commit is a separate explicit action. Watchers may reload files."
        )

    def cancel_review(self) -> None:
        if self._writing:
            return
        self._generation += 1
        self._cancel_event.set()
        self._cancel_event = threading.Event()
        self._draft = None
        clear_children(self._review)
        self._commit.set_sensitive(False)
        # A cancelled worker retains the slot until its completion; no overlapping children.
        if not self._loading:
            self._refresh.set_sensitive(True)
            self._rows.set_sensitive(True)

    def commit_reviewed(self) -> None:
        if self._closed or self._loading or self._writing or self._draft is None:
            return
        draft = self._draft
        self._draft = None
        self._commit.set_sensitive(False)
        try:
            if self._restore_permission is not None:
                self._restore_permission()
            if self._begin_restore is not None:
                self._begin_restore()
        except Exception as exc:
            self._feedback.set_label(f"Commit refused: {exc}. Prepare a fresh review.")
            return
        self._writing = True
        token = object()
        self._write_token = token
        self._refresh.set_sensitive(False)
        self._rows.set_sensitive(False)
        self._cancel.set_sensitive(False)
        self._feedback.set_label("Writing reviewed recovery. Wait for the worker outcome.")

        def complete(result: PublicationResult | None, error: str | None, uncertain: bool) -> bool:
            if not self._writing or self._write_token is not token:
                return GLib.SOURCE_REMOVE
            self.scope_may_have_changed |= uncertain or (
                result is not None and result.scope_may_have_changed
            )
            self.journal_may_have_changed |= uncertain or (
                result is not None and result.journal_may_have_changed
            )
            invalidate = self.scope_may_have_changed or self.journal_may_have_changed
            try:
                if self._finish_restore is not None:
                    self._finish_restore(invalidate)
            except Exception as exc:
                error = f"{error or ''} Editor notification failed: {exc}. Restart Attune."
            finally:
                self._writing = False
                self._cancel.set_sensitive(True)
                self.cancel_review()
            self._feedback.set_label(
                f"Outcome: {result.outcome if result else 'uncertain failure'}. "
                f"Pending: {result.pending if result else 'unknown'}. "
                f"Scope may have changed: {self.scope_may_have_changed}. "
                f"Journal may have changed: {self.journal_may_have_changed}.\n"
                f"{error or (result.error if result else '') or ''}\n"
                "Refresh assessment and prepare a fresh review for another action. "
                "The old editor baseline has not been marked saved."
            )
            return GLib.SOURCE_REMOVE

        def commit() -> None:
            try:
                result = scoped_recovery.commit_action(draft)
            except Exception as exc:
                GLib.idle_add(complete, None, str(exc), True)
            else:
                GLib.idle_add(complete, result, None, False)

        try:
            threading.Thread(target=commit, daemon=False).start()
        except Exception as exc:
            complete(None, str(exc), False)

    def close(self, *_args) -> None:
        if self._writing:
            return
        self._closed = True
        self.cancel_review()
