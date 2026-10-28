"""Explicit recovery review and protected direct writer, with no desktop effects."""

import threading
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

from hyprmod.core import recovery, restoration
from hyprmod.pages import backups as page_module
from tests import test_restore_window as restore_tests

page = restore_tests.page
scheduled = restore_tests.scheduled
window = restore_tests.window
no_unmocked_operations = restore_tests.no_unmocked_operations
finish = restore_tests.finish

DRAFT = recovery.RecoveryDraft(
    **asdict(restore_tests.DRAFT),
    current_status="foreign",
    preservation_root="/private/recovery",
    preservation_path="/private/recovery/" + "b" * 64 + ".bin",
)


def reviewed(page):
    page._draft = DRAFT
    page._recovery_ack = MagicMock()
    page._recovery_ack.get_active.return_value = True


class TestRecovery:
    @pytest.mark.parametrize("status", ["foreign", "invalid"])
    def test_explicit_prepare_freezes_selection_and_cancel_never_writes(
        self, page, scheduled, monkeypatch, status
    ):
        draft = replace(DRAFT, current_status=status)
        prepare = MagicMock(return_value=draft)
        monkeypatch.setattr(recovery, "run_prepare", prepare)
        shown = MagicMock(side_effect=lambda draft: setattr(page, "_draft", draft))
        monkeypatch.setattr(page, "_show_restore_review", shown)
        page.review_recovery(draft.backup_name)
        page.review_restoration(draft.backup_name)
        page.refresh()
        finish(scheduled)
        prepare.assert_called_once_with(
            page._output_path, draft.backup_name, cancel_event=page._cancel_event
        )
        shown.assert_called_once_with(draft)
        assert page._draft is draft and page._loading
        with pytest.raises(FrozenInstanceError):
            setattr(draft, "current_status", "owned")
        page.cancel_restoration()
        page.restore_reviewed()
        cast(MagicMock, recovery.commit_recovery).assert_not_called()
        cast(MagicMock, restoration.run_prepare).assert_not_called()
        cast(MagicMock, restoration.commit_restore).assert_not_called()

    @pytest.mark.parametrize("status", ["foreign", "invalid"])
    def test_review_exact_diff_identities_warning_and_ack_gate(self, page, monkeypatch, status):
        draft = replace(DRAFT, current_status=status)
        dialog, content, diff, label, ack = (MagicMock() for _ in range(5))
        ack.get_active.return_value = False
        buttons = []

        def button(**kwargs):
            value = MagicMock()
            buttons.append((kwargs["label"], value))
            return value

        monkeypatch.setattr(page_module.Adw, "Dialog", MagicMock(return_value=dialog))
        monkeypatch.setattr(page_module.Adw, "HeaderBar", MagicMock())
        monkeypatch.setattr(
            page_module, "make_page_layout", lambda **kw: (MagicMock(), None, content, None)
        )
        monkeypatch.setattr(page_module.Gtk, "Label", label)
        monkeypatch.setattr(page_module.Gtk, "Button", button)
        monkeypatch.setattr(page_module.Gtk, "CheckButton", MagicMock(return_value=ack))
        monkeypatch.setattr(page_module, "ConfigDiffWidget", MagicMock(return_value=diff))
        page._show_restore_review(draft)
        assert page._draft is draft
        diff.set_precomputed_diff.assert_called_once_with(
            draft.diff, added_lines=1, removed_lines=1, title="CURRENT -> RECOVERY BACKUP"
        )
        diff.set_texts.assert_not_called()
        text = label.call_args.kwargs["label"]
        for value in (
            draft.observed_at,
            draft.backup_root + "/" + draft.backup_name,
            draft.previous_sha256,
            draft.proposed_sha256,
            draft.lexical_path,
            draft.resolved_path,
            draft.preservation_path,
            f"Original status: {status}",
            "exact original bytes",
            "NOT a canonical rollback",
            "compile-only",
            "original is not compiled",
            "no Lua is executed",
            "Hyprland may auto-reload",
        ):
            assert value in text
        label.assert_called_once()
        assert label.call_args.kwargs["use_markup"] is False
        assert [name for name, _ in buttons] == ["Cancel", "Preserve and Recover Reviewed Output"]
        commit_button = buttons[1][1]
        commit_button.set_sensitive.assert_called_once_with(False)
        page.restore_reviewed()  # Public entry point must enforce acknowledgment too.
        assert page._draft is draft
        cast(MagicMock, recovery.commit_recovery).assert_not_called()
        ack.get_active.return_value = True
        ack.connect.call_args.args[1](ack)
        commit_button.set_sensitive.assert_called_with(True)
        buttons[0][1].connect.call_args.args[1](buttons[0][1])
        page.restore_reviewed()
        assert page._draft is None and page._recovery_ack is None
        cast(MagicMock, recovery.commit_recovery).assert_not_called()

    @pytest.mark.parametrize("reason", ["owned", "missing", "binary", "invalid UTF-8"])
    def test_backend_refusal_is_final_without_ui_fallback(
        self, page, scheduled, monkeypatch, reason
    ):
        prepare = MagicMock(side_effect=ValueError(reason))
        monkeypatch.setattr(recovery, "run_prepare", prepare)
        page.review_recovery(DRAFT.backup_name)
        finish(scheduled)
        assert not page._loading and page._draft is None
        page.restore_reviewed()
        assert reason in page._comparison_status.set_label.call_args.args[0]
        cast(MagicMock, recovery.commit_recovery).assert_not_called()
        cast(MagicMock, restoration.run_prepare).assert_not_called()
        cast(MagicMock, restoration.commit_restore).assert_not_called()

    @pytest.mark.parametrize("dirty,monitor", [(True, False), (False, True)])
    def test_public_permissions_block_stage_and_immediate_commit(
        self, page, window, dirty, monitor
    ):
        page._restore_permission = window.restore_permission
        page._begin_restore = window.begin_restore
        page._finish_restore = window.finish_restore
        window.has_dirty.return_value = dirty
        window._monitors_page.is_confirm_pending.return_value = monitor
        page.review_recovery(DRAFT.backup_name)
        cast(MagicMock, recovery.run_prepare).assert_not_called()
        reviewed(page)
        page.restore_reviewed()
        cast(MagicMock, recovery.commit_recovery).assert_not_called()
        assert page._draft is None and not window._restore_in_progress

    @pytest.mark.parametrize(
        "outcome,invalidate",
        [
            (
                recovery.RecoveryResult(
                    "recovered", Path(DRAFT.resolved_path), Path(DRAFT.preservation_path)
                ),
                True,
            ),
            (recovery.RecoveryFailure("preservation failed"), False),
            (recovery.RecoveryFailure("late failure", may_have_written=True), True),
            (RuntimeError("unexpected"), True),
        ],
    )
    def test_direct_non_daemon_writer_close_veto_one_use_and_editor_outcome(
        self, page, window, scheduled, monkeypatch, outcome, invalidate
    ):
        entered, release = threading.Event(), threading.Event()
        page._restore_permission = window.restore_permission
        page._begin_restore = window.begin_restore
        page._finish_restore = window.finish_restore
        child = MagicMock(side_effect=AssertionError("Writer must not be a child process"))
        monkeypatch.setattr("hyprmod.core.health.run_bounded", child)

        def write(draft, *, cancel_event):
            assert draft is DRAFT and cancel_event is page._cancel_event
            assert not cancel_event.is_set()
            assert not threading.current_thread().daemon
            assert threading.current_thread() is not threading.main_thread()
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Test worker not released")
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        writer = MagicMock(side_effect=write)
        monkeypatch.setattr(recovery, "commit_recovery", writer)
        reviewed(page)
        page._loading = True
        try:
            page.restore_reviewed()
            assert entered.wait(3)
            assert not window.editor_edit_allowed()
            assert page._on_close_request() is True
            page.close()
            page.restore_reviewed()
            page.refresh()
            assert not page._closed and not page._cancel_event.is_set()
        finally:
            release.set()
        finish(scheduled)
        assert window._editor_invalidated is invalidate
        assert window.editor_edit_allowed() is (not invalidate)
        assert not page.restore_writing and not page._loading and page._draft is None
        page.restore_reviewed()
        writer.assert_called_once()
        child.assert_not_called()
        window.app_state.mark_saved.assert_not_called()
        cast(MagicMock, restoration.commit_restore).assert_not_called()
        message = page._comparison_status.set_label.call_args.args[0]
        assert "fresh recovery review" in message
        if isinstance(outcome, recovery.RecoveryResult):
            assert DRAFT.preservation_path in message and "Restart Attune" in message
        elif invalidate:
            assert "may have changed" in message and "No output replacement" not in message
        else:
            assert "No output replacement" in message and "preserved copy" in message

    @pytest.mark.parametrize("cancel", [False, True])
    def test_late_preparation_cannot_reopen_after_cancel_or_close(
        self, page, scheduled, monkeypatch, cancel
    ):
        monkeypatch.setattr(recovery, "run_prepare", MagicMock(return_value=DRAFT))
        shown = MagicMock()
        monkeypatch.setattr(page, "_show_restore_review", shown)
        page.review_recovery(DRAFT.backup_name)
        if cancel:
            page.cancel_restoration()
        else:
            page.close()
        finish(scheduled)
        shown.assert_not_called()
        assert page._draft is None

    def test_wrong_draft_type_cannot_turn_restoration_into_recovery(
        self, page, scheduled, monkeypatch
    ):
        monkeypatch.setattr(restoration, "run_prepare", MagicMock(return_value=DRAFT))
        page.review_restoration(DRAFT.backup_name)
        finish(scheduled)
        assert page._draft is None and not page._loading
        assert "wrong draft type" in page._comparison_status.set_label.call_args.args[0]

    @pytest.mark.parametrize("state", ["invalid", "unavailable", "stale", "unknown", "closed"])
    def test_unavailable_selection_is_inert(self, page, state):
        if state in ("invalid", "unavailable"):
            page._listing = replace(
                page._listing,
                backups=(replace(page._listing.backups[0], status=state),),
            )
        elif state == "stale":
            page._stale = True
        elif state == "closed":
            page.close()
        page.review_recovery("unknown" if state == "unknown" else DRAFT.backup_name)
        cast(MagicMock, recovery.run_prepare).assert_not_called()

    @pytest.mark.parametrize("failure", ["begin", "thread"])
    def test_prewrite_failure_unlocks_without_invalidating(self, page, monkeypatch, failure):
        reviewed(page)
        if failure == "begin":
            page._begin_restore.side_effect = RuntimeError("begin failed")
        else:
            monkeypatch.setattr(
                page_module.threading, "Thread", MagicMock(side_effect=RuntimeError("no worker"))
            )
        page.restore_reviewed()
        page._finish_restore.assert_called_once_with(False)
        assert page._draft is None and not page.restore_writing
        cast(MagicMock, recovery.commit_recovery).assert_not_called()

    def test_failed_attempt_needs_fresh_prepare_and_ignores_duplicate_completion(
        self, page, scheduled, monkeypatch
    ):
        writer = MagicMock(side_effect=recovery.RecoveryFailure("preservation failed"))
        monkeypatch.setattr(recovery, "commit_recovery", writer)
        reviewed(page)
        page.restore_reviewed()
        callback, *args = scheduled.get(timeout=3)
        callback(*args)
        page.restore_reviewed()
        writer.assert_called_once()
        prepare = MagicMock(return_value=DRAFT)
        monkeypatch.setattr(recovery, "run_prepare", prepare)
        monkeypatch.setattr(page, "_show_restore_review", lambda draft: reviewed(page))
        page.review_recovery(DRAFT.backup_name)
        finish(scheduled)
        callback(*args)
        assert page._draft is DRAFT and page._loading
        prepare.assert_called_once()
        page.restore_reviewed()
        finish(scheduled)
        assert writer.call_count == 2
