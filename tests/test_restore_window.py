"""Restoration lifecycle with mocked writers, without GTK or compositor effects."""

import threading
from dataclasses import FrozenInstanceError
from pathlib import Path
from queue import Queue
from types import MethodType
from typing import cast
from unittest.mock import MagicMock

import pytest

from hyprmod import window as window_module
from hyprmod.core import backups, recovery, restoration
from hyprmod.pages import backups as page_module
from hyprmod.pages.backups import BackupsPage
from hyprmod.window import HyprModWindow

DRAFT = restoration.RestoreDraft(
    "/output/attune.lua",
    "/target/attune.lua",
    "/backups",
    "a" * 64 + ".lua",
    "old\n",
    "new\n",
    "b" * 64,
    "a" * 64,
    "--- current/attune.lua\n+++ backup\n-old\n+new\n",
    1,
    1,
    "2026-10-27T12:00:00+00:00",
)


@pytest.fixture(autouse=True)
def no_unmocked_operations(monkeypatch):
    for module, names in (
        (restoration, ("run_prepare", "commit_restore")),
        (recovery, ("run_prepare", "commit_recovery")),
    ):
        for name in names:
            monkeypatch.setattr(
                module, name, MagicMock(side_effect=AssertionError("Mock this API explicitly"))
            )


@pytest.fixture
def scheduled(monkeypatch):
    queue = Queue()
    monkeypatch.setattr(page_module.GLib, "idle_add", lambda *args: queue.put(args))
    return queue


def finish(queue):
    callback, *args = queue.get(timeout=3)
    callback(*args)


@pytest.fixture
def page(tmp_path):
    page = BackupsPage(
        tmp_path / "attune.lua",
        restore_permission=MagicMock(),
        begin_restore=MagicMock(),
        finish_restore=MagicMock(),
    )
    for name in ("_refresh_button", "_status", "_rows", "_comparison_status", "_diff"):
        setattr(page, name, MagicMock())
    page._listing = backups.BackupListing(
        DRAFT.observed_at,
        "/backups",
        "available",
        (backups.BackupInfo(DRAFT.backup_name, "valid", "verified"),),
        (),
    )
    return page


@pytest.fixture
def window():
    win = MagicMock()
    win._restore_in_progress = False
    win._restore_owner = None
    win._editor_invalidated = False
    win.has_dirty.return_value = False
    win._monitors_page.is_confirm_pending.return_value = False
    for name in (
        "editor_edit_allowed",
        "restore_permission",
        "begin_restore",
        "finish_restore",
        "scope_restore_permission",
        "begin_scope_restore",
        "finish_scope_restore",
        "_lock_legacy_editor",
    ):
        setattr(win, name, MethodType(getattr(HyprModWindow, name), win))
    return win


