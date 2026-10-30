"""Opt-in Broadway recovery checks. Shared conftest isolates HOME and all XDG roots."""

import os
import threading
import time
from pathlib import Path
from types import MethodType
from typing import cast
from unittest.mock import MagicMock

import pytest
from gi.repository import Adw, GLib, Gtk
from hyprland_socket import HyprlandError

from hyprmod.core import config, scoped_recovery, scoped_review
from hyprmod.core.transaction_publication import PublicationResult
from hyprmod.pages.scope_recovery import ScopeRecoveryPage
from hyprmod.window import HyprModWindow
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


@pytest.fixture
def recovery_context(plan, monkeypatch):
    config_root = Path(plan.evidence.config_root)
    state_root = Path(plan.evidence.state_root)
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
