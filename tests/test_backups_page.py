"""Read-only backup page scheduling and rendering without a desktop."""

import os
import signal
import subprocess
import sys
import textwrap
import threading
from dataclasses import replace
from queue import Queue
from typing import cast
from unittest.mock import MagicMock

import pytest

from hyprmod.core import backups, recovery, restoration
from hyprmod.pages import backups as page_module
from hyprmod.pages.backups import BackupsPage
from hyprmod.ui.diff import ConfigDiffWidget

STAMP = "2026-10-26T12:00:00+00:00"
VALID = backups.BackupInfo(
    "a" * 64 + ".lua",
    "valid",
    "Canonical <literal>&",
    100,
    0,
    "a" * 64,
    backups.BackupSummary(1, 2, 3, 4),
)
LISTING = backups.BackupListing(STAMP, "/state/<backups>&", "available", (VALID,), ())
CURRENT = backups.CurrentOutput("/lexical/<output>&", "/resolved/output", "foreign", "raw only")
COMPARISON = backups.BackupComparison(
    STAMP,
    VALID,
    CURRENT,
    "compared",
    "--- backup\n+++ current\n-old\n+<new>&\n",
    1,
    1,
    False,
    ("<note>&",),
)


@pytest.fixture(autouse=True)
def no_writers(monkeypatch):
    for module, names in (
        (restoration, ("run_prepare", "commit_restore")),
        (recovery, ("run_prepare", "commit_recovery")),
    ):
        for name in names:
            monkeypatch.setattr(
                module, name, MagicMock(side_effect=AssertionError("Mock this API explicitly"))
            )


@pytest.fixture
def page(tmp_path, monkeypatch):
    page = BackupsPage(tmp_path / "attune.lua")
    for name in ("_refresh_button", "_status", "_rows", "_comparison_status", "_diff"):
        setattr(page, name, MagicMock())
    monkeypatch.setattr(page_module, "clear_children", MagicMock())
    monkeypatch.setattr(
        page_module.Adw, "PreferencesGroup", MagicMock(side_effect=lambda: MagicMock())
    )
    monkeypatch.setattr(
        page_module.Adw, "ActionRow", MagicMock(side_effect=lambda **kw: MagicMock())
    )
    monkeypatch.setattr(page_module.Gtk, "Button", MagicMock(side_effect=lambda **kw: MagicMock()))
    return page


@pytest.fixture
def scheduled(monkeypatch):
    callbacks = Queue()
    monkeypatch.setattr(page_module.GLib, "idle_add", lambda *args: callbacks.put(args))
    return callbacks


def finish(scheduled):
    callback, *args = scheduled.get(timeout=3)
    callback(*args)
    return callback, args


