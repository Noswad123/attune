"""Opt-in Broadway recovery checks. Shared conftest isolates HOME and all XDG roots."""

import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import MethodType
from typing import cast
from unittest.mock import MagicMock

import pytest
from gi.repository import Adw, GLib, Gtk
from hyprland_socket import HyprlandError

from hyprmod.core import config, scoped_backups, scoped_recovery, scoped_restore, scoped_review
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_publication import PublicationResult
from hyprmod.core.transaction_records import GroupSnapshot, Phase
from hyprmod.pages.scope_recovery import ScopeRecoveryPage
from hyprmod.ui import clear_children
from hyprmod.window import HyprModWindow
from tests.test_scoped_review import appearance
from tests.test_scoped_review import evidence as evidence
from tests.test_transaction_store import plan as plan

pytestmark = pytest.mark.skipif(
    os.environ.get("ATTUNE_GUI_SMOKE") != "1" or os.environ.get("GDK_BACKEND") != "broadway",
    reason="set ATTUNE_GUI_SMOKE=1 with an isolated Broadway display",
)


def wait_for(predicate):
    deadline = time.monotonic() + 5
    context = GLib.MainContext.default()
    while not predicate() and time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.005)
    assert predicate()


def widgets(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from widgets(child)
        child = child.get_next_sibling()


@pytest.fixture(autouse=True)
def no_live_effects(monkeypatch):
    def offline():
        raise HyprlandError("IPC disabled in isolated recovery tests")

    monkeypatch.setattr("hyprland_socket.get_version", offline)
    for name in ("run_assess", "run_prepare_action", "commit_action"):
        monkeypatch.setattr(
            scoped_recovery,
            name,
            MagicMock(side_effect=AssertionError("Mock recovery service explicitly")),
        )
    for name in ("run_list", "run_prepare", "commit_restore"):
        monkeypatch.setattr(
            scoped_restore,
            name,
            MagicMock(side_effect=AssertionError("Mock historical service explicitly")),
        )


@pytest.fixture
def recovery_context(plan, monkeypatch):
    config_root = Path(plan.evidence.config_root)
    state_root = Path(plan.evidence.state_root)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_root))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_root))
    txid = "a" * 32
    draft = scoped_recovery.ScopedRecoveryDraft(
        str(config_root),
        str(state_root),
        txid,
        "resume",
        "b" * 64,
        "c" * 64,
        plan.review_hash,
        plan,
    )
    assessment = scoped_recovery.LayoutAssessment(
        str(config_root),
        str(state_root),
        "scope-recovery-required",
        "valid",
        tuple(
            scoped_recovery.CanonicalScope(r.scope.value, r.file.source_sha256, r.content_id)
            for r in plan.evidence.routes
        ),
        None,
        (
            scoped_recovery.TransactionRow(
                txid, "verified", "prepared", False, "all-prior", ("<literal>& note",)
            ),
        ),
        False,
        (),
    )
    monkeypatch.setattr(scoped_recovery, "run_assess", MagicMock(return_value=assessment))
    monkeypatch.setattr(scoped_recovery, "run_prepare_action", MagicMock(return_value=draft))
    return assessment, draft


@pytest.fixture
def history(recovery_context, monkeypatch):
    assessment, recovery = recovery_context
    snapshot = GroupSnapshot(recovery.plan)
    sources = tuple(
        scoped_restore.RestoreSourceRow(
            review.scope,
            side,
            scoped_backups.describe_backup(
                f"{review.previous_sha256 if side == 'prior' else review.proposed_sha256}.lua",
                review.previous_text if side == "prior" else review.proposed_text,
                expected_scope=review.scope,
            ),
        )
        for review in recovery.plan.scopes
        for side in ("prior", "proposed")
    )
    row = scoped_restore.RestoreTransactionRow(
        recovery.transaction_id,
        "verified",
        Phase.COMMITTED,
        "reviewable",
        (),
        sources,
    )
    listing = scoped_restore.ScopedRestoreListing(
        assessment.config_root,
        assessment.state_root,
        "observed",
        True,
        False,
        (row,),
        (),
    )
    monkeypatch.setattr(scoped_restore, "run_list", MagicMock(return_value=listing))

    def prepare(config_root, state_root, txid, scope, side, *, cancel_event):
        assert threading.current_thread() is not threading.main_thread()
        assert (str(config_root), str(state_root), txid) == (
            listing.config_root,
            listing.state_root,
            row.transaction_id,
        )
        source = next(s for s in sources if s.scope is scope and s.side == side)
        proposals = {}
        if scope is Scope.APPEARANCE and side == "proposed":
            proposals[scope] = appearance("7")
        plan = scoped_review.build_review(recovery.plan.evidence, proposals)
        return scoped_restore.ScopedRestoreDraft(
            listing.config_root,
            listing.state_root,
            txid,
            scope,
            side,
            "d" * 64,
            Phase.COMMITTED,
            snapshot.snapshot_id,
            snapshot,
            source.descriptor,
            plan,
        )

    monkeypatch.setattr(scoped_restore, "run_prepare", MagicMock(side_effect=prepare))
    return listing


@pytest.fixture
def page(recovery_context):
    assessment, _ = recovery_context
    owner = MagicMock()
    owner._restore_in_progress = False
    owner._editor_invalidated = False
    owner.has_dirty.return_value = False
    owner._monitors_page.is_confirm_pending.return_value = False
    for name in (
        "scope_restore_permission",
        "begin_scope_restore",
        "finish_restore",
        "finish_scope_restore",
        "restore_permission",
        "editor_edit_allowed",
    ):
        setattr(owner, name, MethodType(getattr(HyprModWindow, name), owner))
    page = ScopeRecoveryPage(
        Path(assessment.config_root),
        Path(assessment.state_root),
        restore_permission=owner.scope_restore_permission,
        begin_restore=owner.begin_scope_restore,
        finish_restore=owner.finish_scope_restore,
    )
    window = Adw.Window()
    window.set_content(page.build())
    page.bind_lifecycle(window)
    window.present()
    page.ensure_loaded()
    wait_for(lambda: not page._loading)
    yield page, owner, window
    page.close()
    window.destroy()