class TestWindowWriterExceptions:
    @pytest.mark.parametrize("owner", ["scope", "backups", None])
    @pytest.mark.parametrize("failure", ["cache", "sensitivity", "title", "revealed", "toast"])
    def test_finish_retires_owner_and_invalidates_before_fallible_work(
        self, window, monkeypatch, owner, failure
    ):
        cache = MagicMock()
        monkeypatch.setattr(window_module, "config", MagicMock(invalidate_cache=cache))
        window._restore_owner = owner
        window._restore_in_progress = owner is not None
        notification = {
            "cache": cache,
            "sensitivity": window._set_editor_sensitive,
            "title": window._hyprland_banner.set_title,
            "revealed": window._hyprland_banner.set_revealed,
            "toast": window.show_toast,
        }[failure]

        def fail(*args):
            assert window._restore_owner is None
            assert not window._restore_in_progress
            assert window._editor_invalidated
            raise RuntimeError("notification failed")

        notification.side_effect = fail
        finish = window.finish_scope_restore if owner == "scope" else window.finish_restore
        with pytest.raises(RuntimeError, match="notification failed"):
            finish(True)
        assert window._restore_owner is None
        assert not window._restore_in_progress
        assert window._editor_invalidated

    @pytest.mark.parametrize("owner", ["scope", "backups"])
    def test_refused_finish_does_not_touch_owner_or_cache(self, window, monkeypatch, owner):
        cache = MagicMock(side_effect=RuntimeError("cache failed"))
        monkeypatch.setattr(window_module, "config", MagicMock(invalidate_cache=cache))
        window._restore_owner = owner
        window._restore_in_progress = True
        finish = window.finish_restore if owner == "scope" else window.finish_scope_restore
        finish(True)
        assert window._restore_owner == owner and window._restore_in_progress
        assert not window._editor_invalidated
        cache.assert_not_called()
        window._set_editor_sensitive.assert_not_called()

    @pytest.mark.parametrize(
        "owner,invalidated", [("backups", False), ("scope", False), ("scope", True)]
    )
    @pytest.mark.parametrize("rollback_fails", [False, True])
    def test_begin_sensitivity_error_rolls_back_ownership(
        self, window, owner, invalidated, rollback_fails
    ):
        window._editor_invalidated = invalidated
        window._set_editor_sensitive.side_effect = [
            RuntimeError("sensitivity failed"),
            RuntimeError("rollback failed") if rollback_fails else None,
        ]
        begin = window.begin_scope_restore if owner == "scope" else window.begin_restore
        with pytest.raises(RuntimeError):
            begin()
        assert window._restore_owner is None and not window._restore_in_progress
        assert window._editor_invalidated is invalidated
        assert window._set_editor_sensitive.call_args_list[-1].args == (not invalidated,)

    @pytest.mark.parametrize("owner", ["scope", "backups"])
    @pytest.mark.parametrize("notification_fails", [False, True])
    def test_finish_notification_cannot_release_reentrant_writer(
        self, window, owner, notification_fails
    ):
        window._restore_owner = owner
        window._restore_in_progress = True

        def notify(sensitive):
            if sensitive:
                window.begin_scope_restore()
                if notification_fails:
                    raise RuntimeError("notification failed")

        window._set_editor_sensitive.side_effect = notify
        finish = window.finish_scope_restore if owner == "scope" else window.finish_restore
        if notification_fails:
            with pytest.raises(RuntimeError, match="notification failed"):
                finish(False)
        else:
            finish(False)
        assert window._restore_owner == "scope" and window._restore_in_progress

    def test_legacy_lock_is_sticky_before_cache_error(self, window, monkeypatch):
        monkeypatch.setattr(
            window_module,
            "config",
            MagicMock(invalidate_cache=MagicMock(side_effect=RuntimeError("cache failed"))),
        )
        with pytest.raises(RuntimeError, match="cache failed"):
            window._lock_legacy_editor("Scoped evidence")
        assert window._editor_invalidated
        assert not window.editor_edit_allowed()
        window.finish_restore(False)
        assert window._editor_invalidated
        window._set_editor_sensitive.assert_called_once_with(False)