class TestBackupsPage:
    def test_constructor_is_lazy(self, tmp_path, monkeypatch):
        collector = MagicMock()
        monkeypatch.setattr(backups, "run_list", collector)
        BackupsPage(tmp_path / "absent" / "attune.lua")
        collector.assert_not_called()
        assert not (tmp_path / "absent").exists()

    def test_rows_metadata_notes_bounds_and_valid_callback(self, page, scheduled, monkeypatch):
        rows = (VALID,) + tuple(
            backups.BackupInfo(f"{i:064x}.lua", "invalid" if i % 2 else "unavailable", "<reason>&")
            for i in range(63)
        )
        listing = replace(LISTING, status="partial", backups=rows, notes=("<bounded note>&",))
        monkeypatch.setattr(backups, "run_list", lambda *a, **kw: listing)
        page.refresh()
        finish(scheduled)
        text = page._status.set_label.call_args.args[0]
        assert "Showing 64 candidates (maximum 64)" in text
        assert listing.directory in text and "<bounded note>&" in text and STAMP in text
        assert cast(MagicMock, page_module.Adw.ActionRow).call_count == 64
        assert cast(MagicMock, page_module.Gtk.Button).call_count == 3
        row = page._rows.append.call_args_list[0].args[0].add.call_args.args[0]
        row.set_use_markup.assert_called_with(False)
        metadata = row.set_subtitle.call_args.args[0]
        for value in (
            "<literal>&",
            "SHA-256: " + "a" * 64,
            "100 bytes",
            "1970-01-01",
            "not last save",
            "1 scalars, 2 monitors, 3 animations, 4 Beziers",
        ):
            assert value in metadata
        button = row.add_suffix.call_args_list[0].args[0]
        row.set_activatable_widget.assert_called_once_with(button)
        page.compare = MagicMock()
        button.connect.call_args.args[1](button)
        page.compare.assert_called_once_with(VALID.name)
        page.review_restoration = MagicMock()
        page.review_recovery = MagicMock()
        for index, action in ((1, page.review_restoration), (2, page.review_recovery)):
            action_button = row.add_suffix.call_args_list[index].args[0]
            action_button.connect.call_args.args[1](action_button)
            action.assert_called_once_with(VALID.name)

    @pytest.mark.parametrize("status", ["available", "unavailable"])
    def test_empty_or_missing_directory_does_not_create(self, page, scheduled, monkeypatch, status):
        listing = replace(LISTING, status=status, backups=(), notes=("Directory missing",))
        monkeypatch.setattr(backups, "run_list", lambda *a, **kw: listing)
        page.refresh()
        finish(scheduled)
        text = page._status.set_label.call_args.args[0]
        assert "No backup candidates" in text and "Directory missing" in text
        assert not page._output_path.exists()
        cast(MagicMock, page_module.Gtk.Button).assert_not_called()

    @pytest.mark.parametrize("status", ["invalid", "unavailable"])
    def test_invalid_unknown_or_stale_selection_is_inert(self, page, monkeypatch, status):
        page._listing = replace(LISTING, backups=(replace(VALID, status=status),))
        collector = MagicMock()
        monkeypatch.setattr(backups, "run_compare", collector)
        page.compare(VALID.name)
        page.compare("unknown")
        page._listing = LISTING
        page._stale = True
        page.compare(VALID.name)
        collector.assert_not_called()

    def test_single_non_daemon_worker_and_lazy_navigation(self, page, scheduled, monkeypatch):
        entered = threading.Event()
        release = threading.Event()
        workers = []

        def collect(path, **kwargs):
            assert path == page._output_path
            assert kwargs["cancel_event"] is page._cancel_event
            workers.append(threading.current_thread())
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Test worker not released")
            return LISTING

        monkeypatch.setattr(backups, "run_list", collect)
        compare = MagicMock()
        monkeypatch.setattr(backups, "run_compare", compare)
        try:
            page.ensure_loaded()
            assert entered.wait(3)
            page.refresh()
            page.ensure_loaded()
            page.compare(VALID.name)
            assert len(workers) == 1
            assert not workers[0].daemon and workers[0] is not threading.current_thread()
            page._rows.append.assert_not_called()
            page._refresh_button.set_sensitive.assert_called_with(False)
            page._rows.set_sensitive.assert_called_with(False)
        finally:
            release.set()
        finish(scheduled)
        page.ensure_loaded()
        assert len(workers) == 1
        compare.assert_not_called()

    @pytest.mark.parametrize("previous", [False, True])
    def test_failed_refresh_clears_diff_retains_explicit_stale_rows(
        self, page, scheduled, monkeypatch, previous
    ):
        page._listing = LISTING if previous else None
        monkeypatch.setattr(backups, "run_list", MagicMock(side_effect=TimeoutError("<timeout>&")))
        page.refresh()
        page._diff.set_visible.assert_called_with(False)
        page._diff.set_precomputed_diff.assert_called_once_with(
            "", added_lines=0, removed_lines=0, title="BACKUP -> CURRENT"
        )
        finish(scheduled)
        message = page._status.set_label.call_args.args[0]
        assert "<timeout>&" in message
        assert ("Stale rows retained" if previous else "No observation available") in message
        cast(MagicMock, page_module.clear_children).assert_not_called()
        page._rows.set_sensitive.assert_called_with(not previous)
        assert page._stale is previous
        monkeypatch.setattr(backups, "run_list", lambda *a, **kw: LISTING)
        page.refresh()
        finish(scheduled)
        assert not page._stale
        page._rows.set_sensitive.assert_called_with(True)

    @pytest.mark.parametrize("current_status", ["owned", "foreign", "invalid", "missing"])
    @pytest.mark.parametrize("kind", ["changed", "equal", "truncated", "too_large", "error"])
    def test_comparison_direction_states_and_warnings(
        self, page, scheduled, monkeypatch, current_status, kind
    ):
        page._listing = LISTING
        result = replace(COMPARISON, current=replace(CURRENT, status=current_status))
        if kind == "equal":
            result = replace(result, diff="", added_lines=0, removed_lines=0)
        elif kind == "truncated":
            result = replace(result, truncated=True)
        elif kind in ("too_large", "error"):
            result = replace(result, status=kind, diff="", added_lines=None, removed_lines=None)
        collector = MagicMock(return_value=result)
        monkeypatch.setattr(backups, "run_compare", collector)
        page.compare(VALID.name)
        page.refresh()
        page.compare(VALID.name)
        finish(scheduled)
        collector.assert_called_once_with(
            page._output_path, VALID.name, cancel_event=page._cancel_event
        )
        text = page._comparison_status.set_label.call_args.args[0]
        for value in (
            STAMP,
            VALID.name,
            CURRENT.lexical_path,
            CURRENT.resolved_path,
            current_status,
            "<note>&",
            "BACKUP -> CURRENT",
        ):
            assert value in text
        if current_status == "missing":
            assert "empty CURRENT" in text
        if kind in ("too_large", "error"):
            assert "Warning: no diff" in text
            page._diff.set_visible.assert_called_with(False)
            assert page._diff.set_precomputed_diff.call_count == 1  # Clear only.
        else:
            call = page._diff.set_precomputed_diff.call_args
            assert call.args == (result.diff,)
            assert call.kwargs["added_lines"] == result.added_lines
            assert call.kwargs["removed_lines"] == result.removed_lines
            expected = "Diff truncated" if kind == "truncated" else "No textual differences"
            assert expected in call.kwargs["empty_message"]
            page._diff.set_visible.assert_called_with(True)
            assert ("Warning: diff truncated" in text) is (kind == "truncated")
        page._diff.set_texts.assert_not_called()
        assert "next save" not in text and "up to date" not in text

    def test_compare_failure_cannot_retain_old_diff(self, page, scheduled, monkeypatch):
        page._listing = LISTING
        monkeypatch.setattr(backups, "run_compare", MagicMock(side_effect=ValueError("changed")))
        page.compare(VALID.name)
        finish(scheduled)
        assert "changed. No diff" in page._comparison_status.set_label.call_args.args[0]
        page._diff.set_visible.assert_called_with(False)

    def test_old_completion_cannot_overwrite_new_operation(self, page, scheduled, monkeypatch):
        monkeypatch.setattr(backups, "run_list", lambda *a, **kw: LISTING)
        page.refresh()
        callback, args = finish(scheduled)
        monkeypatch.setattr(backups, "run_compare", lambda *a, **kw: COMPARISON)
        page.compare(VALID.name)
        page._status.reset_mock()
        callback(*args)
        assert page._loading
        page._status.set_label.assert_not_called()
        finish(scheduled)
        assert not page._loading

    @pytest.mark.parametrize("operation", ["list", "compare"])
    def test_close_cancels_worker_and_ignores_late_callbacks(
        self, page, scheduled, monkeypatch, operation
    ):
        entered = threading.Event()
        release = threading.Event()

        def collect(path, *args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Test worker not released")
            assert kwargs["cancel_event"].is_set()
            return LISTING if operation == "list" else COMPARISON

        collector = MagicMock(side_effect=collect)
        monkeypatch.setattr(backups, "run_" + operation, collector)
        try:
            if operation == "list":
                page.refresh()
            else:
                page._listing = LISTING
                page.compare(VALID.name)
            assert entered.wait(3)
            page.close()
            assert page._cancel_event.is_set()
            page._status.reset_mock()
            page._refresh_button.reset_mock()
            page._comparison_status.reset_mock()
        finally:
            release.set()
        finish(scheduled)
        page.refresh()
        page.ensure_loaded()
        page._status.set_label.assert_not_called()
        page._refresh_button.set_sensitive.assert_not_called()
        assert page._listing is (None if operation == "list" else LISTING)
        page._comparison_status.set_label.assert_not_called()
        collector.assert_called_once()

    def test_worker_start_failure_allows_retry(self, page, scheduled, monkeypatch):
        monkeypatch.setattr(
            page_module.threading, "Thread", MagicMock(side_effect=RuntimeError("no thread"))
        )
        page.refresh()
        finish(scheduled)
        assert not page._loading
        assert "no thread" in page._status.set_label.call_args.args[0]

    def test_interpreter_exit_waits_for_cancelled_collector_cleanup(self, tmp_path):
        script = textwrap.dedent("""
            import pathlib, sys, time
            from unittest.mock import MagicMock
            from hyprmod.core import health
            from hyprmod.pages import backups as module
            path = pathlib.Path(sys.argv[1])
            original = health.run_bounded
            def bounded(command, **kwargs):
                code = ("import os,pathlib,sys,time; "
                        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)")
                return original([sys.executable, '-I', '-B', '-c', code, str(path)], **kwargs)
            health.run_bounded = bounded
            module.GLib.idle_add = MagicMock()
            page = module.BackupsPage(path.parent / 'attune.lua')
            for name in ('_refresh_button', '_status', '_rows', '_comparison_status', '_diff'):
                setattr(page, name, MagicMock())
            page.refresh()
            deadline = time.monotonic() + 3
            while not path.exists():
                if time.monotonic() > deadline:
                    raise TimeoutError('Collector did not start')
                time.sleep(0.01)
            page.close()
        """)
        pid_path = tmp_path / "collector.pid"
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", script, str(pid_path)],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=6,
            )
            assert result.returncode == 0, result.stderr
            with pytest.raises(ProcessLookupError):
                os.kill(int(pid_path.read_text()), 0)
        finally:
            if pid_path.exists():
                try:
                    os.killpg(int(pid_path.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass


class TestPrecomputedDiff:
    def test_precomputed_uses_literal_renderer_without_difflib(self, monkeypatch):
        widget = MagicMock()
        diff = "--- backup\n+++ current\n-<old>&\n+https://example.invalid\n"
        compute = MagicMock(side_effect=AssertionError("Must not compute on GTK"))
        monkeypatch.setattr("hyprmod.ui.diff.difflib.unified_diff", compute)
        ConfigDiffWidget.set_precomputed_diff(
            widget, diff, added_lines=8, removed_lines=9, title="BACKUP -> CURRENT"
        )
        widget._render_lines.assert_called_once_with(diff.splitlines(keepends=True))
        widget._added_label.set_label.assert_called_with("+8")
        widget._removed_label.set_label.assert_called_with("\u22129")
        widget._empty_label.set_label.assert_called_with("No textual differences")
        compute.assert_not_called()