class TestScopeRecovery:
    @pytest.mark.parametrize(
        "outcome", ["changed", "noop", "journal", "refused", "pending", "exception"]
    )
    def test_historical_writer_lifetime(self, page, history, monkeypatch, outcome):
        page, owner, window = page
        source_id = history.transactions[0].transaction_id
        page.browse_sources()
        wait_for(lambda: not page._loading)
        page.prepare_source(
            source_id, Scope.APPEARANCE, "prior" if outcome == "noop" else "proposed"
        )
        wait_for(lambda: not page._loading)
        draft = page._restore_draft
        assert draft is not None
        entered, release = threading.Event(), threading.Event()
        new_id = "e" * 32
        result = PublicationResult(
            None if outcome in ("noop", "refused") else new_id,
            "no-op"
            if outcome == "noop"
            else ("failed" if outcome in ("refused", "pending") else "committed"),
            outcome == "pending",
            outcome in ("changed", "pending"),
            outcome in ("changed", "journal", "pending"),
            "source check refused" if outcome == "refused" else None,
        )

        def commit(reviewed):
            assert reviewed is draft
            assert threading.current_thread() is not threading.main_thread()
            assert not threading.current_thread().daemon
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test worker not released")
            if outcome == "exception":
                raise RuntimeError("after delegation")
            return result

        writer = MagicMock(side_effect=commit)
        monkeypatch.setattr(scoped_restore, "commit_restore", writer)
        page.commit_reviewed()  # The recovery handler cannot consume a historical review.
        assert page._restore_draft is draft
        writer.assert_not_called()
        page._restore_commit.emit("clicked")
        try:
            assert entered.wait(3)
            assert page._draft is None and page._restore_draft is None
            assert page._assessment is None and page._listing is None
            assert page._rows.get_first_child() is None
            assert page._on_close_request()
            window.close()
            page.close()
            page.cancel_review()
            page.refresh()
            page.browse_sources()
            page.prepare_source(source_id, Scope.APPEARANCE, "prior")
            page.prepare_action(source_id, "resume")
            page.commit_reviewed()
            page.commit_reviewed_restore()
            assert not page._closed and page.restore_writing
            for control in (
                page._refresh,
                page._browse,
                page._rows,
                page._history_rows,
                page._cancel,
                page._commit,
                page._restore_commit,
            ):
                assert not control.get_sensitive()
            writer.assert_called_once_with(draft)
        finally:
            release.set()
            wait_for(lambda: not page.restore_writing)
        scope_flag = outcome in ("changed", "pending", "exception")
        journal_flag = outcome in ("changed", "journal", "pending", "exception")
        assert page.scope_may_have_changed is scope_flag
        assert page.journal_may_have_changed is journal_flag
        assert owner._editor_invalidated is (scope_flag or journal_flag)
        assert not owner._restore_in_progress
        text = page._feedback.get_text()
        assert f"Historical source transaction: {source_id}" in text
        assert "New restore transaction: " in text
        if outcome == "pending":
            assert new_id in text and "not the terminal historical source" in text
        elif outcome == "exception":
            assert "unknown/untrusted" in text
        elif outcome in ("noop", "refused"):
            assert "none allocated" in text
        owner.app_state.mark_saved.assert_not_called()
        cast(MagicMock, scoped_recovery.commit_action).assert_not_called()
        # A later clean no-op cannot clear independent sticky uncertainty flags.
        page.browse_sources()
        wait_for(lambda: not page._loading)
        page.prepare_source(source_id, Scope.APPEARANCE, "prior")
        wait_for(lambda: not page._loading)
        writer.side_effect = None
        writer.return_value = PublicationResult(None, "no-op", False, False, False)
        page.commit_reviewed_restore()
        wait_for(lambda: not page.restore_writing)
        assert page.scope_may_have_changed is scope_flag
        assert page.journal_may_have_changed is journal_flag
        assert owner._editor_invalidated is (scope_flag or journal_flag)

    @pytest.mark.parametrize("historical", [False, True])
    @pytest.mark.parametrize(
        "fault",
        [
            "none",
            "object",
            "subclass",
            "missing-field",
            "pending",
            "scope",
            "journal",
            "outcome",
            "error",
            "id",
            "identity",
            "success",
            "noop",
        ],
    )
    def test_write_result_boundary(
        self, page, history, recovery_context, monkeypatch, historical, fault
    ):
        page, owner, _ = page
        source_id = history.transactions[0].transaction_id
        if historical:
            page.browse_sources()
            wait_for(lambda: not page._loading)
            page.prepare_source(source_id, Scope.APPEARANCE, "proposed")
        else:
            page.prepare_action(source_id, "resume")
        wait_for(lambda: not page._loading)
        result = PublicationResult(
            "e" * 32 if historical else source_id, "committed", False, True, True
        )
        if fault == "none":
            result = None
        elif fault == "object":
            result = object()
        elif fault == "missing-field":
            object.__delattr__(result, "pending")
        elif fault == "subclass":
            result = type("OtherResult", (PublicationResult,), {})(
                "e" * 32, "committed", False, True, True
            )
        else:
            field, value = {
                "pending": ("pending", 0),
                "scope": ("scope_may_have_changed", 1),
                "journal": ("journal_may_have_changed", "yes"),
                "outcome": ("outcome", "other"),
                "error": ("error", 1),
                "id": ("transaction_id", "E" * 32),
                "identity": ("transaction_id", source_id if historical else "e" * 32),
                "success": ("outcome", "aborted"),
                "noop": ("outcome", "no-op"),
            }[fault]
            object.__setattr__(result, field, value)
        module, service = (
            (scoped_restore, "commit_restore") if historical else (scoped_recovery, "commit_action")
        )
        monkeypatch.setattr(module, service, MagicMock(return_value=result))
        (page.commit_reviewed_restore if historical else page.commit_reviewed)()
        wait_for(lambda: not page.restore_writing)
        assert page.scope_may_have_changed and page.journal_may_have_changed
        assert owner._editor_invalidated and not owner._restore_in_progress
        assert "unknown/untrusted" in page._feedback.get_text().lower()
        if historical:
            assert "New restore transaction: unknown/untrusted" in page._feedback.get_text()

    @pytest.mark.parametrize("blocker", ["dirty", "preview", "writer"])
    def test_historical_commit_permission_consumes_all_reviews(self, page, history, blocker):
        page, owner, _ = page
        page.browse_sources()
        wait_for(lambda: not page._loading)
        page.prepare_source(history.transactions[0].transaction_id, Scope.APPEARANCE, "prior")
        wait_for(lambda: not page._loading)
        if blocker == "dirty":
            owner.has_dirty.return_value = True
        elif blocker == "preview":
            owner._monitors_page.is_confirm_pending.return_value = True
        else:
            owner._restore_in_progress = True
        page.commit_reviewed_restore()
        assert page._draft is None and page._restore_draft is None
        assert page._assessment is None and page._listing is None
        assert not page._commit.get_sensitive() and not page._restore_commit.get_sensitive()
        cast(MagicMock, scoped_restore.commit_restore).assert_not_called()
        owner._restore_in_progress = False

    @pytest.mark.parametrize("historical", [False, True])
    @pytest.mark.parametrize(
        "control_name", ["_refresh", "_browse", "_rows", "_history_rows", "_cancel"]
    )
    def test_writer_ui_setup_failure_releases_owner(
        self, page, history, monkeypatch, historical, control_name
    ):
        page, owner, _ = page
        txid = history.transactions[0].transaction_id
        if historical:
            page.browse_sources()
            wait_for(lambda: not page._loading)
            page.prepare_source(txid, Scope.APPEARANCE, "proposed")
        else:
            page.prepare_action(txid, "resume")
        wait_for(lambda: not page._loading)
        finish = MagicMock(wraps=page._finish_restore)
        monkeypatch.setattr(page, "_finish_restore", finish)
        control = getattr(page, control_name)
        set_sensitive = control.set_sensitive

        def failing_setup(sensitive):
            if page.restore_writing and not sensitive:
                assert owner._restore_in_progress
                raise RuntimeError(f"setup failed: {control_name}")
            set_sensitive(sensitive)

        monkeypatch.setattr(control, "set_sensitive", failing_setup)
        thread = MagicMock(side_effect=AssertionError("setup must precede worker creation"))
        monkeypatch.setattr(threading, "Thread", thread)
        handler = page.commit_reviewed_restore if historical else page.commit_reviewed
        handler()
        thread.assert_not_called()
        finish.assert_called_once_with(False)
        assert not owner._restore_in_progress and not page.restore_writing
        assert page._write_token is None
        assert not page.scope_may_have_changed and not page.journal_may_have_changed
        assert page._draft is None and page._restore_draft is None
        assert page._assessment is None and page._listing is None
        for box in (page._rows, page._history_rows, page._review):
            assert box.get_first_child() is None
        assert not page._commit.get_sensitive() and not page._restore_commit.get_sensitive()
        assert f"setup failed: {control_name}" in page._feedback.get_text()
        prepare = cast(MagicMock, scoped_recovery.run_prepare_action)
        restore_prepare = cast(MagicMock, scoped_restore.run_prepare)
        prepare.reset_mock()
        restore_prepare.reset_mock()
        handler()
        page.commit_reviewed()
        page.commit_reviewed_restore()
        page.prepare_action(txid, "resume")
        page.prepare_source(txid, Scope.APPEARANCE, "proposed")
        prepare.assert_not_called()
        restore_prepare.assert_not_called()
        finish.assert_called_once_with(False)
        cast(MagicMock, scoped_recovery.commit_action).assert_not_called()
        cast(MagicMock, scoped_restore.commit_restore).assert_not_called()

    @pytest.mark.parametrize("historical", [False, True])
    @pytest.mark.parametrize("feedback_failure", [False, True])
    @pytest.mark.parametrize(
        "cleanup",
        [
            "_cancel",
            "_refresh",
            "_browse",
            "_rows",
            "_history_rows",
            "_commit",
            "_restore_commit",
            "clear_rows",
            "clear_history_rows",
            "clear_review",
        ],
    )
    def test_writer_cleanup_widget_failure_cannot_retain_authority(
        self, page, history, monkeypatch, historical, feedback_failure, cleanup
    ):
        page, owner, _ = page
        txid = history.transactions[0].transaction_id
        if historical:
            page.browse_sources()
            wait_for(lambda: not page._loading)
            page.prepare_source(txid, Scope.APPEARANCE, "proposed")
        else:
            page.prepare_action(txid, "resume")
        wait_for(lambda: not page._loading)
        writer = MagicMock(
            return_value=PublicationResult(
                "e" * 32 if historical else txid, "committed", False, True, True
            )
        )
        monkeypatch.setattr(
            scoped_restore if historical else scoped_recovery,
            "commit_restore" if historical else "commit_action",
            writer,
        )
        finish = MagicMock(wraps=page._finish_restore)
        monkeypatch.setattr(page, "_finish_restore", finish)
        queued = []
        monkeypatch.setattr(GLib, "idle_add", lambda *args: queued.append(args))
        (page.commit_reviewed_restore if historical else page.commit_reviewed)()
        wait_for(lambda: bool(queued))
        callback, *args = queued.pop()
        if feedback_failure:
            monkeypatch.setattr(page._feedback, "set_label", MagicMock(side_effect=RuntimeError))
        with monkeypatch.context() as cleanup_patch:
            if cleanup.startswith("clear"):
                target = getattr(page, cleanup.removeprefix("clear"))

                def failing_clear(container):
                    if container is target:
                        raise RuntimeError("cleanup clear failed")
                    clear_children(container)

                cleanup_patch.setattr("hyprmod.pages.scope_recovery.clear_children", failing_clear)
            else:
                control = getattr(page, cleanup)
                cleanup_patch.setattr(control, "set_sensitive", MagicMock(side_effect=RuntimeError))
            callback(*args)
        writer.assert_called_once()
        finish.assert_called_once_with(True)
        assert page._write_token is None and not page.restore_writing
        assert not owner._restore_in_progress
        assert page.scope_may_have_changed and page.journal_may_have_changed
        assert page._draft is None and page._restore_draft is None
        assert page._assessment is None and page._listing is None
        assert not page._on_close_request()
        page.commit_reviewed()
        page.commit_reviewed_restore()
        writer.assert_called_once()
        # Late completion must not release a newly acquired owner, even after cleanup failed.
        owner.begin_scope_restore()
        callback(*args)
        assert owner._restore_in_progress
        finish.assert_called_once_with(True)
        owner.finish_scope_restore(False)

    @pytest.mark.parametrize("historical", [False, True])
    @pytest.mark.parametrize("failure", ["constructor", "start", "after-entry"])
    def test_writer_start_failures(self, page, history, monkeypatch, historical, failure):
        page, owner, _ = page
        txid = history.transactions[0].transaction_id
        if historical:
            page.browse_sources()
            wait_for(lambda: not page._loading)
            page.prepare_source(txid, Scope.APPEARANCE, "proposed")
        else:
            page.prepare_action(txid, "resume")
        wait_for(lambda: not page._loading)
        queued = []
        monkeypatch.setattr(GLib, "idle_add", lambda *args: queued.append(args))
        writer = MagicMock(side_effect=RuntimeError("delegated"))
        monkeypatch.setattr(
            scoped_restore if historical else scoped_recovery,
            "commit_restore" if historical else "commit_action",
            writer,
        )
        real_thread = threading.Thread

        def constructor(*, target, daemon):
            if failure == "constructor":
                raise RuntimeError("constructor")
            worker = real_thread(target=target, daemon=daemon)

            def start():
                if failure == "after-entry":
                    worker.start()
                    worker.join(3)  # Test-only fault injection, never production GTK code.
                raise RuntimeError("start")

            return MagicMock(start=start)

        monkeypatch.setattr(threading, "Thread", constructor)
        (page.commit_reviewed_restore if historical else page.commit_reviewed)()
        if failure == "after-entry":
            assert page.restore_writing and owner._restore_in_progress
            callback, *args = queued.pop()
            callback(*args)
            writer.assert_called_once()
        else:
            writer.assert_not_called()
        assert not page.restore_writing and not owner._restore_in_progress
        assert page.scope_may_have_changed is (failure == "after-entry")
        assert page.journal_may_have_changed is (failure == "after-entry")
        assert page._draft is None and page._restore_draft is None
        assert page._assessment is None and page._listing is None

    @pytest.mark.parametrize("valid", [False, True])
    @pytest.mark.parametrize("failure", ["none", "finish", "feedback"])
    def test_completion_is_one_shot_and_exception_safe(
        self, page, recovery_context, monkeypatch, failure, valid
    ):
        page, owner, _ = page
        _, draft = recovery_context
        page.prepare_action(draft.transaction_id, "resume")
        wait_for(lambda: not page._loading)
        page.commit_reviewed_restore()
        assert page._draft is draft  # Wrong handler cannot call the other writer.
        queued = []
        monkeypatch.setattr(GLib, "idle_add", lambda *args: queued.append(args))
        monkeypatch.setattr(
            scoped_recovery,
            "commit_action",
            MagicMock(
                return_value=(
                    PublicationResult(
                        draft.transaction_id if valid else "f" * 32,
                        "committed",
                        False,
                        False,
                        True,
                    )
                )
            ),
        )
        finish = page._finish_restore

        def finishing(invalidate):
            assert page.restore_writing and page._write_token is None
            callback(*args)  # Reentrant duplicate must not finish the owner twice.
            page.commit_reviewed()
            if finish is not None:
                finish(invalidate)
            if failure == "finish":
                raise RuntimeError("notification failed")

        finish_mock = MagicMock(side_effect=finishing)
        monkeypatch.setattr(page, "_finish_restore", finish_mock)
        page.commit_reviewed()
        wait_for(lambda: bool(queued))
        callback, *args = queued.pop()
        if failure == "feedback":
            monkeypatch.setattr(page._feedback, "set_label", MagicMock(side_effect=RuntimeError))
        callback(*args)
        callback(*args)
        finish_mock.assert_called_once_with(True)
        assert not page.restore_writing and not owner._restore_in_progress
        assert page._write_token is None
        assert page._refresh.get_sensitive() and page._cancel.get_sensitive()
        # A stale callback cannot retire a newer operation's token.
        newer = object()
        page._write_token = newer
        callback(*args)
        assert page._write_token is newer
        page._write_token = None

    @pytest.mark.parametrize("action", ["rollback", "abandon", "resume", "finalize"])
    def test_recovery_success_matches_action(self, page, recovery_context, monkeypatch, action):
        page, owner, _ = page
        _, draft = recovery_context
        draft = replace(draft, action=action)
        monkeypatch.setattr(scoped_recovery, "run_prepare_action", MagicMock(return_value=draft))
        page.prepare_action(draft.transaction_id, action)
        wait_for(lambda: not page._loading)
        result = PublicationResult(
            draft.transaction_id,
            "aborted" if action in ("rollback", "abandon") else "committed",
            False,
            False,
            True,
        )
        writer = MagicMock(return_value=result)
        monkeypatch.setattr(scoped_recovery, "commit_action", writer)
        page.commit_reviewed()
        wait_for(lambda: not page.restore_writing)
        writer.assert_called_once_with(draft)
        assert not page.scope_may_have_changed and page.journal_may_have_changed
        assert not owner._restore_in_progress

    @pytest.mark.parametrize("historical", [False, True])
    def test_commit_requires_full_render(self, page, history, monkeypatch, historical):
        page, _, _ = page
        txid = history.transactions[0].transaction_id
        render = page._render_plan

        def broken_render(plan):
            assert page._draft is None and page._restore_draft is None
            assert not page._commit.get_sensitive() and not page._restore_commit.get_sensitive()
            render(plan)
            raise RuntimeError("incomplete both-scope rendering")

        monkeypatch.setattr(page, "_render_plan", broken_render)
        if historical:
            page.browse_sources()
            wait_for(lambda: not page._loading)
            page.prepare_source(txid, Scope.APPEARANCE, "prior")
        else:
            page.prepare_action(txid, "resume")
        wait_for(lambda: not page._loading)
        assert page._draft is None and page._restore_draft is None
        assert not page._commit.get_sensitive() and not page._restore_commit.get_sensitive()
        page.commit_reviewed()
        page.commit_reviewed_restore()
        cast(MagicMock, scoped_restore.commit_restore).assert_not_called()
        cast(MagicMock, scoped_recovery.commit_action).assert_not_called()

    @pytest.mark.parametrize(
        "mode,fault",
        [
            (mode, fault)
            for mode in ("assess", "recovery", "list", "restore")
            for fault in (
                "wrong-dto",
                "subclass",
                "config_root",
                "state_root",
                "none",
                "exception",
                "render",
            )
        ]
        + [
            ("recovery", "transaction_id"),
            ("recovery", "action"),
            ("restore", "transaction_id"),
            ("restore", "scope"),
            ("restore", "side"),
        ],
    )
    def test_read_boundary_refuses_unexpected_results(
        self,
        page,
        history,
        recovery_context,
        monkeypatch,
        mode,
        fault,
    ):
        page, owner, _ = page
        assessment, recovery = recovery_context
        show_source = MagicMock(wraps=page._show_source_review)
        monkeypatch.setattr(page, "_show_source_review", show_source)
        page.browse_sources()
        wait_for(lambda: not page._loading)
        page.prepare_source(recovery.transaction_id, Scope.APPEARANCE, "proposed")
        wait_for(lambda: not page._loading)
        restore = show_source.call_args.args[0]
        result = {"assess": assessment, "recovery": recovery, "list": history, "restore": restore}[
            mode
        ]
        module, service, start, renderer = {
            "assess": (scoped_recovery, "run_assess", page.refresh, "_render_assessment"),
            "recovery": (
                scoped_recovery,
                "run_prepare_action",
                lambda: page.prepare_action(recovery.transaction_id, "resume"),
                "_show_review",
            ),
            "list": (scoped_restore, "run_list", page.browse_sources, "_render_listing"),
            "restore": (
                scoped_restore,
                "run_prepare",
                lambda: page.prepare_source(recovery.transaction_id, Scope.APPEARANCE, "proposed"),
                "_show_source_review",
            ),
        }[mode]
        # Each refusal follows a successful result, with stale review and choices to revoke.
        start()
        wait_for(lambda: not page._loading)
        page._show_review(recovery)
        page._render_listing(history)
        assert page._draft is recovery and page._listing is history
        begin, finish, assessment_error = MagicMock(), MagicMock(), MagicMock()
        monkeypatch.setattr(page, "_begin_restore", begin)
        monkeypatch.setattr(page, "_finish_restore", finish)
        page.on_assessment_error = assessment_error
        scoped_evidence = MagicMock()
        page.on_scoped_evidence = scoped_evidence
        literal = "R&D <literal>"
        if fault == "wrong-dto":
            result = assessment if mode == "recovery" else recovery
        elif fault == "subclass":
            subclass = type("UnexpectedResult", (type(result),), {})
            result = subclass(
                **{name: getattr(result, name) for name in result.__dataclass_fields__}
            )
        elif fault == "none":
            result = None
        elif fault in ("config_root", "state_root", "transaction_id", "action", "scope", "side"):
            result = replace(result)
            echoes = {
                "config_root": str(Path(assessment.config_root).parent / literal),
                "state_root": str(Path(assessment.state_root).parent / literal),
                "transaction_id": "f" * 32,
                "action": "rollback",
                "scope": Scope.DISPLAYS,
                "side": "prior",
            }
            # Inject service-boundary echoes without invoking deep DTO validation on GTK.
            object.__setattr__(result, fault, echoes[fault])
        collector = MagicMock(return_value=result)
        if fault == "exception":
            collector.side_effect = RuntimeError(literal)
        monkeypatch.setattr(module, service, collector)
        if fault == "render":
            render = getattr(page, renderer)

            def partial_render(value):
                if mode in ("list", "restore"):
                    scoped_evidence.assert_called_once_with()
                render(value)
                raise RuntimeError(literal)

            monkeypatch.setattr(page, renderer, partial_render)
        start()
        wait_for(lambda: not page._loading)
        collector.assert_called_once()
        assert page._draft is None and page._listing is None
        assert page._restore_draft is None and not page._restore_commit.get_sensitive()
        assert page._review.get_first_child() is None
        assert page._history_rows.get_first_child() is None
        assert not page._commit.get_sensitive()
        assert page._read_token is None
        feedback = page._feedback.get_text()
        assert "Read-only operation refused:" in feedback
        assert "No changes made" in feedback
        assert not page._feedback.get_use_markup()
        assert not page._history_status.get_use_markup()
        if fault in ("exception", "render", "config_root", "state_root"):
            assert literal in feedback and literal in page._history_status.get_text()
        if mode == "assess":
            assert page._assessment is None
            assert page._rows.get_first_child() is None
            assessment_error.assert_called_once()
            assert assessment_error.call_args.args[0] in feedback
        else:
            assessment_error.assert_not_called()
        if mode in ("list", "restore") and fault == "render":
            scoped_evidence.assert_called_once_with()
        else:
            scoped_evidence.assert_not_called()
        page.commit_reviewed()
        page._commit.emit("clicked")
        cast(MagicMock, scoped_recovery.commit_action).assert_not_called()
        begin.assert_not_called()
        finish.assert_not_called()
        assert not owner._restore_in_progress

    def test_history_request_selection_and_recovery_transition(
        self,
        page,
        history,
        recovery_context,
    ):
        page, owner, _ = page
        _, recovery = recovery_context
        collector = cast(MagicMock, scoped_restore.run_list)
        collector.assert_not_called()
        page.seed_assessment(
            replace(
                recovery_context[0],
                mode="blocked",
                transactions=(
                    replace(
                        recovery_context[0].transactions[0],
                        actual_status="conflict",
                        phase="committed",
                    ),
                ),
            )
        )
        page.prepare_action(recovery.transaction_id, "resume")
        wait_for(lambda: page._draft is not None)
        page._browse.emit("clicked")
        assert page._draft is None and not page._commit.get_sensitive()
        wait_for(lambda: not page._loading)
        buttons = [w for w in widgets(page._history_rows) if isinstance(w, Gtk.Button)]
        assert [b.get_label() for b in buttons] == [
            f"Review {s.scope.value} {s.side}" for s in history.transactions[0].sources
        ]
        page.prepare_source("f" * 32, Scope.APPEARANCE, "proposed")
        page.prepare_source(recovery.transaction_id, Scope.APPEARANCE, "unknown")
        cast(MagicMock, scoped_restore.run_prepare).assert_not_called()
        for button in buttons:
            button.emit("clicked")
            wait_for(lambda: not page._loading)
            labels = [w for w in widgets(page._review) if isinstance(w, Gtk.Label)]
            assert all(not label.get_use_markup() for label in labels)
            texts = [label.get_text() for label in labels]
            assert any("Historical source transaction" in text for text in texts)
            assert any("Unchanged (noop)" in text for text in texts)
            assert len([w for w in widgets(page._review) if isinstance(w, Gtk.TextView)]) == 2
            assert page._draft is None and not page._commit.get_sensitive()
            assert page._restore_draft is not None and page._restore_commit.get_sensitive()
            page.commit_reviewed()
        cast(MagicMock, scoped_recovery.commit_action).assert_not_called()
        assert not owner._restore_in_progress
        owner.app_state.mark_saved.assert_not_called()
        cast(MagicMock, scoped_restore.commit_restore).assert_not_called()
        page.prepare_action(recovery.transaction_id, "resume")
        assert page._draft is None
        wait_for(lambda: page._draft is recovery)
        assert page._history_rows.get_first_child() is None

    @pytest.mark.parametrize("side", ["prior", "proposed"])
    def test_history_complete_precomputed_review(self, page, history, monkeypatch, side):
        page, _, _ = page
        begin, finish = MagicMock(), MagicMock()
        monkeypatch.setattr(page, "_begin_restore", begin)
        monkeypatch.setattr(page, "_finish_restore", finish)
        show = MagicMock(wraps=page._show_source_review)
        monkeypatch.setattr(page, "_show_source_review", show)
        page.browse_sources()
        wait_for(lambda: not page._loading)
        page.prepare_source(history.transactions[0].transaction_id, Scope.APPEARANCE, side)
        wait_for(lambda: not page._loading)
        draft = show.call_args.args[0]
        assert page._restore_draft is draft and page._restore_commit.get_sensitive()
        assert not page._commit.get_sensitive()
        for module, name in (
            (scoped_review, "_diff"),
            (scoped_review, "validate_recorded_review"),
            (scoped_review, "build_review"),
            (scoped_backups, "describe_backup"),
        ):
            monkeypatch.setattr(module, name, MagicMock(side_effect=AssertionError("GTK work")))
        monkeypatch.setattr(
            scoped_restore.ScopedRestoreDraft,
            "to_json",
            MagicMock(side_effect=AssertionError("GTK serialization")),
        )
        page._show_source_review(draft)
        labels = [w.get_text() for w in widgets(page._review) if isinstance(w, Gtk.Label)]
        for identity in (
            draft.source_private_digest,
            draft.source_snapshot_id,
            draft.selected_descriptor.sha256,
            draft.selected_descriptor.content_id,
            draft.plan.review_hash,
            draft.plan.evidence.evidence_hash,
        ):
            assert any(identity in text for text in labels)
        assert any(
            f"Changed scopes: {'none (noop)' if side == 'prior' else 'appearance'}" in text
            for text in labels
        )
        views = [w for w in widgets(page._review) if isinstance(w, Gtk.TextView)]
        assert len(views) == 2
        for review, view in zip(draft.plan.scopes, views, strict=True):
            assert any(
                review.lexical_path in text
                and review.resolved_path in text
                and review.previous_sha256 in text
                and review.proposed_sha256 in text
                and review.previous_content_id in text
                and review.proposed_content_id in text
                and review.diff_sha256 in text
                and f"Added lines: {review.added_lines}" in text
                and f"Removed lines: {review.removed_lines}" in text
                for text in labels
            )
            buffer = view.get_buffer()
            assert buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True) == (
                review.diff.rstrip("\n") if review.diff else ""
            )
        page.commit_reviewed()
        cast(MagicMock, scoped_recovery.commit_action).assert_not_called()
        begin.assert_not_called()
        finish.assert_not_called()

    @pytest.mark.parametrize("blocker", ["dirty", "preview", "writer"])
    def test_history_read_allows_dirty_but_prepare_requires_permission(
        self,
        page,
        history,
        blocker,
    ):
        page, owner, _ = page
        if blocker == "dirty":
            owner.has_dirty.return_value = True
        elif blocker == "preview":
            owner._monitors_page.is_confirm_pending.return_value = True
        else:
            owner._restore_in_progress = True
        page.browse_sources()
        wait_for(lambda: not page._loading)
        assert page._listing is history
        page.prepare_source(history.transactions[0].transaction_id, Scope.APPEARANCE, "proposed")
        cast(MagicMock, scoped_restore.run_prepare).assert_not_called()
        assert page._draft is None and page._listing is None
        owner._restore_in_progress = False

    @pytest.mark.parametrize("kind", ["pending", "invalid", "truncated", "blocked"])
    def test_history_listing_status_and_limits(self, page, history, monkeypatch, kind):
        page, _, _ = page
        row = history.transactions[0]
        if kind == "truncated":
            listing = replace(
                history,
                truncated=True,
                transactions=tuple(replace(row, transaction_id=f"{i:032x}") for i in range(32)),
            )
        else:
            row = replace(row, eligibility="blocked", notes=("R&D <literal> refused",))
            if kind == "invalid":
                row = replace(row, validity="invalid", phase=None, sources=())
            elif kind == "pending":
                row = replace(row, phase=Phase.PREPARED)
            listing = replace(
                history,
                status="blocked",
                scan_complete=kind == "blocked",
                transactions=(row,),
                notes=("Pending or uninspectable evidence <literal>&",),
            )
        monkeypatch.setattr(scoped_restore, "run_list", MagicMock(return_value=listing))
        page.browse_sources()
        wait_for(lambda: not page._loading)
        text = page._history_status.get_text()
        assert f"Global status: {listing.status}" in text
        assert f"Scan complete: {listing.scan_complete}" in text
        assert f"Truncated: {listing.truncated}" in text
        assert "1048576" in text and "maximum 32" in text
        buttons = [w for w in widgets(page._history_rows) if isinstance(w, Gtk.Button)]
        assert len(buttons) == (128 if kind == "truncated" else 0)
        if kind != "truncated":
            page.prepare_source(row.transaction_id, Scope.APPEARANCE, "prior")
            cast(MagicMock, scoped_restore.run_prepare).assert_not_called()

    @pytest.mark.parametrize("operation", ["list", "prepare"])
    def test_history_failure_revokes_choices(self, page, history, monkeypatch, operation):
        page, _, _ = page
        page.browse_sources()
        wait_for(lambda: not page._loading)
        monkeypatch.setattr(
            scoped_restore,
            f"run_{operation}",
            MagicMock(
                side_effect=TimeoutError("R&D <literal>"),
            ),
        )
        if operation == "list":
            page.browse_sources()
        else:
            page.prepare_source(history.transactions[0].transaction_id, Scope.APPEARANCE, "prior")
        wait_for(lambda: not page._loading)
        assert page._listing is None and page._draft is None
        assert page._history_rows.get_first_child() is None
        assert page._review.get_first_child() is None
        assert "R&D <literal>" in page._feedback.get_text()
        assert not page._feedback.get_use_markup()
        assert not page._commit.get_sensitive()

    @pytest.mark.parametrize("operation", ["list", "prepare"])
    def test_history_cancel_close_single_slot_and_duplicates(
        self,
        page,
        history,
        monkeypatch,
        operation,
    ):
        page, _, _ = page
        page.browse_sources()
        wait_for(lambda: not page._loading)
        queued = []
        monkeypatch.setattr(GLib, "idle_add", lambda *args: queued.append(args))
        if operation == "list":
            page.browse_sources()
        else:
            page.prepare_source(history.transactions[0].transaction_id, Scope.APPEARANCE, "prior")
        wait_for(lambda: bool(queued))
        callback, *args = queued.pop()
        cancel = page._cancel_event
        page.cancel_review()
        assert cancel.is_set() and page._loading
        token = page._read_token
        page.browse_sources()
        page.refresh()
        page.prepare_action(history.transactions[0].transaction_id, "resume")
        assert page._read_token is token
        callback(*args)
        assert not page._loading and page._listing is None and page._draft is None
        page.browse_sources()
        callback(*args)
        assert page._loading
        wait_for(lambda: bool(queued))
        callback, *args = queued.pop()
        page.close()
        callback(*args)
        assert page._draft is None and page._listing is None

    def test_action_preparation_can_refuse_without_commit(
        self, page, recovery_context, monkeypatch
    ):
        page, _, _ = page
        _, draft = recovery_context
        monkeypatch.setattr(
            scoped_recovery,
            "run_prepare_action",
            MagicMock(side_effect=ValueError("Rollback direction is locked")),
        )
        page.prepare_action(draft.transaction_id, "finalize")
        wait_for(lambda: not page._loading)
        assert page._draft is None
        assert not page._commit.get_sensitive()
        assert "Rollback direction is locked" in page._feedback.get_text()
        cast(MagicMock, scoped_recovery.commit_action).assert_not_called()

    def test_explicit_complete_review_without_implicit_commit(
        self, page, recovery_context, monkeypatch
    ):
        page, owner, _ = page
        assessment, draft = recovery_context
        labels = [w.get_text() for w in widgets(page._rows) if isinstance(w, Gtk.Label)]
        assert any("Actual status: all-prior" in text for text in labels)
        assert any("Advisory phase: prepared" in text for text in labels)
        assert any("<literal>& note" in text for text in labels)
        writer = cast(MagicMock, scoped_recovery.commit_action)
        page.commit_reviewed()
        writer.assert_not_called()
        page.prepare_action(draft.transaction_id, "resume")
        wait_for(lambda: page._draft is not None)
        # Rendering must never rederive a diff on GTK.
        monkeypatch.setattr(
            scoped_review, "_diff", MagicMock(side_effect=AssertionError("GTK diff"))
        )
        page._show_review(draft)
        labels = [w.get_text() for w in widgets(page._review) if isinstance(w, Gtk.Label)]
        assert any(draft.plan.review_hash in text for text in labels)
        for scope in draft.plan.scopes:
            assert any(
                scope.lexical_path in text
                and scope.proposed_sha256 in text
                and scope.previous_sha256 in text
                for text in labels
            )
            assert any(f"{scope.scope.value}: CURRENT -> GOAL" in text for text in labels)
        views = [w for w in widgets(page._review) if isinstance(w, Gtk.TextView)]
        assert len(views) == 2
        for view, scope in zip(views, draft.plan.scopes, strict=True):
            buffer = view.get_buffer()
            assert buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True) == (
                scope.diff.rstrip("\n") if scope.diff else ""
            )
        writer.assert_not_called()
        page.cancel_review()
        page.commit_reviewed()
        writer.assert_not_called()
        owner.app_state.mark_saved.assert_not_called()
        assert assessment.mode != "legacy-clear"

    @pytest.mark.parametrize("outcome", ["changed", "journal", "exception", "refused"])
    def test_writer_lifetime_uncertainty_and_repeat_recovery(
        self, page, recovery_context, monkeypatch, outcome
    ):
        page, owner, window = page
        _, draft = recovery_context
        invalidate_cache = MagicMock()
        monkeypatch.setattr(config, "invalidate_cache", invalidate_cache)
        entered, release = threading.Event(), threading.Event()

        def commit(reviewed):
            assert reviewed is draft
            assert not threading.current_thread().daemon
            assert threading.current_thread() is not threading.main_thread()
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test worker not released")
            if outcome == "exception":
                raise RuntimeError("failure after delegation")
            return PublicationResult(
                draft.transaction_id,
                "failed" if outcome == "refused" else "committed",
                outcome == "refused",
                outcome == "changed",
                outcome in ("journal", "changed"),
            )

        monkeypatch.setattr(scoped_recovery, "commit_action", commit)
        page.prepare_action(draft.transaction_id, "resume")
        wait_for(lambda: page._draft is not None)
        page._commit.emit("clicked")
        try:
            assert entered.wait(3)
            assert page.restore_writing and owner._restore_in_progress
            assert page._on_close_request() is True
            window.close()
            assert not page._closed
            page.close()
            page.cancel_review()
            page.browse_sources()
            page.refresh()
            page.prepare_source(draft.transaction_id, Scope.APPEARANCE, "prior")
            cast(MagicMock, scoped_restore.run_list).assert_not_called()
            cast(MagicMock, scoped_restore.run_prepare).assert_not_called()
            assert page.restore_writing
            with pytest.raises(ValueError, match="Another"):
                owner.scope_restore_permission()
            with pytest.raises(ValueError, match="locked"):
                owner.restore_permission()
            owner.finish_restore(False)  # A refused v1 backup commit must not release our slot.
            assert owner._restore_in_progress
        finally:
            release.set()
            wait_for(lambda: not page.restore_writing)
        assert owner._editor_invalidated is (outcome != "refused")
        assert invalidate_cache.called is (outcome != "refused")
        assert page.scope_may_have_changed is (outcome in ("changed", "exception"))
        assert page.journal_may_have_changed is (outcome != "refused")
        assert not owner._restore_in_progress
        owner.scope_restore_permission()
        owner.app_state.mark_saved.assert_not_called()
        page.refresh()
        wait_for(lambda: not page._loading)
        page.prepare_action(draft.transaction_id, "resume")
        wait_for(lambda: page._draft is not None)

    @pytest.mark.parametrize("blocker", ["dirty", "preview", "writer"])
    def test_permission_rechecked_before_prepare_and_commit(self, page, recovery_context, blocker):
        page, owner, _ = page
        _, draft = recovery_context

        def block(active):
            if blocker == "dirty":
                owner.has_dirty.return_value = active
            elif blocker == "preview":
                owner._monitors_page.is_confirm_pending.return_value = active
            else:
                owner._restore_in_progress = active

        block(True)
        page.prepare_action(draft.transaction_id, "resume")
        cast(MagicMock, scoped_recovery.run_prepare_action).assert_not_called()
        block(False)
        page.prepare_action(draft.transaction_id, "resume")
        wait_for(lambda: page._draft is not None)
        block(True)
        page.commit_reviewed()
        cast(MagicMock, scoped_recovery.commit_action).assert_not_called()
        assert page._draft is None
        block(False)

    def test_cancel_and_late_duplicate_callbacks(self, page, recovery_context, monkeypatch):
        page, _, _ = page
        _, draft = recovery_context
        queued = []
        monkeypatch.setattr(GLib, "idle_add", lambda *args: queued.append(args))
        page.prepare_action(draft.transaction_id, "resume")
        wait_for(lambda: bool(queued))
        callback, *args = queued.pop()
        cancel = page._cancel_event
        page.cancel_review()
        assert cancel.is_set()
        page.refresh()
        assert page._loading  # Cancelled worker still owns the single slot.
        callback(*args)
        assert not page._loading and page._draft is None
        page.prepare_action(draft.transaction_id, "resume")
        callback(*args)  # Old duplicate cannot clear the new worker's slot.
        assert page._loading
        wait_for(lambda: bool(queued))
        callback, *args = queued.pop()
        page.close()
        callback(*args)
        assert page._draft is None

    def test_failed_assessment_revokes_old_rows_and_review(
        self, page, recovery_context, monkeypatch
    ):
        page, _, _ = page
        _, draft = recovery_context
        page.prepare_action(draft.transaction_id, "resume")
        wait_for(lambda: page._draft is not None)
        error_callback = MagicMock()
        page.on_assessment_error = error_callback
        monkeypatch.setattr(
            scoped_recovery, "run_assess", MagicMock(side_effect=TimeoutError("R&D <literal>"))
        )
        page.refresh()
        wait_for(lambda: not page._loading)
        assert page._draft is None and page._assessment is None
        assert page._rows.get_first_child() is None
        assert not page._commit.get_sensitive()
        assert "R&D <literal>" in page._feedback.get_text()
        error_callback.assert_called_once_with("R&D <literal>")
        prepare = cast(MagicMock, scoped_recovery.run_prepare_action)
        prepare.reset_mock()
        page.prepare_action(draft.transaction_id, "resume")
        prepare.assert_not_called()
        cast(MagicMock, scoped_recovery.commit_action).assert_not_called()

    @pytest.mark.parametrize(
        "kind",
        ["observed", "observed-empty", "blocked-rows", "blocked-empty"],
    )
    def test_normal_window_history_discovery_locks_only_positive_evidence(
        self,
        monkeypatch,
        history,
        recovery_context,
        kind,
    ):
        assessment, _ = recovery_context
        clear = replace(
            assessment,
            mode="legacy-clear",
            registry_condition="absent",
            canonical_pair=(),
            transactions=(),
        )
        monkeypatch.setattr(scoped_recovery, "run_assess", MagicMock(return_value=clear))
        if kind == "observed-empty":
            history = replace(history, transactions=())
        elif kind.startswith("blocked"):
            rows = (
                ()
                if kind == "blocked-empty"
                else (
                    replace(
                        history.transactions[0],
                        eligibility="blocked",
                        notes=("Pending evidence",),
                    ),
                )
            )
            history = replace(
                history,
                status="blocked",
                scan_complete=False,
                transactions=rows,
                notes=("Store absent or evidence blocked",),
            )
        monkeypatch.setattr(scoped_restore, "run_list", MagicMock(return_value=history))
        config.managed_path().parent.mkdir(parents=True, exist_ok=True)
        window = HyprModWindow()
        try:
            page = window._scope_recovery_page
            assert page is not None
            wait_for(lambda: not page._loading)
            assert not window._editor_invalidated
            cast(MagicMock, scoped_restore.run_list).assert_not_called()
            window._on_option_changed("decoration:rounding", 17)
            reviewed = window.review_snapshot()
            assert window.has_dirty()
            page.browse_sources()
            wait_for(lambda: not page._loading)
            assert page._listing is history
            editor = window._page_stack.get_child_by_name("general")
            assert editor is not None
            positive = kind != "blocked-empty"
            assert window._editor_invalidated is positive
            assert editor.get_sensitive() is not positive
            assert window.has_dirty() and window.review_snapshot() == reviewed
            assert page._assessment is clear
            if positive:
                message = window._hyprland_banner.get_title()
                assert "Historical scoped evidence discovered" in message
                live_set, live_apply = MagicMock(), MagicMock()
                monkeypatch.setattr(window.app_state, "set_live", live_set)
                monkeypatch.setattr(window.hypr, "apply", live_apply)
                window._on_option_changed("decoration:rounding", 19)
                window._on_paired_option_changed([("decoration:rounding", 21)])
                live_set.assert_not_called()
                live_apply.assert_not_called()
                assert window.review_snapshot() == reviewed
            if kind == "observed":
                page.prepare_source(
                    history.transactions[0].transaction_id,
                    Scope.APPEARANCE,
                    "prior",
                )
                cast(MagicMock, scoped_restore.run_prepare).assert_not_called()
                assert "Pending editor changes" in page._feedback.get_text()
            # Neither a later empty refusal nor a legacy-clear assessment unlocks discovery.
            empty = replace(
                history,
                status="blocked",
                scan_complete=False,
                transactions=(),
                notes=("Store absent",),
            )
            monkeypatch.setattr(scoped_restore, "run_list", MagicMock(return_value=empty))
            page.browse_sources()
            wait_for(lambda: not page._loading)
            page.refresh()
            wait_for(lambda: not page._loading)
            assert window._editor_invalidated is positive
            assert window.has_dirty() and window.review_snapshot() == reviewed
            utility = window._page_stack.get_child_by_name("scope-recovery")
            assert utility is not None and utility.get_sensitive()
            assert not window._restore_in_progress
            page.commit_reviewed()
            cast(MagicMock, scoped_recovery.commit_action).assert_not_called()
        finally:
            window.destroy()

    def test_normal_window_failed_refresh_locks_editor_and_retains_pending(self, monkeypatch):
        clear = scoped_recovery.LayoutAssessment(
            os.environ["XDG_CONFIG_HOME"],
            os.environ["XDG_STATE_HOME"],
            "legacy-clear",
            "absent",
            (),
            None,
            (),
            False,
            (),
        )
        assessor = MagicMock(return_value=clear)
        monkeypatch.setattr(scoped_recovery, "run_assess", assessor)
        config.managed_path().parent.mkdir(parents=True, exist_ok=True)
        window = HyprModWindow()
        try:
            page = window._scope_recovery_page
            assert page is not None
            wait_for(lambda: not page._loading)
            assert not window._editor_invalidated
            window._on_option_changed("decoration:rounding", 17)
            window.save()
            reviewed = window.review_snapshot()
            assert window.has_dirty()
            assessor.side_effect = TimeoutError("R&D <literal>")
            registry = Path(clear.config_root) / "attune/installation.json"
            registry.parent.mkdir(parents=True)
            registry.write_text("uninspectable scoped evidence")
            page.refresh()
            wait_for(lambda: not page._loading)
            assert window._editor_invalidated and window.has_dirty()
            assert "R&D <literal>" in window._hyprland_banner.get_title()
            editor = window._page_stack.get_child_by_name("general")
            assert editor is not None and not editor.get_sensitive()
            window.save_reviewed(reviewed)
            assert not config.managed_path().exists()
            assert window.has_dirty()
            assert registry.read_text() == "uninspectable scoped evidence"
        finally:
            window.destroy()

    def test_normal_window_discovery_preserves_dirty_and_utilities(
        self, monkeypatch, recovery_context
    ):
        assessment, _ = recovery_context
        monkeypatch.setenv("XDG_CONFIG_HOME", assessment.config_root)
        monkeypatch.setenv("XDG_STATE_HOME", assessment.state_root)
        # The constructor starts a bounded read-only assessment in a normal window.
        config.managed_path().parent.mkdir(parents=True, exist_ok=True)
        window = HyprModWindow()
        try:
            page = window._scope_recovery_page
            assert page is not None
            wait_for(lambda: not page._loading)
            assert window._editor_invalidated
            window.has_dirty = MagicMock(return_value=True)
            window.scope_assessed(assessment)
            assert window.has_dirty()
            with pytest.raises(ValueError, match="Pending"):
                window.scope_restore_permission()
            window.has_dirty.return_value = False
            window.scope_restore_permission()
            window.begin_scope_restore()
            with pytest.raises(ValueError):
                window.restore_permission()
            window.finish_restore(False)
            assert window._restore_in_progress
            window.finish_scope_restore(True)
            for name in ("health", "backups", "scope-recovery", "settings"):
                widget = window._page_stack.get_child_by_name(name)
                assert widget is not None and widget.get_sensitive()
            editor = window._page_stack.get_child_by_name("general")
            assert editor is not None and not editor.get_sensitive()
            assert "scope-recovery" in window._sidebar._rows_by_id
        finally:
            window.destroy()
