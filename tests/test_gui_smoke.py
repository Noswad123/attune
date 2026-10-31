"""Opt-in widget checks on an isolated display, with compositor IPC disabled."""

import base64
import os
import sys
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from gi.repository import Adw, Gio, GLib, Gtk
from hyprland_socket import HyprlandError

from hyprmod import main as main_module
from hyprmod.core import (
    backups,
    config,
    health,
    persistence,
    restoration,
    scoped_recovery,
    scoped_restore,
)
from hyprmod.core import recovery as recovery_module
from hyprmod.core.diagnostics import build_diagnostics_report
from hyprmod.core.focused_ui import PAGE_IDS
from hyprmod.main import HyprModApp
from hyprmod.ui.diff import ConfigDiffWidget
from hyprmod.window import HyprModWindow

pytestmark = pytest.mark.skipif(
    os.environ.get("ATTUNE_GUI_SMOKE") != "1",
    reason="set ATTUNE_GUI_SMOKE=1 with an isolated GTK display",
)


@pytest.fixture(autouse=True)
def startup_assessment(monkeypatch, isolated_user_paths):
    assessment = scoped_recovery.LayoutAssessment(
        config_root=os.environ["XDG_CONFIG_HOME"],
        state_root=os.environ["XDG_STATE_HOME"],
        mode="legacy-clear",
        registry_condition="absent",
        canonical_pair=(),
        registry_error=None,
        transactions=(),
        truncated=False,
        notes=(),
    )
    collector = MagicMock(return_value=assessment)
    monkeypatch.setattr(scoped_recovery, "run_assess", collector)
    for name in ("run_prepare_action", "commit_action"):
        monkeypatch.setattr(
            scoped_recovery,
            name,
            MagicMock(side_effect=AssertionError("Mock scoped recovery API explicitly")),
        )
    for name in ("run_list", "run_prepare", "commit_restore"):
        monkeypatch.setattr(
            scoped_restore,
            name,
            MagicMock(side_effect=AssertionError("Mock scoped restore API explicitly")),
        )
    return collector


@pytest.fixture(autouse=True)
def no_external_health_effects(monkeypatch):
    clipboard = MagicMock()
    monkeypatch.setattr(Adw.Dialog, "get_clipboard", lambda _dialog: clipboard)
    monkeypatch.setattr(Gio.AppInfo, "get_default_for_type_async", MagicMock())
    return clipboard


@pytest.fixture
def health_collector(monkeypatch):
    collector = MagicMock(return_value=health.HealthSnapshot("2026-10-26T12:00:00+00:00", ()))
    monkeypatch.setattr(health, "run_snapshot", collector)
    return collector


@pytest.fixture(autouse=True)
def backup_collectors(monkeypatch, tmp_path):
    for name in ("run_prepare", "commit_recovery"):
        monkeypatch.setattr(
            recovery_module,
            name,
            MagicMock(side_effect=AssertionError("Mock recovery API explicitly")),
        )
    monkeypatch.setattr(
        restoration,
        "run_prepare",
        MagicMock(side_effect=AssertionError("Set deterministic restoration preparation first")),
    )
    monkeypatch.setattr(
        restoration,
        "commit_restore",
        MagicMock(side_effect=AssertionError("Set deterministic restoration commit first")),
    )
    listing = MagicMock(
        return_value=backups.BackupListing(
            "2026-10-26T12:00:00+00:00",
            str(tmp_path / "absent-backups"),
            "available",
            (),
            ("Backup directory missing; nothing created",),
        )
    )
    comparison = MagicMock(side_effect=AssertionError("Set a deterministic comparison first"))
    monkeypatch.setattr(backups, "run_list", listing)
    monkeypatch.setattr(backups, "run_compare", comparison)
    return listing, comparison


@pytest.fixture
def app(monkeypatch, health_collector):
    def offline():
        raise HyprlandError("IPC disabled during widget smoke test")

    monkeypatch.setattr("hyprland_socket.get_version", offline)
    config.managed_path().parent.mkdir(parents=True, exist_ok=True)
    application = HyprModApp()
    application.set_application_id(f"io.github.jdawson.Attune.Test{uuid4().hex}")
    application.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    application.register(None)
    yield application
    for window in application.get_windows():
        window.destroy()
    application.quit()


def _render():
    context = GLib.MainContext.default()
    for _ in range(50):
        if not context.pending():
            break
        context.iteration(False)


def _wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        _render()
        time.sleep(0.005)
    assert predicate()


