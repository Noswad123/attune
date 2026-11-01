"""Bounded stdin shares the existing collector's deadline and cleanup."""

import subprocess
import sys
import threading

import pytest

from hyprmod.core.health import run_bounded


def command(source):
    return [sys.executable, "-I", "-B", "-c", source]


class TestBoundedInput:
    @pytest.mark.parametrize("text", ["", "caf\u00e9\n" * 50000], ids=["empty", "large-utf8"])
    def test_roundtrip_larger_than_pipe_and_argv(self, text):
        result = run_bounded(
            command("import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"),
            input_text=text,
            max_bytes=1024 * 1024,
            timeout=10,
            process_group=True,
        )
        assert result.returncode == 0
        assert result.stdout == text

    def test_interleaved_output_does_not_deadlock(self):
        result = run_bounded(
            command(
                "import sys; sys.stdout.write('x'*200000); sys.stdout.flush(); "
                "sys.stdout.write(sys.stdin.read())"
            ),
            input_text="y" * 200000,
            max_bytes=1024 * 1024,
            timeout=10,
        )
        assert result.stdout == "x" * 200000 + "y" * 200000

    def test_closed_pipe_preserves_error(self):
        result = run_bounded(
            command("import os,sys; os.close(0); sys.stderr.write('refused'); sys.exit(7)"),
            input_text="x" * 300000,
            max_bytes=1024 * 1024,
            timeout=10,
        )
        assert result.returncode == 7
        assert result.stderr == "refused"

    def test_unread_input_times_out(self):
        with pytest.raises(subprocess.TimeoutExpired):
            run_bounded(
                command("import time; time.sleep(30)"),
                input_text="x" * 300000,
                max_bytes=1024 * 1024,
                timeout=0.1,
                process_group=True,
            )

    def test_cancel_during_input(self):
        event = threading.Event()
        timer = threading.Timer(0.1, event.set)
        timer.start()
        try:
            with pytest.raises(InterruptedError):
                run_bounded(
                    command("import time; time.sleep(30)"),
                    input_text="x" * 300000,
                    max_bytes=1024 * 1024,
                    timeout=10,
                    cancel_event=event,
                    process_group=True,
                )
        finally:
            timer.cancel()
            timer.join()

    def test_oversized_input_never_launches(self, monkeypatch):
        def forbidden(*args, **kwargs):
            pytest.fail("Oversized request launched a process")

        monkeypatch.setattr(subprocess, "Popen", forbidden)
        with pytest.raises(ValueError, match="input exceeds"):
            run_bounded(command(""), input_text="\u00e9" * 100, max_bytes=100, timeout=1)

    @pytest.mark.parametrize("input_text", [None, "request"])
    def test_output_limit_unchanged(self, input_text):
        with pytest.raises(ValueError, match="response exceeds"):
            run_bounded(
                command("print('x'*1000)"),
                input_text=input_text,
                max_bytes=100,
                timeout=5,
            )
