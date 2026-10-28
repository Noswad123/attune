"""Health refresh scheduling without GTK widgets or a compositor session."""

import os
import signal
import subprocess
import sys
import textwrap
import threading
from queue import Queue
from typing import cast
from unittest.mock import MagicMock

import pytest

from hyprmod.core.health import HealthCheck, HealthSnapshot
from hyprmod.pages import health as page_module
from hyprmod.pages.health import HealthPage


@pytest.fixture
def page(tmp_path, monkeypatch):
    page = HealthPage(tmp_path / "attune.lua")
    page._refresh_button = MagicMock()
    page._preview_button = MagicMock()
    page._status = MagicMock()
    page._checks = MagicMock()
    page._local_error = MagicMock()
    monkeypatch.setattr(page_module, "clear_children", MagicMock())
    monkeypatch.setattr(page_module.Adw, "PreferencesGroup", MagicMock())
    monkeypatch.setattr(page_module.Adw, "ActionRow", MagicMock())
    return page


@pytest.fixture
def scheduled(monkeypatch):
    callbacks = Queue()
    monkeypatch.setattr(page_module.GLib, "idle_add", lambda *args: callbacks.put(args))
    return callbacks


class TestHealthPage:
    @pytest.mark.parametrize(
        "loading,has_snapshot", [(False, False), (False, True), (True, False), (True, True)]
    )
    def test_preview_is_inert_without_completed_observation(
        self, page, monkeypatch, loading, has_snapshot
    ):
        page._loading = loading
        if has_snapshot:
            page._snapshot = HealthSnapshot("2026-10-26T12:00:00+00:00", ())
        dialog = MagicMock()
        monkeypatch.setattr(page_module.Adw, "Dialog", dialog)
        page.preview_report()
        dialog.assert_not_called()

    @pytest.mark.parametrize("folder", [False, True])
    def test_open_queries_async_and_uses_explicit_safe_association(self, page, monkeypatch, folder):
        file = MagicMock()
        # URI escaping is Gio's responsibility, never string concatenation or a shell.
        uri = page_module.Gio.File.new_for_path(str(page._output_path)).get_uri()
        file.get_uri.return_value = uri
        file.query_info_finish.return_value.get_file_type.return_value = (
            page_module.Gio.FileType.DIRECTORY if folder else page_module.Gio.FileType.REGULAR
        )
        new_file = MagicMock(return_value=file)
        monkeypatch.setattr(page_module.Gio.File, "new_for_path", new_file)
        association = MagicMock()
        monkeypatch.setattr(page_module.Gio.AppInfo, "get_default_for_type_async", association)
        app = MagicMock()
        app.launch_uris_finish.return_value = True
        monkeypatch.setattr(
            page_module.Gio.AppInfo, "get_default_for_type_finish", MagicMock(return_value=app)
        )
        page.open_output(folder=folder)
        new_file.assert_called_once_with(
            str(page._output_path.parent if folder else page._output_path)
        )
        association.assert_not_called()
        query = file.query_info_async.call_args.args
        assert query[0] == "standard::type"
        assert query[3] is page._launch_cancel
        query[4](file, MagicMock())
        args = association.call_args.args
        assert args[:2] == ("inode/directory" if folder else "text/plain", False)
        assert args[2] is page._launch_cancel
        args[3](None, MagicMock())
        launch = app.launch_uris_async.call_args.args
        assert launch[:3] == ([uri], None, page._launch_cancel)
        launch[3](app, MagicMock())
        page._local_error.set_label.assert_not_called()
        assert not page._output_path.exists()

    @pytest.mark.parametrize(
        "stage", ["missing", "wrong_type", "no_app", "association", "launch", "false"]
    )
    def test_open_failures_are_actionable_and_never_create_paths(self, page, monkeypatch, stage):
        file = MagicMock()
        file.query_info_finish.return_value.get_file_type.return_value = (
            page_module.Gio.FileType.REGULAR
        )
        monkeypatch.setattr(page_module.Gio.File, "new_for_path", MagicMock(return_value=file))
        association = MagicMock()
        monkeypatch.setattr(page_module.Gio.AppInfo, "get_default_for_type_async", association)
        app = MagicMock()
        finish = MagicMock(return_value=app)
        monkeypatch.setattr(page_module.Gio.AppInfo, "get_default_for_type_finish", finish)
        if stage == "missing":
            file.query_info_finish.side_effect = page_module.GLib.Error("missing")
        elif stage == "wrong_type":
            file.query_info_finish.return_value.get_file_type.return_value = (
                page_module.Gio.FileType.DIRECTORY
            )
        elif stage == "no_app":
            finish.return_value = None
        elif stage == "association":
            finish.side_effect = page_module.GLib.Error("no association")
        elif stage == "launch":
            app.launch_uris_finish.side_effect = page_module.GLib.Error("cannot launch")
        else:
            app.launch_uris_finish.return_value = False
        page.open_output()
        file.query_info_async.call_args.args[4](file, MagicMock())
        if stage not in ("missing", "wrong_type"):
            association.call_args.args[3](None, MagicMock())
            if stage in ("launch", "false"):
                app.launch_uris_async.call_args.args[3](app, MagicMock())
        message = page._local_error.set_label.call_args.args[0]
        assert any(word in message for word in ("retry", "Configure", "Check", "Select"))
        page._local_error.set_visible.assert_called_with(True)
        assert not page._output_path.exists()

    def test_close_cancels_launch_and_drops_pending_inspection(self, page, monkeypatch):
        file = MagicMock()
        monkeypatch.setattr(page_module.Gio.File, "new_for_path", MagicMock(return_value=file))
        page.open_output(folder=True)
        page.close()
        assert page._launch_cancel.is_cancelled()
        file.query_info_async.call_args.args[4](file, MagicMock())
        file.query_info_finish.assert_not_called()

    def test_construction_does_not_collect(self, tmp_path, monkeypatch):
        collector = MagicMock()
        monkeypatch.setattr(page_module.health, "run_snapshot", collector)
        HealthPage(tmp_path / "attune.lua")
        collector.assert_not_called()

    def test_async_single_non_daemon_and_lazy_once(self, page, scheduled, monkeypatch):
        release = threading.Event()
        entered = threading.Event()
        workers = []
        snapshot = HealthSnapshot("2026-10-26T12:00:00+00:00", ())

        def collect(path, **kwargs):
            assert path == page._output_path
            assert kwargs["cancel_event"] is page._cancel_event
            assert not kwargs["cancel_event"].is_set()
            workers.append(threading.current_thread())
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Test did not release worker")
            return snapshot

        monkeypatch.setattr(page_module.health, "run_snapshot", collect)
        try:
            page.ensure_loaded()
            assert entered.wait(3)
            page.refresh()
            page.ensure_loaded()
            assert len(workers) == 1
            assert workers[0] is not threading.current_thread()
            assert not workers[0].daemon
            page._refresh_button.set_sensitive.assert_called_once_with(False)
            page._checks.append.assert_not_called()
        finally:
            release.set()
        callback, *args = scheduled.get(timeout=3)
        assert page._loading
        callback(*args)
        assert not page._loading
        assert page._snapshot is snapshot
        page._refresh_button.set_sensitive.assert_called_with(True)
        page.ensure_loaded()
        assert len(workers) == 1

    def test_per_check_titles_status_and_literal_details(self, page, scheduled, monkeypatch):
        snapshot = HealthSnapshot(
            "2026-10-26T12:00:00+00:00",
            tuple(
                HealthCheck(status, f"Check {status}", status, "Summary", ("<literal>& detail",))
                for status in ("available", "unavailable", "unknown", "failed")
            ),
        )
        monkeypatch.setattr(page_module.health, "run_snapshot", lambda path, **kwargs: snapshot)
        page.refresh()
        callback, *args = scheduled.get(timeout=3)
        callback(*args)
        assert [
            call.kwargs["title"]
            for call in cast(MagicMock, page_module.Adw.PreferencesGroup).call_args_list
        ] == [check.title for check in snapshot.checks]
        rows = cast(MagicMock, page_module.Adw.ActionRow)
        assert [call.kwargs["title"] for call in rows.call_args_list] == [
            check.status.capitalize() for check in snapshot.checks
        ]
        rows.return_value.set_use_markup.assert_called_with(False)
        rows.return_value.set_subtitle.assert_called_with("Summary\n<literal>& detail")
        page._status.set_label.assert_called_with(f"Observed: {snapshot.observed_at}")

    @pytest.mark.parametrize("has_previous", [False, True])
    def test_failure_preserves_snapshot_and_allows_retry(
        self, page, scheduled, monkeypatch, has_previous
    ):
        previous = (
            HealthSnapshot(
                "2026-10-26T12:00:00+00:00",
                (HealthCheck("output", "Attune Output", "unknown", "Output is empty"),),
            )
            if has_previous
            else None
        )
        page._snapshot = previous
        collector = MagicMock(side_effect=TimeoutError("collector timeout"))
        monkeypatch.setattr(page_module.health, "run_snapshot", collector)
        page.refresh()
        callback, *args = scheduled.get(timeout=3)
        callback(*args)
        assert page._snapshot is previous
        assert page._stale is has_previous
        page._preview_button.set_sensitive.assert_called_with(has_previous)
        message = page._status.set_label.call_args.args[0]
        assert "Refresh failed: collector timeout" in message
        expected = "Stale observation retained" if has_previous else "No observation available"
        assert expected in message
        cast(MagicMock, page_module.clear_children).assert_not_called()
        page._refresh_button.set_sensitive.assert_called_with(True)
        page.refresh()
        callback, *args = scheduled.get(timeout=3)
        callback(*args)
        assert collector.call_count == 2

    def test_close_ignores_queued_completion_and_future_refresh(self, page, scheduled, monkeypatch):
        collector = MagicMock(return_value=HealthSnapshot("2026-10-26T12:00:00+00:00", ()))
        monkeypatch.setattr(page_module.health, "run_snapshot", collector)
        page.refresh()
        callback, *args = scheduled.get(timeout=3)
        page.close()
        assert page._cancel_event.is_set()
        assert collector.call_args.kwargs["cancel_event"] is page._cancel_event
        page._status.reset_mock()
        page._refresh_button.reset_mock()
        callback(*args)
        page.refresh()
        page._status.set_label.assert_not_called()
        page._refresh_button.set_sensitive.assert_not_called()
        page._checks.append.assert_not_called()
        assert page._snapshot is None
        collector.assert_called_once()

    @pytest.mark.skipif(sys.platform != "linux", reason="Uses an isolated Linux subreaper")
    def test_interpreter_exit_waits_for_cancelled_process_group_cleanup(self, tmp_path):
        collector = textwrap.dedent("""
            import os, pathlib, subprocess, sys, time
            path = pathlib.Path(sys.argv[1])
            path.write_text(str(os.getpid()))
            child = subprocess.Popen(
                [sys.executable, '-I', '-B', '-c', 'import time; time.sleep(60)'],
            )
            path.with_suffix('.child').write_text(str(child.pid))
            time.sleep(60)
        """)
        application = textwrap.dedent("""
            import pathlib, sys, threading, time
            from unittest.mock import MagicMock
            from hyprmod.core import health
            from hyprmod.pages.health import HealthPage
            collector, path = sys.argv[1:]
            path = pathlib.Path(path)
            page = HealthPage(path.parent / 'attune.lua')
            page._refresh_button = MagicMock()
            page._preview_button = MagicMock()
            page._status = MagicMock()
            health_page_module = sys.modules[HealthPage.__module__]
            health_page_module.GLib.idle_add = MagicMock()
            entered = threading.Event()
            class BlockedSelector(health.selectors.DefaultSelector):
                def select(self, timeout=None):
                    entered.set()
                    if not page._cancel_event.wait(3):
                        raise TimeoutError('Page did not close')
                    time.sleep(0.2)
                    return super().select(0)
            health.selectors.DefaultSelector = BlockedSelector
            def collect(output_path, **kwargs):
                return health.run_bounded(
                    [sys.executable, '-I', '-B', '-c', collector, str(path)],
                    timeout=4, max_bytes=8192, process_group=True, **kwargs,
                )
            health.run_snapshot = collect
            page.refresh()
            deadline = time.monotonic() + 3
            while not path.with_suffix('.child').exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError('Collector descendant did not start')
                time.sleep(0.01)
            if not entered.wait(1):
                raise TimeoutError('Supervisor did not reach selector')
            page.close()
        """)
        harness = textwrap.dedent("""
            import ctypes, os, pathlib, signal, subprocess, sys, time
            if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
                raise OSError('Cannot establish isolated test subreaper')
            application, collector, path = sys.argv[1:]
            path = pathlib.Path(path)
            try:
                started = time.monotonic()
                result = subprocess.run(
                    [sys.executable, '-I', '-B', '-c', application, collector, str(path)],
                    capture_output=True, text=True, timeout=6,
                )
                assert result.returncode == 0, result.stderr
                assert time.monotonic() - started < 3, 'Application exit was not prompt'
                collector_pid = int(path.read_text())
                descendant_pid = int(path.with_suffix('.child').read_text())
                deadline = time.monotonic() + 2
                while True:
                    pid, status = os.waitpid(descendant_pid, os.WNOHANG)
                    if pid:
                        assert os.WIFSIGNALED(status)
                        assert os.WTERMSIG(status) == signal.SIGKILL
                        break
                    assert time.monotonic() < deadline, 'Descendant survived application exit'
                    time.sleep(0.01)
                try:
                    os.kill(collector_pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    raise AssertionError('Collector survived or was not reaped')
            finally:
                if path.exists():
                    try:
                        os.killpg(int(path.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                for pid_file in (path, path.with_suffix('.child')):
                    if pid_file.exists():
                        try:
                            os.waitpid(int(pid_file.read_text()), 0)
                        except ChildProcessError:
                            pass
        """)
        pid_path = tmp_path / "collector.pid"
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", harness, application, collector, str(pid_path)],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == 0, result.stderr
        finally:
            if pid_path.exists():
                try:
                    os.killpg(int(pid_path.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_close_cancels_running_collector_without_waiting(self, page, scheduled, monkeypatch):
        entered = threading.Event()
        release = threading.Event()
        signals = []

        def collect(path, **kwargs):
            signals.append(kwargs["cancel_event"])
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Test did not release worker")
            raise InterruptedError("Health collection cancelled")

        collector = MagicMock(side_effect=collect)
        monkeypatch.setattr(page_module.health, "run_snapshot", collector)
        try:
            page.refresh()
            assert entered.wait(3)
            page.refresh()
            page.ensure_loaded()
            collector.assert_called_once()
            assert not signals[0].is_set()
            page.close()
            assert signals[0].is_set()
            page.refresh()
            page._status.reset_mock()
            page._refresh_button.reset_mock()
        finally:
            release.set()
        callback, *args = scheduled.get(timeout=3)
        callback(*args)
        collector.assert_called_once()
        page._status.set_label.assert_not_called()
        page._refresh_button.set_sensitive.assert_not_called()
