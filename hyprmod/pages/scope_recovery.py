"""Explicit scoped journal recovery, separate from v1 backup restoration."""

import re
import threading
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from gi.repository import Adw, GLib, Gtk

from hyprmod.core import scoped_recovery, scoped_restore
from hyprmod.core.scoped_backups import BackupDescriptor
from hyprmod.core.scoped_review import GroupReviewPlan
from hyprmod.core.scopes import Scope
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
        self.on_scoped_evidence: Callable[[], None] | None = None
        self._assessment: scoped_recovery.LayoutAssessment | None = None
        self._draft: scoped_recovery.ScopedRecoveryDraft | None = None
        self._restore_draft: scoped_restore.ScopedRestoreDraft | None = None
        self._listing: scoped_restore.ScopedRestoreListing | None = None
        self._loading = False
        self._started = False
        self._closed = False
        self._generation = 0
        self._read_token: object | None = None
        self._writing = False
        self._write_token: object | None = None
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
                "Scoped canonical historical restore is available after explicit review. "
                "Foreign preservation, migration, and split editor Save remain unavailable. "
                "Canonical hashes do not establish runtime loading or Lua semantics. "
                "Nothing is converted or repaired implicitly. Attune sends no reload IPC; "
                "Hyprland may auto-reload watched files. "
                "Separate scope renames are not pair-atomic.",
                xalign=0,
                wrap=True,
                use_markup=False,
            )
        )
        content.append(Gtk.Label(label="Transaction recovery actions", xalign=0))
        self._refresh = Gtk.Button(label="Refresh Scope Assessment")
        self._refresh.connect("clicked", lambda _button: self.refresh())
        content.append(self._refresh)
        self._status = Gtk.Label(label="Not observed yet", xalign=0, wrap=True, selectable=True)
        content.append(self._status)
        self._rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.append(self._rows)
        content.append(Gtk.Label(label="Historical source review", xalign=0))
        content.append(
            Gtk.Label(
                label="Canonical history is not publication proof. A terminal phase does not "
                "prove that prior or proposed bytes were installed. Canonical restore requires "
                "a separate explicit commit; v1 conversion is unavailable.",
                xalign=0,
                wrap=True,
                use_markup=False,
            )
        )
        self._browse = Gtk.Button(label="Browse Historical Sources")
        self._browse.connect("clicked", lambda _button: self.browse_sources())
        content.append(self._browse)
        self._history_status = Gtk.Label(
            label="Historical sources not requested",
            xalign=0,
            wrap=True,
            selectable=True,
            use_markup=False,
        )
        content.append(self._history_status)
        self._history_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.append(self._history_rows)
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
        self._restore_commit = Gtk.Button(label="Commit Reviewed Historical Restore")
        self._restore_commit.add_css_class("destructive-action")
        self._restore_commit.set_sensitive(False)
        self._restore_commit.connect("clicked", lambda _button: self.commit_reviewed_restore())
        content.append(self._restore_commit)
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
            self._start_read("assess")

    def browse_sources(self) -> None:
        if not self._closed and not self._loading and not self._writing:
            self._start_read("list")

    def prepare_source(self, transaction_id: str, scope: Scope, side: str) -> None:
        listing = self._listing
        if self._closed or self._loading or self._writing or listing is None:
            return
        if listing.status != "observed" or not listing.scan_complete:
            return
        if not any(
            row.transaction_id == transaction_id
            and row.eligibility == "reviewable"
            and any(source.scope is scope and source.side == side for source in row.sources)
            for row in listing.transactions
        ):
            return
        try:
            if self._restore_permission is not None:
                self._restore_permission()
        except Exception as exc:
            self.cancel_review()
            self._feedback.set_label(f"Preparation refused: {exc}. No changes were made.")
            return
        self._start_read("restore", transaction_id, side, scope)

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
        self._start_read("recovery", transaction_id, action)

    def _start_read(
        self,
        mode: Literal["assess", "recovery", "list", "restore"],
        transaction_id: str = "",
        action: str = "",
        scope: Scope | None = None,
    ) -> None:
        listing = self._listing if mode == "restore" else None
        self.cancel_review()
        self._listing = listing
        self._started = True
        self._loading = True
        generation = self._generation
        token = object()
        self._read_token = token
        self._refresh.set_sensitive(False)
        self._browse.set_sensitive(False)
        self._rows.set_sensitive(False)
        self._history_rows.set_sensitive(False)
        self._feedback.set_label(f"Read-only {mode}: {transaction_id} {action}...")
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
                    page._browse.set_sensitive(True)
                    page._rows.set_sensitive(True)
                    page._history_rows.set_sensitive(True)
                return GLib.SOURCE_REMOVE
            page._generation += 1
            page._loading = False
            page._refresh.set_sensitive(True)
            page._browse.set_sensitive(True)
            page._rows.set_sensitive(True)
            page._history_rows.set_sensitive(True)
            try:
                if error is not None:
                    raise ValueError(error)
                expected_type = {
                    "assess": scoped_recovery.LayoutAssessment,
                    "recovery": scoped_recovery.ScopedRecoveryDraft,
                    "list": scoped_restore.ScopedRestoreListing,
                    "restore": scoped_restore.ScopedRestoreDraft,
                }[mode]
                if type(result) is not expected_type:
                    raise ValueError(f"Unexpected {mode} result type: {type(result).__name__}")
                if (result.config_root, result.state_root) != (str(config_root), str(state_root)):
                    raise ValueError(
                        f"Unexpected {mode} result roots: "
                        f"{result.config_root!r}, {result.state_root!r}"
                    )
                if mode == "recovery" and (result.transaction_id, result.action) != (
                    transaction_id,
                    action,
                ):
                    raise ValueError("Unexpected recovery transaction/action")
                if mode == "restore" and (result.transaction_id, result.scope, result.side) != (
                    transaction_id,
                    scope,
                    action,
                ):
                    raise ValueError("Unexpected restore transaction/scope/side")
                if page.on_scoped_evidence is not None and (
                    mode == "restore"
                    or (mode == "list" and (result.status == "observed" or result.transactions))
                ):
                    page.on_scoped_evidence()
                if mode == "assess":
                    page.seed_assessment(result)
                    page._feedback.set_label(
                        "Assessment complete. Choose a transaction and action."
                    )
                elif mode == "recovery":
                    page._show_review(result)
                elif mode == "list":
                    page._render_listing(result)
                    page._feedback.set_label("Historical listing complete. No changes made.")
                else:
                    if listing is not None:
                        page._render_listing(listing)
                    page._show_source_review(result)
            except Exception as exc:
                error = str(exc)
                page.cancel_review()
                page._history_status.set_label(f"Historical sources unavailable: {error}")
                page._feedback.set_label(f"Read-only operation refused: {error}. No changes made.")
                if mode == "assess":
                    page._assessment = None
                    clear_children(page._rows)
                    page._status.set_label(f"Assessment unavailable: {error}")
                    if page.on_assessment_error is not None:
                        page.on_assessment_error(error)
            return GLib.SOURCE_REMOVE

        def collect() -> None:
            try:
                if mode == "assess":
                    result = scoped_recovery.run_assess(
                        config_root, state_root, cancel_event=cancel
                    )
                elif mode == "recovery":
                    result = scoped_recovery.run_prepare_action(
                        config_root, state_root, transaction_id, action, cancel_event=cancel
                    )
                elif mode == "list":
                    result = scoped_restore.run_list(config_root, state_root, cancel_event=cancel)
                elif scope is not None:
                    result = scoped_restore.run_prepare(
                        config_root, state_root, transaction_id, scope, action, cancel_event=cancel
                    )
                else:
                    raise ValueError("Historical review requires a scope")
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
                f"Snapshot: {draft.snapshot_id}\nOriginal review: {draft.original_review_hash}\n"
                f"Private evidence: {draft.private_digest}",
                xalign=0,
                wrap=True,
                selectable=True,
                use_markup=False,
            )
        )
        self._render_plan(plan)
        self._restore_draft = None
        self._restore_commit.set_sensitive(False)
        self._draft = draft
        self._commit.set_sensitive(True)
        self._feedback.set_label(
            "Both scopes reviewed above, including unchanged scopes. "
            "Commit is a separate explicit action. Watchers may reload files."
        )

    def _render_plan(self, plan: GroupReviewPlan) -> None:
        changed = ", ".join(s.value for s in plan.changed_scopes) or "none (noop)"
        self._review.append(
            Gtk.Label(
                label=f"Observed: {plan.observed_at}\nReview identity: {plan.review_hash}\n"
                f"Installation evidence: {plan.evidence.evidence_hash}\n"
                f"Changed scopes: {changed}\n"
                f"{plan.notice}",
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
                    f"Diff SHA-256: {scope.diff_sha256}\n"
                    f"Added lines: {scope.added_lines}. Removed lines: {scope.removed_lines}.\n"
                    + (
                        "Changed scope"
                        if scope.scope in plan.changed_scopes
                        else "Unchanged (noop)"
                    ),
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

    @staticmethod
    def _descriptor_text(descriptor: BackupDescriptor) -> str:
        return (
            f"Descriptor: {descriptor.name}. Kind: {descriptor.kind}. "
            f"Version: {descriptor.version}\n"
            f"SHA-256: {descriptor.sha256}\nContent ID: {descriptor.content_id}\n"
            f"Size: {descriptor.size_bytes} bytes. Counts (values, beziers, animations, monitors): "
            f"{descriptor.counts}"
        )

    def _render_listing(self, listing: scoped_restore.ScopedRestoreListing) -> None:
        self._listing = listing
        self._history_status.set_label(
            f"Global status: {listing.status}. Scan complete: {listing.scan_complete}. "
            f"Truncated: {listing.truncated}.\n"
            f"Config root: {listing.config_root}\nState root: {listing.state_root}\n"
            f"Displayed transactions: {len(listing.transactions)}; maximum "
            f"{scoped_restore.MAX_SOURCE_TRANSACTIONS}. Transport limit: "
            f"{scoped_restore.MAX_LIST_BYTES} bytes (1 MiB).\n"
            "Truncation limits displayed rows; incomplete or blocked scans cannot offer review.\n"
            + "\n".join(listing.notes)
        )
        clear_children(self._history_rows)
        for row in listing.transactions:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.append(
                Gtk.Label(
                    label=f"Transaction: {row.transaction_id}\nValidity: {row.validity}. "
                    f"Phase: {row.phase.value if row.phase else 'unknown'}. "
                    f"Eligibility: {row.eligibility}.\n" + "\n".join(row.notes),
                    xalign=0,
                    wrap=True,
                    selectable=True,
                    use_markup=False,
                )
            )
            for source in row.sources:
                box.append(
                    Gtk.Label(
                        label=f"Source: {source.scope.value} / {source.side}\n"
                        + self._descriptor_text(source.descriptor),
                        xalign=0,
                        wrap=True,
                        selectable=True,
                        use_markup=False,
                    )
                )
                if (
                    listing.status == "observed"
                    and listing.scan_complete
                    and row.eligibility == "reviewable"
                ):
                    button = Gtk.Button(label=f"Review {source.scope.value} {source.side}")
                    button.connect(
                        "clicked",
                        lambda _button, tx=row.transaction_id, s=source.scope, side=source.side: (
                            self.prepare_source(tx, s, side)
                        ),
                    )
                    box.append(button)
            self._history_rows.append(box)

    def _show_source_review(self, draft: scoped_restore.ScopedRestoreDraft) -> None:
        self._draft = None
        self._commit.set_sensitive(False)
        clear_children(self._review)
        self._review.append(
            Gtk.Label(
                label=f"Historical source transaction: {draft.transaction_id}\n"
                f"Source: {draft.scope.value} / {draft.side}. Phase: {draft.source_phase.value}\n"
                f"Snapshot: {draft.source_snapshot_id}\n"
                f"Original source review: {draft.source_snapshot.plan.review_hash}\n"
                f"Private evidence: {draft.source_private_digest}\n"
                + self._descriptor_text(draft.selected_descriptor)
                + "\nCanonical history, not proof of publication.",
                xalign=0,
                wrap=True,
                selectable=True,
                use_markup=False,
            )
        )
        self._render_plan(draft.plan)
        self._restore_draft = draft
        self._restore_commit.set_sensitive(True)
        self._feedback.set_label(
            "Historical CURRENT -> GOAL review. Both scopes shown, including the unchanged "
            "sibling. Nothing was written. Historical restore requires explicit commit; "
            "transaction recovery commit is disabled. Watchers may auto-reload; no reload IPC "
            "is sent. Separate scope renames are not pair-atomic."
        )

    def cancel_review(self) -> None:
        if self._writing:
            return
        self._generation += 1
        self._cancel_event.set()
        self._cancel_event = threading.Event()
        self._draft = None
        self._restore_draft = None
        self._listing = None
        clear_children(self._history_rows)
        self._history_status.set_label("Historical sources cleared. Browse to observe again.")
        clear_children(self._review)
        self._commit.set_sensitive(False)
        self._restore_commit.set_sensitive(False)
        # A cancelled worker retains the slot until its completion; no overlapping children.
        if not self._loading:
            self._refresh.set_sensitive(True)
            self._browse.set_sensitive(True)
            self._rows.set_sensitive(True)
            self._history_rows.set_sensitive(True)

    def commit_reviewed(self) -> None:
        if self._closed or self._loading or self._writing or self._draft is None:
            return
        draft = self._draft
        self._commit_write(
            lambda: scoped_recovery.commit_action(draft),
            draft.transaction_id,
            draft.action,
            bool(draft.plan.changed_scopes),
        )

    def commit_reviewed_restore(self) -> None:
        if self._closed or self._loading or self._writing or self._restore_draft is None:
            return
        draft = self._restore_draft
        self._commit_write(
            lambda: scoped_restore.commit_restore(draft),
            draft.transaction_id,
            "restore",
            bool(draft.plan.changed_scopes),
        )

    def _commit_write(
        self,
        commit_callback: Callable[[], PublicationResult],
        transaction_id: str,
        action: str,
        changed: bool,
    ) -> None:
        self.cancel_review()
        self._assessment = None
        clear_children(self._rows)
        delegated = threading.Event()
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

        def complete(result: PublicationResult | None, error: str | None, uncertain: bool) -> bool:
            if self._write_token is not token:
                return GLib.SOURCE_REMOVE
            # Retire before owner callbacks, which can reenter this completion.
            self._write_token = None
            try:
                if result is not None:
                    valid = (
                        type(result) is PublicationResult
                        and all(
                            type(flag) is bool
                            for flag in (
                                result.pending,
                                result.scope_may_have_changed,
                                result.journal_may_have_changed,
                            )
                        )
                        and type(result.outcome) is str
                        and result.outcome in ("committed", "aborted", "no-op", "failed")
                        and (result.error is None or type(result.error) is str)
                        and (
                            result.transaction_id is None
                            or (
                                type(result.transaction_id) is str
                                and re.fullmatch("[0-9a-f]{32}", result.transaction_id) is not None
                            )
                        )
                    )
                    if valid and action == "restore":
                        valid = result.transaction_id != transaction_id and (
                            (
                                result.outcome == "committed"
                                and changed
                                and result.transaction_id is not None
                                and not result.pending
                            )
                            or (
                                result.outcome == "no-op"
                                and not changed
                                and result.transaction_id is None
                                and not result.pending
                                and not result.scope_may_have_changed
                                and not result.journal_may_have_changed
                            )
                            or (
                                result.outcome == "failed"
                                and (
                                    (result.transaction_id is not None and result.pending)
                                    or (
                                        result.transaction_id is None
                                        and not result.pending
                                        and not result.scope_may_have_changed
                                        and not result.journal_may_have_changed
                                    )
                                )
                            )
                        )
                    elif valid:
                        expected = "aborted" if action in ("rollback", "abandon") else "committed"
                        valid = result.transaction_id == transaction_id and (
                            result.outcome == "failed"
                            or (result.outcome == expected and not result.pending)
                        )
                    if not valid:
                        result = None
                        uncertain = True
                        error = "Unknown/untrusted worker result; transaction identity unavailable."
                elif delegated.is_set():
                    uncertain = True
            except Exception:
                result = None
                uncertain = True
                error = "Unknown/untrusted worker result; transaction identity unavailable."
            try:
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
                identity = ""
                if action == "restore":
                    new_id = (
                        result.transaction_id or "none allocated"
                        if result is not None
                        else "unknown/untrusted"
                        if uncertain
                        else "none allocated"
                    )
                    identity = (
                        f"Historical source transaction: {transaction_id}\n"
                        f"New restore transaction: {new_id}\n"
                    )
                    if result is not None and result.pending:
                        identity += (
                            "Refresh assessment and review recovery for the new restore "
                            "transaction, not the terminal historical source.\n"
                        )
                self._feedback.set_label(
                    identity + f"Outcome: {result.outcome if result else 'unknown/untrusted'}. "
                    f"Pending: {result.pending if result else 'unknown'}. "
                    f"Scope may have changed: {self.scope_may_have_changed}. "
                    f"Journal may have changed: {self.journal_may_have_changed}.\n"
                    f"{error or (result.error if result else '') or ''}\n"
                    "Refresh assessment and prepare a fresh review for another action. "
                    "The old editor baseline has not been marked saved."
                )
            except Exception:
                # Feedback failure must not retain the page's writer slot.
                pass
            finally:
                self._draft = None
                self._restore_draft = None
                self._assessment = None
                self._listing = None
                try:
                    for container in (self._rows, self._history_rows, self._review):
                        try:
                            clear_children(container)
                        except Exception:
                            pass
                    for control in (
                        self._cancel,
                        self._refresh,
                        self._browse,
                        self._rows,
                        self._history_rows,
                        self._commit,
                        self._restore_commit,
                    ):
                        try:
                            control.set_sensitive(
                                control is not self._commit and control is not self._restore_commit
                            )
                        except Exception:
                            pass
                finally:
                    self._writing = False
            return GLib.SOURCE_REMOVE

        def commit() -> None:
            try:
                delegated.set()
                result = commit_callback()
            except Exception as exc:
                GLib.idle_add(complete, None, str(exc), True)
            else:
                GLib.idle_add(complete, result, None, False)

        try:
            self._refresh.set_sensitive(False)
            self._browse.set_sensitive(False)
            self._rows.set_sensitive(False)
            self._history_rows.set_sensitive(False)
            self._cancel.set_sensitive(False)
            threading.Thread(target=commit, daemon=False).start()
        except Exception as exc:
            if delegated.is_set():
                # A start implementation may raise after entry; keep ownership until completion.
                return
            complete(None, str(exc), False)

    def close(self, *_args) -> None:
        if self._writing:
            return
        self._closed = True
        self.cancel_review()
