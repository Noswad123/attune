"""Health observations never contact the workstation or execute configuration."""

import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from hyprmod.core import config, health, persistence


@pytest.fixture(autouse=True)
def offline_health(monkeypatch):
    bounded_command = health.run_bounded
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.setattr(health.shutil, "which", lambda name: None)

    def forbidden(*args, **kwargs):
        pytest.fail("Unmocked subprocess: health tests must never contact the live desktop")

    monkeypatch.setattr(health, "run_bounded", forbidden)
    return bounded_command


@pytest.fixture
def output(tmp_path):
    path = tmp_path / "attune.lua"
    path.write_text(persistence.build_text({}, config.ConfigSections()), encoding="utf-8")
    return path


@pytest.fixture
def ipc(monkeypatch):
    responses = {
        "version": {"version": "0.55.0"},
        "configerrors": [""],
        "monitors": [
            {
                "name": "DP-1",
                "width": 2560,
                "height": 1440,
                "refreshRate": 143.97,
                "x": -1280,
                "y": 0,
                "scale": 1.25,
            }
        ],
    }
    calls = []
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "test-session")
    monkeypatch.setattr(health.shutil, "which", lambda name: f"/fake/{name}")

    def run(command, **kwargs):
        assert command[:2] == ["/fake/hyprctl", "-j"]
        assert command[2] in ("version", "configerrors", "monitors")
        assert kwargs == {"max_bytes": health._MAX_QUERY_BYTES, "timeout": 2}
        calls.append(command[2])
        response = responses[command[2]]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, subprocess.CompletedProcess):
            return response
        return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

    monkeypatch.setattr(health, "run_bounded", run)
    return responses, calls


def by_key(snapshot):
    return {check.key: check for check in snapshot.checks}