def _widgets(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _widgets(child)
        child = child.get_next_sibling()


class TestWidgetSmoke:
    @pytest.mark.parametrize(
        "route", ["legacy-clear", "scope-recovery-required", "blocked", "error"]
    )
    def test_async_startup_routes_after_responsive_checking_window(
        self, app, startup_assessment, monkeypatch, route
    ):
        entered = threading.Event()
        release = threading.Event()
        message = "R&D <literal>"
        assessment = replace(
            startup_assessment.return_value,
            mode="legacy-clear" if route == "error" else route,
            transactions=(
                (
                    scoped_recovery.TransactionRow(
                        "a" * 32, "verified", "prepared", False, "all-prior", ()
                    ),
                )
                if route == "scope-recovery-required"
                else ()
            ),
        )

        def assess(config_root, state_root, **kwargs):
            assert threading.current_thread() is not threading.main_thread()
            assert not threading.current_thread().daemon
            assert str(config_root) == assessment.config_root
            assert str(state_root) == assessment.state_root
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Test worker not released")
            if route == "error":
                raise ValueError(message)
            return assessment

        startup_assessment.side_effect = assess
        app._integration_shown = True
        monkeypatch.setattr(main_module, "has_cairo_support", lambda: True)
        if route != "legacy-clear":
            monkeypatch.setattr(
                "hyprmod.window.HyprlandState",
                MagicMock(side_effect=AssertionError("Blocked startup must not build editor")),
            )
        try:
            app.do_activate()
            assert entered.wait(3)
            checking = app._config_error_window
            assert checking is not None
            assert not isinstance(checking, main_module.RecoveryWindow)
            assert any(
                isinstance(w, Gtk.Label) and w.get_text() == "Checking Attune Layout"
                for w in _widgets(checking)
            )
            app.do_activate()
            assert app._config_error_window is checking
            ticked = []
            GLib.idle_add(lambda: ticked.append(True))
            _wait_for(lambda: bool(ticked))
            assert not any(isinstance(w, HyprModWindow) for w in app.get_windows())
            startup_assessment.assert_called_once_with(
                Path(assessment.config_root),
                Path(assessment.state_root),
                cancel_event=app._startup_cancel,
                timeout=15,
            )
        finally:
            release.set()
        _wait_for(lambda: app._startup_cancel is None)
        assert checking not in app.get_windows()
        if route == "legacy-clear":
            assert app._config_error_window is None
            assert any(isinstance(w, HyprModWindow) for w in app.get_windows())
        else:
            shell = app._config_error_window
            if not isinstance(shell, main_module.RecoveryWindow):
                pytest.fail("Startup did not route to the recovery shell")
            labels = [w for w in _widgets(shell) if isinstance(w, Gtk.Label)]
            assert any(w.get_text() == "Attune Recovery" for w in labels)
            if route == "error":
                description = next(w for w in labels if "Read-only shell." in w.get_label())
                expected = (
                    f"{message}\n\nRead-only shell. Recovery requires a separate review "
                    "and explicit commit. Nothing is activated or migrated automatically."
                )
                assert description.get_text() == expected
                assert description.get_label() == GLib.markup_escape_text(expected)
            assert not any(isinstance(w, HyprModWindow) for w in app.get_windows())
        assert not config.managed_path().exists()
        assert not Path(assessment.state_root).exists()

    def test_toast_literal_text_and_unchanged_copy_payload(self, app, monkeypatch):
        window = HyprModWindow(application=app)
        clipboard = MagicMock()
        monkeypatch.setattr(window, "get_clipboard", lambda: clipboard)
        toasts = []
        monkeypatch.setattr(window, "add_toast", toasts.append)
        message = "R&D <literal>"
        window.show_toast(message, copy=True)
        toast = toasts[0]
        assert toast.get_title() == message
        clipboard.set.assert_not_called()
        toast.emit("button-clicked")
        clipboard.set.assert_called_once_with(message)
        assert not toast.get_use_markup()

    @pytest.mark.parametrize("recover_output", [False, True])
    @pytest.mark.parametrize("recovery", [False, True])
    @pytest.mark.parametrize("outcome", ["cancel", "restored", "unchanged", "uncertain"])
    def test_restoration_review_and_protected_worker(
        self, app, backup_collectors, monkeypatch, recovery, outcome, recover_output
    ):
        if recover_output and outcome == "unchanged":
            pytest.skip("Recovery always replaces output")
        listing, _ = backup_collectors
        name = "a" * 64 + ".lua"
        listing.return_value = replace(
            listing.return_value, backups=(backups.BackupInfo(name, "valid", "verified"),)
        )
        draft = restoration.RestoreDraft(
            str(config.managed_path()),
            "/temporary/target",
            "/temporary/backups",
            name,
            "old\n",
            "new\n",
            "b" * 64,
            "a" * 64,
            "--- current/attune.lua\n+++ backup\n-old\n+<new>&\n",
            1,
            1,
            "2026-10-27T12:00:00+00:00",
        )
        if recover_output:
            draft = recovery_module.RecoveryDraft(
                **asdict(draft),
                current_status="foreign",
                preservation_path="/temporary/private/original.bin",
                preservation_root="/temporary/private",
            )
        prepare = MagicMock(return_value=draft)
        operation = recovery_module if recover_output else restoration
        monkeypatch.setattr(operation, "run_prepare", prepare)
        entered = threading.Event()
        release = threading.Event()

        def commit(reviewed, **kwargs):
            assert reviewed is draft
            assert threading.current_thread() is not threading.main_thread()
            assert not threading.current_thread().daemon
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Test worker not released")
            if outcome == "uncertain":
                if recover_output:
                    raise recovery_module.RecoveryFailure("late failure", may_have_written=True)
                raise restoration.RestoreFailure("late failure", may_have_written=True)
            if recover_output:
                if not isinstance(draft, recovery_module.RecoveryDraft):
                    pytest.fail("Expected recovery draft")
                return recovery_module.RecoveryResult(
                    "recovered", config.managed_path(), Path(draft.preservation_path)
                )
            return restoration.RestoreResult(
                "unchanged" if outcome == "unchanged" else "restored",
                config.managed_path(),
                None if outcome == "unchanged" else config.managed_path().parent / "rollback.lua",
            )

        writer = MagicMock(side_effect=commit)
        monkeypatch.setattr(
            operation, "commit_recovery" if recover_output else "commit_restore", writer
        )
        if recovery:
            config.managed_path().write_text("foreign output\n")
            app.do_activate()
            _wait_for(lambda: isinstance(app._config_error_window, main_module.RecoveryWindow))
            window = app._config_error_window
            assert window is not None
            button = next(
                w
                for w in _widgets(window.get_content())
                if isinstance(w, Gtk.Button) and w.get_label() == "Legacy Backups (v1)"
            )
            button.emit("clicked")
            page = app._recovery_backups
        else:
            window = HyprModWindow(application=app)
            window.present()
            window.show_page("backups")
            page = window._backups_page
        assert page is not None
        _wait_for(lambda: not page._loading)
        if recover_output:
            page.review_recovery(name)
        else:
            page.review_restoration(name)
        _wait_for(lambda: page._review is not None)
        review = page._review
        assert review is not None
        diff = next(w for w in _widgets(review.get_child()) if isinstance(w, Gtk.TextView))
        buffer = diff.get_buffer()
        assert buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), True
        ) == draft.diff.rstrip("\n")
        writer.assert_not_called()
        cancel = next(
            w
            for w in _widgets(review.get_child())
            if isinstance(w, Gtk.Button) and w.get_label() == "Cancel"
        )
        if outcome == "cancel":
            cancel.emit("clicked")
            assert page._draft is None
            page.restore_reviewed()
            writer.assert_not_called()
            return
        restore = next(
            w
            for w in _widgets(review.get_child())
            if isinstance(w, Gtk.Button)
            and w.get_label()
            == (
                "Preserve and Recover Reviewed Output"
                if recover_output
                else "Restore Reviewed Output"
            )
        )
        if recover_output:
            assert not restore.get_sensitive()
            page.restore_reviewed()
            writer.assert_not_called()
            ack = next(w for w in _widgets(review.get_child()) if isinstance(w, Gtk.CheckButton))
            ack.set_active(True)
            assert restore.get_sensitive()
        try:
            restore.emit("clicked")
            assert entered.wait(3)
            assert page.restore_writing
            window.close()
            _render()
            assert window in app.get_windows() and not page._closed
            if recovery:
                app.do_activate()
                assert app._config_error_window is window
            else:
                assert not window.editor_edit_allowed()
                pending = window._page_stack.get_child_by_name("pending")
                health_view = window._page_stack.get_child_by_name("health")
                if pending is None or health_view is None:
                    pytest.fail("Missing editor or health page")
                assert not pending.get_sensitive()
                assert health_view.get_sensitive()
        finally:
            release.set()
        _wait_for(lambda: not page.restore_writing)
        assert page._draft is None
        page.restore_reviewed()
        writer.assert_called_once()
        if not recovery:
            assert window._editor_invalidated is (outcome != "unchanged")
            if outcome != "unchanged":
                window.save()
                window._on_undo()
                window._on_option_changed("decoration:rounding", 12)
                assert not window.has_dirty()
        assert not (config.managed_path().parent / "rollback.lua").exists()
        if recovery:
            assert config.managed_path().read_text() == "foreign output\n"
        else:
            assert not config.managed_path().exists()

    @pytest.mark.parametrize("recovery", [False, True])
    def test_backups_literal_comparison_and_reused_navigation(
        self, app, backup_collectors, monkeypatch, recovery
    ):
        listing, comparison = backup_collectors
        stamp = "2026-10-26T12:00:00+00:00"
        info = backups.BackupInfo(
            "a" * 64 + ".lua",
            "valid",
            "Canonical <literal>&",
            100,
            0,
            "a" * 64,
            backups.BackupSummary(1, 2, 3, 4),
        )
        listing.return_value = backups.BackupListing(
            stamp,
            "/test/<backups>&",
            "partial",
            (info, backups.BackupInfo("b" * 64 + ".lua", "invalid", "<bad hash>&")),
            ("<bounded note>&",),
        )
        comparison.side_effect = None
        comparison.return_value = backups.BackupComparison(
            stamp,
            info,
            backups.CurrentOutput("/lexical/<output>&", "/resolved/output", "foreign", "raw only"),
            "compared",
            "--- backup\n+++ current\n-old\n+<literal>& https://example.invalid\n",
            1,
            1,
            False,
            ("<comparison note>&",),
        )
        text = 'os.execute("must never execute")\n'
        live_state = MagicMock(side_effect=AssertionError("No editor for foreign output"))
        if recovery:
            config.managed_path().write_text(text)
            monkeypatch.setattr("hyprmod.window.HyprlandState", live_state)
            main_module.HyprModApp.do_activate(app)
            _wait_for(lambda: isinstance(app._config_error_window, main_module.RecoveryWindow))
            window = app._config_error_window
            assert window is not None
            stack = window.get_content()
            assert isinstance(stack, Gtk.Stack)
            button = next(
                w
                for w in _widgets(stack.get_visible_child())
                if isinstance(w, Gtk.Button) and w.get_label() == "Legacy Backups (v1)"
            )
            listing.assert_not_called()
            button.emit("clicked")
        else:
            window = HyprModWindow(application=app)
            window.present()
            listing.assert_not_called()
            window.show_page("backups")
            stack = window._page_stack
            assert window._backups_page not in window.section_pages
            assert "backups" in window._sidebar._rows_by_id
        view = stack.get_child_by_name("backups")
        assert view is not None
        _wait_for(
            lambda: any(
                isinstance(w, Gtk.Button) and w.get_label() == "Compare" for w in _widgets(view)
            )
        )
        rows = [w for w in _widgets(view) if isinstance(w, Adw.ActionRow)]
        assert len(rows) == 2
        assert rows[0].get_title() == info.name
        assert all(not row.get_use_markup() for row in rows)
        assert "Canonical <literal>&" in (rows[0].get_subtitle() or "")
        assert "<bad hash>&" in (rows[1].get_subtitle() or "")
        compares = [
            w for w in _widgets(view) if isinstance(w, Gtk.Button) and w.get_label() == "Compare"
        ]
        assert len(compares) == 1
        assert (
            sum(
                isinstance(w, Gtk.Button) and w.get_label() == "Review Recovery"
                for w in _widgets(view)
            )
            == 1
        )
        compares[0].emit("clicked")
        diff_view = next(w for w in _widgets(view) if isinstance(w, Gtk.TextView))
        buffer = diff_view.get_buffer()
        _wait_for(lambda: buffer.get_char_count() > 0)
        assert not diff_view.get_editable()
        assert buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True) == (
            comparison.return_value.diff.rstrip("\n")
        )
        tag = buffer.get_tag_table().lookup("diff-added")
        if tag is None:
            pytest.fail("Missing diff-added tag")
        assert buffer.get_iter_at_line(3)[1].has_tag(tag)
        labels = [w for w in _widgets(view) if isinstance(w, Gtk.Label)]
        assert any("Current lexical path: /lexical/<output>&" in w.get_text() for w in labels)
        assert any("<comparison note>&" in w.get_text() for w in labels)
        assert any(w.get_text() == "BACKUP -> CURRENT" for w in labels)
        assert all(not w.get_use_markup() for w in labels if "<" in w.get_text())
        forbidden = {"Restore", "Delete", "Activate", "Open Output", "Save", "Copy", "Export"}
        assert not any(
            isinstance(w, Gtk.Button) and w.get_label() in forbidden for w in _widgets(view)
        )
        if recovery:
            next(
                w for w in _widgets(view) if isinstance(w, Gtk.Button) and w.get_label() == "Back"
            ).emit("clicked")
            assert stack.get_visible_child_name() == "recovery"
            next(
                w
                for w in _widgets(stack.get_visible_child())
                if isinstance(w, Gtk.Button) and w.get_label() == "Legacy Backups (v1)"
            ).emit("clicked")
            assert stack.get_child_by_name("backups") is view
            live_state.assert_not_called()
            assert config.managed_path().read_text() == text
            with pytest.raises(ValueError):
                persistence.read_document(text)
        else:
            window.show_page("general")
            window.show_page("backups")
            assert not window.has_dirty()
            assert not config.managed_path().exists()
        listing.assert_called_once()
        comparison.assert_called_once()
        refresh = next(
            w for w in _widgets(view) if isinstance(w, Gtk.Button) and w.get_label() == "Refresh"
        )
        listing.side_effect = TimeoutError("<refresh error>&")
        refresh.emit("clicked")
        assert buffer.get_char_count() == 0
        _wait_for(refresh.get_sensitive)
        assert not compares[0].is_sensitive()
        assert any("Stale rows retained" in w.get_text() for w in labels)

    @pytest.mark.parametrize(
        "present,action", [(False, "destroy"), (True, "destroy"), (True, "close")]
    )
    def test_window_teardown_detaches_pending_backups(self, app, monkeypatch, present, action):
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def collect(path, **kwargs):
            entered.set()
            try:
                if not release.wait(3):
                    raise TimeoutError("Test worker not released")
                assert kwargs["cancel_event"].is_set()
                return backups.BackupListing(
                    "2026-10-26T12:00:00+00:00", "/test", "available", (), ()
                )
            finally:
                finished.set()

        monkeypatch.setattr(backups, "run_list", collect)
        window = HyprModWindow(application=app)
        if present:
            window.present()
            _render()
        page = window._backups_page
        assert page is not None
        try:
            window.show_page("backups")
            assert entered.wait(3)
            ticked = []
            GLib.idle_add(lambda: ticked.append(True))
            _wait_for(lambda: bool(ticked))
            getattr(window, action)()
            assert page._closed and page._cancel_event.is_set()
            label = page._status.get_label()
        finally:
            release.set()
        assert finished.wait(3)
        _render()
        assert page._listing is None
        assert page._status.get_label() == label

    def test_diff_precomputed_empty_and_existing_editor_behavior(self, app):
        diff = ConfigDiffWidget()
        diff.set_precomputed_diff("", added_lines=0, removed_lines=0, title="BACKUP -> CURRENT")
        assert diff._stack.get_visible_child_name() == "empty"
        assert diff._empty_label.get_label() == "No textual differences"
        diff.set_texts("old\n", "new\n", title="Review")
        assert diff._stack.get_visible_child_name() == "diff"
        assert diff._added_label.get_label() == "+1"
        assert diff._removed_label.get_label() == "−1"
        diff.set_texts("same", "same")
        assert diff._stack.get_visible_child_name() == "empty"
        assert diff._empty_label.get_label() == "Saved config is up to date"

    @pytest.mark.parametrize("recovery", [False, True])
    def test_health_preview_cancel_and_frozen_copy_in_both_windows(
        self, app, health_collector, monkeypatch, no_external_health_effects, recovery
    ):
        snapshot = health.HealthSnapshot(
            "2026-10-26T12:00:00+00:00",
            (health.HealthCheck("output", "Attune Output", "failed", "<literal>& secret"),),
        )
        health_collector.return_value = snapshot
        if recovery:
            config.managed_path().write_text("foreign Lua; must not execute")
            main_module.HyprModApp.do_activate(app)
            _wait_for(lambda: isinstance(app._config_error_window, main_module.RecoveryWindow))
            window = app._config_error_window
            assert isinstance(window, Adw.ApplicationWindow)
            next(
                widget
                for widget in _widgets(window)
                if isinstance(widget, Gtk.Button) and widget.get_label() == "Open Health"
            ).emit("clicked")
        else:
            window = HyprModWindow(application=app)
            window.present()
            window.show_page("health")
        preview = next(
            widget
            for widget in _widgets(window)
            if isinstance(widget, Gtk.Button) and widget.get_label() == "Preview Report"
        )
        _wait_for(preview.get_sensitive)
        rows = [widget for widget in _widgets(window) if isinstance(widget, Adw.ActionRow)]
        assert any(row.get_subtitle() == "<literal>& secret" for row in rows)
        preview.emit("clicked")
        dialog = window.get_visible_dialog()
        assert dialog is not None
        text = next(
            widget
            for widget in _widgets(dialog)
            if isinstance(widget, Gtk.Label) and widget.get_text().startswith("Attune Diagnostics")
        )
        assert not text.get_selectable()
        assert not text.get_use_markup()
        report = text.get_text()
        assert report == build_diagnostics_report(snapshot)
        assert "secret" not in report
        no_external_health_effects.set.assert_not_called()
        next(
            widget
            for widget in _widgets(dialog)
            if isinstance(widget, Gtk.Button) and widget.get_label() == "Cancel"
        ).emit("clicked")
        _wait_for(lambda: window.get_visible_dialog() is None)
        no_external_health_effects.set.assert_not_called()

        refresh = next(
            widget
            for widget in _widgets(window)
            if isinstance(widget, Gtk.Button) and widget.get_label() == "Refresh"
        )
        health_collector.side_effect = TimeoutError("refresh failure")
        refresh.emit("clicked")
        assert not preview.get_sensitive()
        _wait_for(preview.get_sensitive)
        preview.emit("clicked")
        dialog = window.get_visible_dialog()
        assert dialog is not None
        text = next(
            widget
            for widget in _widgets(dialog)
            if isinstance(widget, Gtk.Label) and widget.get_text().startswith("Attune Diagnostics")
        )
        report = text.get_text()
        assert report == build_diagnostics_report(snapshot, stale=True)
        assert "STALE - 2026-10-26T12:00:00+00:00" in report
        # A completion behind the dialog must not change the already reviewed export.
        health_collector.side_effect = None
        health_collector.return_value = health.HealthSnapshot(
            "2026-10-27T12:00:00+00:00", snapshot.checks
        )
        refresh.emit("clicked")
        _wait_for(preview.get_sensitive)
        assert text.get_text() == report
        no_external_health_effects.set.assert_not_called()
        next(
            widget
            for widget in _widgets(dialog)
            if isinstance(widget, Gtk.Button) and widget.get_label() == "Copy Report"
        ).emit("clicked")
        no_external_health_effects.set.assert_called_once_with(report)
        if isinstance(window, HyprModWindow):
            assert not window.has_dirty()
            assert not config.managed_path().exists()
        else:
            assert config.managed_path().read_text() == "foreign Lua; must not execute"

    def test_health_open_missing_output_and_safe_folder_dispatch(self, app, monkeypatch):
        window = HyprModWindow(application=app)
        window.present()
        window.show_page("health")
        page = window._health_page
        assert page is not None
        association = MagicMock()
        monkeypatch.setattr(Gio.AppInfo, "get_default_for_type_async", association)
        page.open_output()
        _wait_for(page._local_error.get_visible)
        assert "Cannot access" in page._local_error.get_label()
        association.assert_not_called()
        assert not config.managed_path().exists()
        page.open_output(folder=True)
        _wait_for(lambda: association.call_count == 1)
        args = association.call_args.args
        assert args[:2] == ("inode/directory", False)
        launcher = MagicMock()
        monkeypatch.setattr(Gio.AppInfo, "get_default_for_type_finish", lambda _result: launcher)
        args[3](None, MagicMock())
        launch = launcher.launch_uris_async.call_args.args
        assert launch[0] == [Gio.File.new_for_path(str(config.managed_path().parent)).get_uri()]
        launcher.launch_uris_finish.side_effect = GLib.Error("Failed file manager")
        launch[3](launcher, MagicMock())
        assert page._local_error.get_visible()
        assert "Could not open" in page._local_error.get_label()
        assert not window.has_dirty()
        assert not config.managed_path().exists()

    def test_health_editor_dispatch_escapes_native_uri_and_missing_folder_is_not_created(
        self, app, monkeypatch, tmp_path
    ):
        window = HyprModWindow(application=app)
        window.present()
        window.show_page("health")
        page = window._health_page
        assert page is not None
        output = tmp_path / "name with spaces # %.lua"
        sentinel = tmp_path / "never-execute"
        text = f'os.execute("touch {sentinel}")'
        output.write_text(text)
        page._output_path = output
        association = MagicMock()
        monkeypatch.setattr(Gio.AppInfo, "get_default_for_type_async", association)
        page.open_output()
        _wait_for(lambda: association.call_count == 1)
        args = association.call_args.args
        assert args[:2] == ("text/plain", False)
        editor = MagicMock()
        monkeypatch.setattr(Gio.AppInfo, "get_default_for_type_finish", lambda _result: editor)
        args[3](None, MagicMock())
        launch = editor.launch_uris_async.call_args.args
        assert launch[0] == [Gio.File.new_for_path(str(output)).get_uri()]
        assert "name%20with%20spaces%20%23%20%25.lua" in launch[0][0]
        assert output.read_text() == text
        assert not sentinel.exists()
        page._output_path = tmp_path / "missing folder" / "attune.lua"
        association.reset_mock()
        page.open_output(folder=True)
        _wait_for(page._local_error.get_visible)
        association.assert_not_called()
        assert not page._output_path.parent.exists()
        assert not window.has_dirty()

    def test_first_run_builds_every_supported_page_without_creating_output(
        self, app, health_collector
    ):
        window = HyprModWindow(application=app)
        health_collector.assert_not_called()
        assert not window.hypr.online
        assert window.hypr.document.lines == []
        window.present()
        for page in sorted(PAGE_IDS - {"search"}):
            window.show_page(page)
            _render()
            assert window._page_stack.get_visible_child_name() == page
        assert not config.managed_path().exists()
        assert window._health_page not in window.section_pages
        assert "health" in window._sidebar._rows_by_id
        assert not window.has_dirty()

    def test_offline_edit_review_save_and_reopen(self, app):
        window = HyprModWindow(application=app)
        window._on_option_changed("decoration:rounding", 17)
        window.save()
        _render()
        reviewed = window.review_snapshot()
        assert "rounding = 17" in reviewed.proposed_text
        window.save_reviewed(reviewed)
        output = config.managed_path()
        assert output.exists()
        assert persistence.read_document(output.read_text()).get("decoration:rounding") == "17"
        assert not window.has_dirty()
        window.destroy()
        reopened = HyprModWindow(application=app)
        assert reopened.saved_values["decoration:rounding"] == "17"
        assert reopened.hypr.document.lines == []
        assert not (output.parent / "hyprland.lua").exists()

    @pytest.mark.parametrize("recursive", [False, True])
    def test_foreign_output_uses_recovery_window(
        self, app, health_collector, monkeypatch, recursive
    ):
        sentinel = Path.home() / "must-not-execute"
        if recursive:
            depth = sys.getrecursionlimit() + 100
            record = base64.b64encode(("[" * depth + "0" + "]" * depth).encode()).decode()
            text = persistence.MARKER + persistence.RECORD + record + "\n"
        else:
            text = f'os.execute("touch {sentinel}")\n'
        config.managed_path().write_text(text)
        live_state = MagicMock(side_effect=AssertionError("Recovery must not construct live state"))
        monkeypatch.setattr("hyprmod.window.HyprlandState", live_state)
        main_module.HyprModApp.do_activate(app)
        _wait_for(lambda: isinstance(app._config_error_window, main_module.RecoveryWindow))
        recovery = app._config_error_window
        assert recovery is not None
        _render()
        health_collector.assert_not_called()
        button = next(
            button
            for button in _widgets(recovery)
            if isinstance(button, Gtk.Button) and button.get_label() == "Open Health"
        )
        button.emit("clicked")
        _wait_for(lambda: health_collector.call_count == 1)
        stack = recovery.get_content()
        assert isinstance(stack, Gtk.Stack)
        health_view = stack.get_child_by_name("health")
        assert health_view is not None
        refresh = next(
            widget
            for widget in _widgets(health_view)
            if isinstance(widget, Gtk.Button) and widget.get_label() == "Refresh"
        )
        _wait_for(refresh.get_sensitive)
        refresh.emit("clicked")
        _wait_for(lambda: health_collector.call_count == 2 and refresh.get_sensitive())
        back = next(
            widget
            for widget in _widgets(health_view)
            if isinstance(widget, Gtk.Button) and widget.get_label() == "Back"
        )
        back.emit("clicked")
        assert stack.get_visible_child_name() == "recovery"
        button.emit("clicked")
        assert stack.get_child_by_name("health") is health_view
        assert stack.get_visible_child_name() == "health"
        assert health_collector.call_count == 2
        back.emit("clicked")
        retry = next(
            widget
            for widget in _widgets(stack.get_visible_child())
            if isinstance(widget, Gtk.Button) and widget.get_label() == "Retry Startup Check"
        )
        retry.emit("clicked")
        assert app._config_error_window is not None
        assert app._config_error_window is not recovery
        assert not isinstance(app._config_error_window, main_module.RecoveryWindow)
        _wait_for(lambda: isinstance(app._config_error_window, main_module.RecoveryWindow))
        assert health_collector.call_count == 2
        live_state.assert_not_called()
        assert not sentinel.exists()
        assert not any(isinstance(window, HyprModWindow) for window in app.get_windows())
        assert config.managed_path().read_text() == text

    def test_health_worker_keeps_main_loop_responsive_and_renders(self, app, monkeypatch):
        entered = threading.Event()
        release = threading.Event()
        worker_threads = []
        snapshot = health.HealthSnapshot(
            "2026-10-26T12:00:00+00:00",
            tuple(
                health.HealthCheck(status, f"Check {status}", status, "Summary", ("<detail>&",))
                for status in ("available", "unavailable", "unknown", "failed")
            ),
        )

        def collect(path, **kwargs):
            worker_threads.append(threading.current_thread())
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Test worker not released")
            return snapshot

        collector = MagicMock(side_effect=collect)
        monkeypatch.setattr(health, "run_snapshot", collector)
        window = HyprModWindow(application=app)
        window.present()
        page = window._health_page
        assert page is not None
        try:
            window.show_page("health")
            assert entered.wait(3)
            page.refresh()
            window.show_page("general")
            window.show_page("health")
            ticked = []
            GLib.idle_add(lambda: ticked.append(True))
            _wait_for(lambda: bool(ticked))
            assert not page._refresh_button.get_sensitive()
            assert "Loading" in page._status.get_label()
            collector.assert_called_once_with(
                config.managed_path(), cancel_event=page._cancel_event
            )
            assert worker_threads[0] is not threading.current_thread()
        finally:
            release.set()
        _wait_for(lambda: page._snapshot is snapshot)
        group = page._checks.get_first_child()
        for check in snapshot.checks:
            assert isinstance(group, Adw.PreferencesGroup)
            assert group.get_title() == check.title
            group = group.get_next_sibling()
        assert page._refresh_button.get_sensitive()
        rows = [widget for widget in _widgets(page._checks) if isinstance(widget, Adw.ActionRow)]
        assert [row.get_title() for row in rows] == [
            check.status.capitalize() for check in snapshot.checks
        ]
        assert all(row.get_subtitle() == "Summary\n<detail>&" for row in rows)
        window.show_page("general")
        window.show_page("health")
        collector.assert_called_once()
        monkeypatch.setattr(
            health, "run_snapshot", MagicMock(side_effect=TimeoutError("timed out"))
        )
        page._refresh_button.emit("clicked")
        _wait_for(lambda: not page._loading)
        assert page._snapshot is snapshot
        assert "Stale observation retained" in page._status.get_label()
        assert "timed out" in page._status.get_label()
        assert page._refresh_button.get_sensitive()

    @pytest.mark.parametrize(
        "present,action", [(False, "destroy"), (True, "destroy"), (True, "close")]
    )
    def test_window_teardown_detaches_pending_health(self, app, monkeypatch, present, action):
        release = threading.Event()
        finished = threading.Event()
        cancellation_events = []

        def collect(path, **kwargs):
            try:
                cancellation_events.append(kwargs["cancel_event"])
                release.wait(3)
                return health.HealthSnapshot("2026-10-26T12:00:00+00:00", ())
            finally:
                finished.set()

        monkeypatch.setattr(health, "run_snapshot", collect)
        window = HyprModWindow(application=app)
        if present:
            window.present()
            _render()
        page = window._health_page
        assert page is not None
        window.show_page("health")
        getattr(window, action)()
        try:
            assert page._closed
            assert page._cancel_event.is_set()
            label = page._status.get_label()
        finally:
            release.set()
        assert finished.wait(3)
        assert cancellation_events == [page._cancel_event]
        _render()
        assert page._snapshot is None
        assert page._status.get_label() == label