class TestRestoration:
    def test_dirty_introduced_after_preparation_refuses_consumed_review(
        self, page, window, scheduled, monkeypatch
    ):
        page._restore_permission = window.restore_permission
        page._begin_restore = window.begin_restore
        page._finish_restore = window.finish_restore
        monkeypatch.setattr(restoration, "run_prepare", MagicMock(return_value=DRAFT))
        writer = MagicMock()
        monkeypatch.setattr(restoration, "commit_restore", writer)

        def show(draft):
            page._draft = draft

        monkeypatch.setattr(page, "_show_restore_review", show)
        page.review_restoration(DRAFT.backup_name)
        finish(scheduled)
        window.has_dirty.return_value = True
        page.restore_reviewed()
        writer.assert_not_called()
        assert page._draft is None and not window._restore_in_progress

    @pytest.mark.parametrize(
        "reason",
        [
            "foreign current",
            "missing current",
            "invalid current",
            "source changed",
            "root changed",
            "cancelled",
        ],
    )
    def test_prepare_failure_has_no_review_or_write(self, page, scheduled, monkeypatch, reason):
        monkeypatch.setattr(restoration, "run_prepare", MagicMock(side_effect=ValueError(reason)))
        writer = MagicMock()
        monkeypatch.setattr(restoration, "commit_restore", writer)
        page.review_restoration(DRAFT.backup_name)
        finish(scheduled)
        assert page._draft is None and not page._loading
        page.restore_reviewed()
        writer.assert_not_called()
        message = page._comparison_status.set_label.call_args.args[0]
        assert reason in message and "No changes were made" in message
        cast(MagicMock, recovery.run_prepare).assert_not_called()
        cast(MagicMock, recovery.commit_recovery).assert_not_called()

    def test_close_during_preparation_cancels_and_ignores_late_draft(
        self, page, scheduled, monkeypatch
    ):
        monkeypatch.setattr(restoration, "run_prepare", MagicMock(return_value=DRAFT))
        shown = MagicMock()
        monkeypatch.setattr(page, "_show_restore_review", shown)
        page.review_restoration(DRAFT.backup_name)
        assert page._on_close_request() is False
        page.close()
        finish(scheduled)
        shown.assert_not_called()
        assert page._cancel_event.is_set() and page._draft is None

    def test_writer_start_failure_unlocks_without_invalidation(self, page, monkeypatch):
        page._draft = DRAFT
        monkeypatch.setattr(
            page_module.threading, "Thread", MagicMock(side_effect=RuntimeError("no worker"))
        )
        page.restore_reviewed()
        page._finish_restore.assert_called_once_with(False)
        assert not page.restore_writing
        assert "No output replacement" in page._comparison_status.set_label.call_args.args[0]

    def test_preparation_and_cancel_are_read_only(self, page, scheduled, monkeypatch):
        prepare = MagicMock(return_value=DRAFT)
        writer = MagicMock()
        monkeypatch.setattr(restoration, "run_prepare", prepare)
        monkeypatch.setattr(restoration, "commit_restore", writer)
        shown = []

        def show(draft):
            shown.append(draft)
            page._draft = draft

        monkeypatch.setattr(page, "_show_restore_review", show)
        page.review_restoration(DRAFT.backup_name)
        page.refresh()
        page.compare(DRAFT.backup_name)
        finish(scheduled)
        assert shown == [DRAFT] and page._loading
        prepare.assert_called_once_with(
            page._output_path, DRAFT.backup_name, cancel_event=page._cancel_event
        )
        with pytest.raises(FrozenInstanceError):
            setattr(DRAFT, "diff", "truncated")
        page.cancel_restoration()
        page.restore_reviewed()
        writer.assert_not_called()
        assert page._draft is None and not page._loading
        assert not page._output_path.exists()

    def test_review_renders_exact_precomputed_diff_and_identities(self, page, monkeypatch):
        dialog = MagicMock()
        content = MagicMock()
        diff = MagicMock()
        label = MagicMock()
        monkeypatch.setattr(page_module.Adw, "Dialog", MagicMock(return_value=dialog))
        monkeypatch.setattr(page_module.Adw, "HeaderBar", MagicMock())
        monkeypatch.setattr(
            page_module, "make_page_layout", lambda **kw: (MagicMock(), None, content, None)
        )
        monkeypatch.setattr(page_module.Gtk, "Label", label)
        monkeypatch.setattr(page_module.Gtk, "Button", MagicMock())
        monkeypatch.setattr(page_module, "ConfigDiffWidget", MagicMock(return_value=diff))
        page._show_restore_review(DRAFT)
        diff.set_precomputed_diff.assert_called_once_with(
            DRAFT.diff, added_lines=1, removed_lines=1, title="CURRENT -> BACKUP"
        )
        diff.set_texts.assert_not_called()
        text = label.call_args.kwargs["label"]
        for value in (
            DRAFT.observed_at,
            DRAFT.backup_name,
            DRAFT.previous_sha256,
            DRAFT.proposed_sha256,
            DRAFT.lexical_path,
            DRAFT.resolved_path,
            "backup of current output",
            "Hyprland may auto-reload watched files",
        ):
            assert value in text

    @pytest.mark.parametrize("dirty,monitor", [(True, False), (False, True)])
    def test_dirty_or_monitor_blocks_stage_and_commit(
        self, page, window, monkeypatch, dirty, monitor
    ):
        window.has_dirty.return_value = dirty
        window._monitors_page.is_confirm_pending.return_value = monitor
        page._restore_permission = window.restore_permission
        prepare = MagicMock()
        writer = MagicMock()
        monkeypatch.setattr(restoration, "run_prepare", prepare)
        monkeypatch.setattr(restoration, "commit_restore", writer)
        page.review_restoration(DRAFT.backup_name)
        page._draft = DRAFT  # Changes can also be introduced while a review is open.
        page.restore_reviewed()
        prepare.assert_not_called()
        writer.assert_not_called()
        assert page._draft is None
        assert "No changes were made" in page._comparison_status.set_label.call_args.args[0]

    @pytest.mark.parametrize(
        "outcome,invalidate",
        [
            (
                restoration.RestoreResult("restored", Path(DRAFT.resolved_path), Path("/rollback")),
                True,
            ),
            (restoration.RestoreResult("unchanged", Path(DRAFT.resolved_path), None), False),
            (restoration.RestoreFailure("source changed"), False),
            (restoration.RestoreFailure("current changed"), False),
            (restoration.RestoreFailure("root changed"), False),
            (restoration.RestoreFailure("late error", may_have_written=True), True),
            (RuntimeError("unexpected boundary failure"), True),
        ],
    )
    def test_commit_outcome_survives_close_and_consumes_review(
        self, page, scheduled, monkeypatch, outcome, invalidate
    ):
        entered = threading.Event()
        release = threading.Event()
        workers = []

        def writer(draft, *, cancel_event):
            assert draft is DRAFT and not cancel_event.is_set()
            workers.append(threading.current_thread())
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Test worker not released")
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        commit = MagicMock(side_effect=writer)
        monkeypatch.setattr(restoration, "commit_restore", commit)
        child = MagicMock(side_effect=AssertionError("Commit must not use a killable child"))
        monkeypatch.setattr("hyprmod.core.health.run_bounded", child)
        page._draft = DRAFT
        page._loading = True
        try:
            page.restore_reviewed()
            assert entered.wait(3)
            assert page.restore_writing
            assert page._on_close_request() is True
            page.close()
            page.refresh()
            page.restore_reviewed()
            assert not page._closed and not page._cancel_event.is_set()
            assert not workers[0].daemon and workers[0] is not threading.current_thread()
        finally:
            release.set()
        finish(scheduled)
        page._finish_restore.assert_called_once_with(invalidate)
        assert not page.restore_writing and not page._loading and page._draft is None
        page.restore_reviewed()
        commit.assert_called_once()
        child.assert_not_called()
        message = page._comparison_status.set_label.call_args.args[0]
        if isinstance(outcome, restoration.RestoreResult):
            assert ("/rollback" if invalidate else "No write or backup") in message
        elif invalidate:
            assert "may have changed; inspect/restart" in message
            assert "No output replacement" not in message
        else:
            assert "No output replacement" in message and "Restored:" not in message

    def test_local_begin_failure_never_enters_writer(self, page, monkeypatch):
        page._draft = DRAFT
        page._begin_restore.side_effect = RuntimeError("callback failed")
        writer = MagicMock()
        monkeypatch.setattr(restoration, "commit_restore", writer)
        page.restore_reviewed()
        writer.assert_not_called()
        page._finish_restore.assert_called_once_with(False)
        assert not page.restore_writing

    @pytest.mark.parametrize("invalidate", [False, True])
    def test_window_gate_does_not_mark_cached_values_saved(self, window, invalidate):
        window.begin_restore()
        assert not window.editor_edit_allowed()
        assert HyprModWindow._on_close_request(window)
        window.finish_restore(invalidate)
        assert window.editor_edit_allowed() is (not invalidate)
        assert window._editor_invalidated is invalidate
        window.app_state.mark_saved.assert_not_called()
        window.hypr.assert_not_called()
        window._perform_save.assert_not_called()

    @pytest.mark.parametrize(
        "method,args",
        [
            ("save", ()),
            ("save_reviewed", (MagicMock(),)),
            ("_on_option_changed", ("key", 1)),
            ("_on_paired_option_changed", ([("key", 1)],)),
            ("_on_option_reset", ("key", 0)),
            ("discard_option", ("key",)),
            ("_apply_undo_redo", (True,)),
            ("_apply_undo_redo", (False,)),
            ("_on_discard", ()),
            ("_do_discard", ()),
        ],
    )
    @pytest.mark.parametrize("writing", [False, True])
    def test_stale_or_committing_editor_handlers_stop_before_ipc(
        self, window, method, args, writing
    ):
        window._restore_in_progress = writing
        window._editor_invalidated = not writing
        getattr(HyprModWindow, method)(window, *args)
        assert window.app_state.mock_calls == []
        assert window.hypr.mock_calls == []
        assert window._undo.mock_calls == []
        window._perform_save.assert_not_called()
        window.review_snapshot.assert_not_called()

    def test_lifecycle_installs_own_close_veto(self, page):
        window = MagicMock()
        page.bind_lifecycle(window)
        callbacks = {call.args[0]: call.args[1] for call in window.connect.call_args_list}
        page.restore_writing = True
        assert callbacks["close-request"]() is True
        callbacks["destroy"]()
        assert not page._closed