class TestObservations:
    def test_actual_ipc_shapes(self, output, ipc):
        snapshot = health.collect_snapshot(output)
        checks = by_key(snapshot)
        assert list(checks) == [
            "compositor",
            "config_errors",
            "displays",
            "output",
            "validator",
            "backups",
            "drift",
        ]
        assert ipc[1] == ["version", "configerrors", "monitors"]
        assert checks["compositor"].status == "available"
        assert "0.55.0" in checks["compositor"].summary
        assert checks["config_errors"].status == "available"
        assert checks["config_errors"].details == ()
        assert checks["displays"].details == (
            "DP-1: 2560x1440 @ 143.97 Hz, scale 1.25, position -1280,0 (effective)",
        )
        assert checks["output"].status == "available"
        assert "runtime loading is not established" in checks["output"].details[-1]

    def test_config_errors(self, output, ipc):
        ipc[0]["configerrors"] = ["", "bad option", "  ", "invalid monitor"]
        check = by_key(health.collect_snapshot(output))["config_errors"]
        assert check.status == "failed"
        assert check.details == ("bad option", "invalid monitor")

    @pytest.mark.parametrize("query", ["version", "configerrors", "monitors"])
    @pytest.mark.parametrize(
        "failure",
        [
            OSError("IPC failed"),
            ValueError("bad encoding"),
            subprocess.TimeoutExpired("hyprctl", 2),
            subprocess.CompletedProcess([], 1, "", "not surfaced"),
            subprocess.CompletedProcess([], 0, "not json", ""),
        ],
    )
    def test_query_failure_is_independent(self, output, ipc, query, failure):
        ipc[0][query] = failure
        checks = by_key(health.collect_snapshot(output))
        key = {"version": "compositor", "configerrors": "config_errors", "monitors": "displays"}[
            query
        ]
        assert checks[key].status == "failed"
        assert all(
            c.status == "available" for k, c in checks.items() if k not in (key, "backups", "drift")
        )
        assert len(ipc[1]) == 3

    @pytest.mark.parametrize(
        ("query", "value"),
        [
            ("version", []),
            ("version", {"version": ""}),
            ("version", {"version": 55}),
            ("configerrors", {}),
            ("configerrors", [None]),
            ("monitors", {}),
            ("monitors", [None]),
            ("monitors", [{"name": "DP-1"}]),
        ],
    )
    def test_invalid_query_shape(self, output, ipc, query, value):
        ipc[0][query] = value
        checks = health.collect_snapshot(output).checks
        assert sum(c.status == "failed" for c in checks) == 1

    @pytest.mark.parametrize("field", ["width", "height", "refreshRate", "x", "y", "scale"])
    @pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "1", None])
    def test_invalid_display_numbers(self, output, ipc, field, value):
        ipc[0]["monitors"][0][field] = value
        assert by_key(health.collect_snapshot(output))["displays"].status == "failed"

    def test_empty_displays_are_unknown(self, output, ipc):
        ipc[0]["monitors"] = []
        assert by_key(health.collect_snapshot(output))["displays"].status == "unknown"

    @pytest.mark.parametrize("session", [False, True])
    def test_offline_no_subprocess(self, monkeypatch, output, session):
        if session:
            monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "test")
        else:
            monkeypatch.setattr(health.shutil, "which", lambda name: "/fake/executable")
        checks = health.collect_snapshot(output).checks
        assert all(c.status == "unavailable" for c in checks[:3])

    def test_default_path_missing_tools_and_no_writes(self, monkeypatch, tmp_path):
        path = tmp_path / "missing" / "attune.lua"
        monkeypatch.setattr(config, "managed_path", lambda: path)
        before = set(tmp_path.rglob("*"))
        checks = by_key(health.collect_snapshot())
        assert checks["output"].status == "unavailable"
        assert checks["validator"].status == "unavailable"
        assert checks["backups"].status == "unavailable"
        assert set(tmp_path.rglob("*")) == before

    @pytest.mark.parametrize("query", ["version", "configerrors", "monitors"])
    def test_recursive_ipc_decoder_is_per_check_failure(self, output, ipc, monkeypatch, query):
        original_loads = json.loads
        recursive_response = json.dumps(ipc[0][query])

        def decode(text, *args, **kwargs):
            if text == recursive_response:
                raise RecursionError("recursive external JSON")
            return original_loads(text, *args, **kwargs)

        monkeypatch.setattr(health.json, "loads", decode)
        checks = health.collect_snapshot(output).checks
        assert sum(c.status == "failed" for c in checks) == 1
        assert checks[3].status == "available"
        assert len(ipc[1]) == 3

    @pytest.mark.parametrize("query", ["version", "configerrors", "monitors"])
    def test_oversized_query_preserves_other_observations(self, output, ipc, monkeypatch, query):
        original_run = health.run_bounded

        def run(command, **kwargs):
            if command[-1] == query:
                raise ValueError("Health command response exceeds capture limit")
            return original_run(command, **kwargs)

        monkeypatch.setattr(health, "run_bounded", run)
        snapshot = health.collect_snapshot(output)
        assert len(snapshot.checks) == 7
        assert sum(c.status == "failed" for c in snapshot.checks) == 1
        assert snapshot.checks[3].status == "available"
        assert health.HealthSnapshot.from_json(snapshot.to_json()) == snapshot

    def test_many_large_messages_are_bounded(self, output, ipc):
        ipc[0]["configerrors"] = ["x" * 1025] * 100
        assert len(json.dumps(ipc[0]["configerrors"]).encode()) < health._MAX_QUERY_BYTES
        snapshot = health.collect_snapshot(output)
        check = by_key(snapshot)["config_errors"]
        assert check.status == "failed"
        assert len(check.details) == health._MAX_DETAILS
        assert all(len(s) <= health._MAX_TEXT for s in check.details)
        assert "truncated" in check.details[0]
        assert "omitted" in check.details[-1]
        assert len(snapshot.to_json().encode("utf-8")) < health._MAX_JSON_BYTES
        assert by_key(snapshot)["displays"].status == "available"


class TestOutput:
    @pytest.mark.parametrize(
        "content",
        [
            b"print('never execute')",
            b"\xff",
            b"-- Generated by Attune\n-- Attune data v1: invalid\n",
            b"-- Generated by Attune\n-- Attune data v1: WzEsMl0=\n",
        ],
    )
    def test_foreign_corrupt_or_invalid_encoding(self, output, content):
        output.write_bytes(content)
        assert by_key(health.collect_snapshot(output))["output"].status == "failed"
        assert output.read_bytes() == content

    def test_empty(self, output):
        output.write_bytes(b"")
        assert by_key(health.collect_snapshot(output))["output"].status == "unknown"

    def test_missing_file(self, output):
        output.unlink()
        check = by_key(health.collect_snapshot(output))["output"]
        assert check.status == "unavailable"
        assert str(output) in " ".join(check.details)

    @pytest.mark.parametrize("parent_link", [False, True])
    def test_symlinks_preserved(self, tmp_path, output, parent_link):
        directory = tmp_path / "links"
        if parent_link:
            directory.symlink_to(output.parent, target_is_directory=True)
        else:
            directory.mkdir()
            (directory / "attune.lua").symlink_to(output)
        path = directory / "attune.lua"
        check = by_key(health.collect_snapshot(path))["output"]
        assert check.status == "available"
        assert any("symlink" in d for d in check.details)
        assert str(output) in " ".join(check.details)
        assert (directory if parent_link else path).is_symlink()

    @pytest.mark.parametrize("kind", ["cycle", "dangling", "directory", "fifo", "hardlink", "main"])
    def test_unsafe_output(self, tmp_path, kind):
        path = tmp_path / "attune.lua"
        if kind == "cycle":
            path.symlink_to(path)
        elif kind == "dangling":
            path.symlink_to(tmp_path / "absent" / "attune.lua")
        elif kind == "directory":
            path.mkdir()
        elif kind == "fifo":
            os.mkfifo(path)
        elif kind == "hardlink":
            other = tmp_path / "other"
            other.write_text("foreign")
            path.hardlink_to(other)
        else:
            other = tmp_path / "hyprland.lua"
            other.write_text("foreign")
            path.symlink_to(other)
        assert by_key(health.collect_snapshot(path))["output"].status == "failed"

    def test_size_limit(self, output, monkeypatch):
        monkeypatch.setattr(health, "_MAX_OUTPUT_BYTES", 4)
        assert "inspection limit" in by_key(health.collect_snapshot(output))["output"].summary

    def test_socket_is_not_opened(self, tmp_path):
        path = tmp_path / "attune.lua"
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(path))
            assert by_key(health.collect_snapshot(path))["output"].status == "failed"

    @pytest.mark.parametrize("replacement", ["regular", "fifo", "symlink"])
    def test_changed_destination_is_rejected(self, output, monkeypatch, replacement):
        original_open = os.open

        def changed_open(path, flags):
            output.unlink()
            if replacement == "regular":
                output.write_bytes(b"foreign")
            elif replacement == "fifo":
                os.mkfifo(output)
            else:
                output.symlink_to(output.parent / "missing")
            return original_open(path, flags)

        monkeypatch.setattr(health.os, "open", changed_open)
        assert by_key(health.collect_snapshot(output))["output"].status == "failed"

    def test_output_failure_preserves_other_checks(self, output, ipc, monkeypatch):
        def denied(*args):
            raise PermissionError("Output inspection denied")

        monkeypatch.setattr(persistence, "resolve_target", denied)
        checks = by_key(health.collect_snapshot(output))
        assert checks["output"].status == "failed"
        assert checks["validator"].status == "available"
        assert checks["compositor"].status == "available"

    def test_programming_errors_are_not_suppressed(self, output, monkeypatch):
        def bug(*args):
            raise RuntimeError("programming bug")

        monkeypatch.setattr(persistence, "read_document", bug)
        with pytest.raises(RuntimeError, match="programming bug"):
            health.collect_snapshot(output)

    def test_recursive_persistence_decoder_preserves_partial_snapshot(
        self, output, ipc, monkeypatch
    ):
        original_loads = json.loads

        def decode(text, *args, **kwargs):
            if isinstance(text, bytes):
                raise RecursionError("recursive external record")
            return original_loads(text, *args, **kwargs)

        monkeypatch.setattr(persistence.json, "loads", decode)
        checks = by_key(health.collect_snapshot(output))
        assert checks["output"].status == "failed"
        assert "too deeply nested" in checks["output"].summary
        assert checks["displays"].status == "available"


class TestBackups:
    def test_candidates_not_verified(self, output):
        path = Path(os.environ["XDG_STATE_HOME"]) / "attune" / "backups"
        path.mkdir(parents=True)
        (path / ("a" * 64 + ".lua")).write_text("not verified")
        (path / ("b" * 64 + ".lua")).symlink_to(output)
        (path / ("c" * 64 + ".lua")).mkdir()
        (path / "unrelated.lua").write_text("ignored")
        check = by_key(health.collect_snapshot(output))["backups"]
        assert check.status == "available"
        assert check.summary == "1 regular hash-named backup candidates"
        assert "not verified" in check.details[-1]

    def test_truncation(self, output, monkeypatch):
        path = Path(os.environ["XDG_STATE_HOME"]) / "attune" / "backups"
        path.mkdir(parents=True)
        for index in range(3):
            (path / f"{index:064x}.lua").touch()
        monkeypatch.setattr(health, "_MAX_BACKUP_ENTRIES", 2)
        check = by_key(health.collect_snapshot(output))["backups"]
        assert check.status == "unknown"
        assert "truncated" in check.summary

    def test_backup_and_validator_errors_are_independent(self, output, monkeypatch):
        def denied(*args):
            raise PermissionError("Inspection denied")

        monkeypatch.setattr(health.os, "scandir", denied)
        monkeypatch.setattr(health.shutil, "which", denied)
        checks = by_key(health.collect_snapshot(output))
        assert checks["output"].status == "available"
        assert checks["validator"].status == checks["backups"].status == "failed"


class TestProcessContract:
    def test_frozen_roundtrip(self, output):
        snapshot = health.collect_snapshot(output)
        assert health.HealthSnapshot.from_json(snapshot.to_json()) == snapshot
        with pytest.raises(FrozenInstanceError):
            setattr(snapshot.checks[0], "summary", "changed")

    @pytest.mark.parametrize(
        "change",
        [
            lambda d: d.update(observed_at="2026-10-26T00:00:00"),
            lambda d: d.update(observed_at="2026-10-26T00:00:00+01:00"),
            lambda d: d.update(checks=[]),
            lambda d: d.update(extra=True),
            lambda d: d["checks"][0].update(status="healthy"),
            lambda d: d["checks"][0].update(details=[3]),
            lambda d: d["checks"][0].update(key="other"),
            lambda d: d["checks"][0].update(title="Other"),
            lambda d: d["checks"][0].update(summary=False),
            lambda d: d["checks"][0].update(summary="x" * 1025),
            lambda d: d["checks"][0].update(details=["x"] * 17),
            lambda d: d["checks"][0].update(details=["x" * 1025]),
            lambda d: d.update(observed_at="x" * 65),
            lambda d: d["checks"].reverse(),
        ],
    )
    def test_invalid_response(self, output, change):
        data = json.loads(health.collect_snapshot(output).to_json())
        change(data)
        with pytest.raises(ValueError):
            health.HealthSnapshot.from_json(json.dumps(data))

    def test_child_invocation(self, output, monkeypatch):
        snapshot = health.collect_snapshot(output)

        def run(command, **kwargs):
            assert command == [
                sys.executable,
                "-I",
                "-B",
                "-m",
                "hyprmod.core.health",
                "--output",
                str(output),
            ]
            assert kwargs == {
                "cwd": Path(health.__file__).resolve().parents[2],
                "timeout": 10,
                "max_bytes": health._MAX_JSON_BYTES,
                "process_group": True,
                "cancel_event": None,
            }
            return subprocess.CompletedProcess(command, 0, snapshot.to_json(), "")

        monkeypatch.setattr(health, "run_bounded", run)
        assert health.run_snapshot(output) == snapshot

    @pytest.mark.parametrize(
        "failure",
        [
            subprocess.TimeoutExpired("child", 0.01),
            OSError("spawn failed"),
        ],
    )
    def test_child_errors_propagate(self, output, monkeypatch, failure):
        def run(*args, **kwargs):
            raise failure

        monkeypatch.setattr(health, "run_bounded", run)
        with pytest.raises(type(failure)):
            health.run_snapshot(output, timeout=0.01)

    @pytest.mark.parametrize(("returncode", "stdout"), [(1, ""), (0, "no JSON"), (0, "{}")])
    def test_child_bad_response(self, output, monkeypatch, returncode, stdout):
        monkeypatch.setattr(
            health,
            "run_bounded",
            lambda *a, **kw: subprocess.CompletedProcess([], returncode, stdout, ""),
        )
        with pytest.raises(ValueError):
            health.run_snapshot(output)

    @pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
    def test_invalid_timeout_does_not_spawn(self, output, timeout):
        with pytest.raises(ValueError, match="timeout"):
            health.run_snapshot(output, timeout)

    @pytest.mark.parametrize("text", ["[]", "null", "{", "[" * 2000])
    def test_malformed_json(self, text):
        with pytest.raises(ValueError):
            health.HealthSnapshot.from_json(text)

    def test_response_size_limit(self, output, monkeypatch):
        text = health.collect_snapshot(output).to_json()
        monkeypatch.setattr(health, "_MAX_JSON_BYTES", 4)
        with pytest.raises(ValueError, match="size limit"):
            health.HealthSnapshot.from_json(text)

    def test_worst_case_text_budget_fits_transport(self, output):
        snapshot = health.collect_snapshot(output)
        text = "\U0001f600" * health._MAX_TEXT
        checks = tuple(
            health.HealthCheck(c.key, c.title, c.status, text, (text,) * health._MAX_DETAILS)
            for c in snapshot.checks
        )
        snapshot = health.HealthSnapshot(snapshot.observed_at, checks)
        encoded = snapshot.to_json()
        assert len(encoded.encode("utf-8")) < health._MAX_JSON_BYTES
        assert health.HealthSnapshot.from_json(encoded) == snapshot

    def test_cancel_event_forwarded(self, output, monkeypatch):
        event = threading.Event()

        def cancelled(*args, **kwargs):
            assert kwargs["cancel_event"] is event
            raise InterruptedError("cancelled")

        monkeypatch.setattr(health, "run_bounded", cancelled)
        with pytest.raises(InterruptedError):
            health.run_snapshot(output, cancel_event=event)


class TestBoundedCapture:
    @pytest.mark.parametrize("stream", [1, 2])
    def test_real_oversized_ipc_capture_preserves_snapshot(
        self,
        offline_health,
        output,
        ipc,
        monkeypatch,
        stream,
    ):
        original_popen = subprocess.Popen

        def spawn(command, **kwargs):
            assert command[:2] == ["/fake/hyprctl", "-j"]
            assert kwargs["start_new_session"] is False
            if command[-1] == "configerrors":
                code = f"import os; os.write({stream}, b'x' * (129 * 1024))"
            else:
                response = json.dumps(ipc[0][command[-1]])
                code = f"print({response!r})"
            return original_popen([sys.executable, "-I", "-B", "-c", code], **kwargs)

        monkeypatch.setattr(health.subprocess, "Popen", spawn)
        monkeypatch.setattr(health, "run_bounded", offline_health)
        snapshot = health.collect_snapshot(output)
        checks = by_key(snapshot)
        assert checks["config_errors"].status == "failed"
        assert "capture limit" in checks["config_errors"].summary
        assert checks["compositor"].status == checks["displays"].status == "available"
        assert checks["output"].status == "available"
        assert len(snapshot.checks) == 7
        assert health.HealthSnapshot.from_json(snapshot.to_json()) == snapshot

    @pytest.mark.parametrize("stream", [1, 2])
    def test_output_flood_is_rejected(self, offline_health, stream):
        command = [sys.executable, "-I", "-B", "-c", f"import os; os.write({stream}, b'x'*1048576)"]
        with pytest.raises(ValueError, match="capture limit"):
            offline_health(command, timeout=3, max_bytes=128, process_group=True)

    def test_both_streams_are_drained(self, offline_health):
        code = "import os; os.write(2,b'e'*100000); os.write(1,b'o'*100000)"
        result = offline_health(
            [sys.executable, "-I", "-B", "-c", code],
            timeout=3,
            max_bytes=128 * 1024,
        )
        assert result.returncode == 0
        assert result.stdout == "o" * 100000
        assert result.stderr == "e" * 100000

    def test_query_timeout_kills_and_reaps_direct_child(self, offline_health, monkeypatch):
        original_popen = subprocess.Popen
        children = []

        def spawn(command, **kwargs):
            assert kwargs["start_new_session"] is False
            child = original_popen(command, **kwargs)
            children.append(child)
            return child

        monkeypatch.setattr(health.subprocess, "Popen", spawn)
        with pytest.raises(subprocess.TimeoutExpired):
            offline_health(
                [sys.executable, "-I", "-B", "-c", "import time; time.sleep(60)"],
                timeout=0.1,
                max_bytes=128,
            )
        assert children[0].returncode == -9
        with pytest.raises(ChildProcessError):
            os.waitpid(children[0].pid, os.WNOHANG)

    def test_pre_cancel_does_not_spawn(self, offline_health, monkeypatch):
        event = threading.Event()
        event.set()

        def forbidden(*args, **kwargs):
            pytest.fail("Pre-cancelled observation spawned a child")

        monkeypatch.setattr(health.subprocess, "Popen", forbidden)
        with pytest.raises(InterruptedError):
            offline_health([sys.executable], timeout=2, max_bytes=128, cancel_event=event)

    @pytest.mark.parametrize("mode", ["timeout", "cancel", "success"])
    def test_supervisor_kills_descendants_and_reaps_collector(
        self,
        offline_health,
        tmp_path,
        output,
        mode,
    ):
        # A separate Linux subreaper owns orphaned grandchildren, never the pytest process.
        snapshot = health.collect_snapshot(output).to_json()
        worker = textwrap.dedent("""
            import pathlib, subprocess, sys, time
            child = subprocess.Popen(
                [sys.executable, '-I', '-B', '-c', 'import time; time.sleep(60)'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            pathlib.Path(sys.argv[1]).write_text(str(child.pid))
            if sys.argv[2] == 'success':
                print(sys.argv[3], flush=True)
            else:
                time.sleep(60)
        """)
        harness = textwrap.dedent("""
            import ctypes, os, pathlib, signal, subprocess, sys, threading, time
            from hyprmod.core import health
            if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
                raise OSError('Cannot establish isolated test subreaper')
            worker, path, mode, snapshot = sys.argv[1:]
            path = pathlib.Path(path)
            original_popen = subprocess.Popen
            parents = []
            def spawn(command, **kwargs):
                assert command[4] == 'hyprmod.core.health'
                assert kwargs['start_new_session'] is True
                process = original_popen(
                    [sys.executable, '-I', '-B', '-c', worker, str(path), mode, snapshot],
                    **kwargs,
                )
                parents.append(process.pid)
                return process
            health.subprocess.Popen = spawn
            event = threading.Event()
            def cancel_when_ready():
                deadline = time.monotonic() + 3
                while not path.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                event.set()
            thread = threading.Thread(target=cancel_when_ready, daemon=True)
            if mode == 'cancel':
                thread.start()
            started = time.monotonic()
            try:
                try:
                    result = health.run_snapshot(
                        path.parent / 'attune.lua', timeout=2,
                        cancel_event=event if mode == 'cancel' else None,
                    )
                except subprocess.TimeoutExpired:
                    assert mode == 'timeout'
                except InterruptedError:
                    assert mode == 'cancel'
                else:
                    assert mode == 'success'
                    assert result.to_json() == snapshot
                if mode == 'cancel':
                    assert time.monotonic() - started < 1.5
                assert path.exists(), 'descendant never started'
                descendant = int(path.read_text())
                deadline = time.monotonic() + 2
                while True:
                    pid, status = os.waitpid(descendant, os.WNOHANG)
                    if pid:
                        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
                        break
                    assert time.monotonic() < deadline, 'descendant survived cleanup'
                    time.sleep(0.01)
                try:
                    os.waitpid(parents[0], os.WNOHANG)
                except ChildProcessError:
                    pass
                else:
                    raise AssertionError('collector was not reaped')
            finally:
                for pid in parents:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if path.exists():
                    try:
                        os.waitpid(int(path.read_text()), 0)
                    except ChildProcessError:
                        pass
        """)
        result = offline_health(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                harness,
                worker,
                str(tmp_path / "descendant.pid"),
                mode,
                snapshot,
            ],
            timeout=8,
            max_bytes=8192,
            process_group=True,
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
