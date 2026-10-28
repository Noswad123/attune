"""Read-only observations, collected in a disposable process for the Health UI."""

import argparse
import json
import math
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from hyprland_config import Assignment, Document, normalize_gradient_string, parse_hyprlang_bool
from hyprland_schema import OPTIONS_BY_KEY

from hyprmod.core import config, persistence
from hyprmod.core.focused_ui import GENERAL_OPTIONS

HealthStatus = Literal["available", "unavailable", "unknown", "failed"]
_TITLES = {
    "compositor": "Compositor",
    "config_errors": "Configuration Errors",
    "displays": "Displays",
    "output": "Attune Output",
    "validator": "Lua Validator",
    "backups": "Backups",
    "drift": "Saved / Runtime Drift",
}
_STATUSES = ("available", "unavailable", "unknown", "failed")
_MAX_OUTPUT_BYTES = 1024 * 1024
_MAX_BACKUP_ENTRIES = 1000
_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_QUERY_BYTES = 128 * 1024
_MAX_TEXT = 1024
_MAX_DETAILS = 16
_MAX_DRIFT_QUERIES = 32
_DRIFT_SECONDS = 2.0


def run_bounded(
    command: list[str],
    *,
    timeout: float,
    max_bytes: int,
    cwd: Path | None = None,
    process_group: bool = False,
    cancel_event: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    """Capture bounded UTF-8 output with deadline, cancellation and optional group cleanup."""
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("Health observation cancelled")
    deadline = time.monotonic() + timeout
    with subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        start_new_session=process_group,
    ) as process:
        stdout = bytearray()
        stderr = bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                for stream, buffer, limit in (
                    (process.stdout, stdout, max_bytes),
                    (process.stderr, stderr, _MAX_QUERY_BYTES),
                ):
                    if stream is not None:
                        os.set_blocking(stream.fileno(), False)
                        selector.register(stream, selectors.EVENT_READ, (buffer, limit))
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("Health observation cancelled")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    if not selector.get_map() and process.poll() is not None:
                        break
                    for key, _ in selector.select(min(0.1, remaining)):
                        buffer, limit = key.data
                        try:
                            chunk = os.read(key.fd, min(65536, limit - len(buffer) + 1))
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                        elif len(buffer) + len(chunk) > limit:
                            raise ValueError("Health command response exceeds capture limit")
                        else:
                            buffer.extend(chunk)
            return subprocess.CompletedProcess(
                command, process.wait(), stdout.decode("utf-8"), stderr.decode("utf-8")
            )
        finally:
            # Queries inherit the collector's group so outer cleanup also reaches them.
            if process_group:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
            process.wait()


def _bounded_check(check: "HealthCheck") -> "HealthCheck":
    def shorten(text: str) -> str:
        marker = "... [truncated]"
        return text if len(text) <= _MAX_TEXT else text[: _MAX_TEXT - len(marker)] + marker

    details = check.details
    if len(details) > _MAX_DETAILS:
        omitted = len(details) - _MAX_DETAILS + 1
        details = (*details[: _MAX_DETAILS - 1], f"{omitted} further details omitted [truncated]")
    return HealthCheck(
        check.key, check.title, check.status, shorten(check.summary), tuple(map(shorten, details))
    )


@dataclass(frozen=True)
class HealthCheck:
    key: str
    title: str
    status: HealthStatus
    summary: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class HealthSnapshot:
    observed_at: str
    checks: tuple[HealthCheck, ...]

    def to_json(self) -> str:
        text = json.dumps(asdict(self), ensure_ascii=True, allow_nan=False)
        self.from_json(text)
        return text

    @classmethod
    def from_json(cls, text: str) -> "HealthSnapshot":
        if len(text) > _MAX_JSON_BYTES or len(text.encode("utf-8")) > _MAX_JSON_BYTES:
            raise ValueError("Health response exceeds size limit")
        try:
            data = json.loads(text)
        except RecursionError as exc:
            raise ValueError("Health response is too deeply nested") from exc
        if not isinstance(data, dict) or set(data) != {"observed_at", "checks"}:
            raise ValueError("Invalid health snapshot")
        observed_at = data["observed_at"]
        if not isinstance(observed_at, str) or len(observed_at) > 64:
            raise ValueError("Invalid observation time")
        stamp = datetime.fromisoformat(observed_at)
        if "T" not in observed_at or stamp.utcoffset() != timedelta(0):
            raise ValueError("Observation time must be ISO8601 UTC")
        records = data["checks"]
        if not isinstance(records, list) or len(records) != len(_TITLES):
            raise ValueError("Expected seven health checks")
        checks = []
        for key, record in zip(_TITLES, records, strict=True):
            if not isinstance(record, dict) or set(record) != {
                "key",
                "title",
                "status",
                "summary",
                "details",
            }:
                raise ValueError("Invalid health check fields")
            if record["key"] != key or record["title"] != _TITLES[key]:
                raise ValueError("Invalid health check identity or order")
            if record["status"] not in _STATUSES or not isinstance(record["summary"], str):
                raise ValueError("Invalid health check status or summary")
            if len(record["summary"]) > _MAX_TEXT:
                raise ValueError("Health summary exceeds limit")
            details = record["details"]
            if not isinstance(details, list) or not all(isinstance(s, str) for s in details):
                raise ValueError("Invalid health check details")
            if len(details) > _MAX_DETAILS or any(len(s) > _MAX_TEXT for s in details):
                raise ValueError("Health details exceed limit")
            checks.append(HealthCheck(**{**record, "details": tuple(details)}))
        return cls(observed_at, tuple(checks))


def _ipc_checks() -> list[HealthCheck]:
    checks = []
    try:
        executable = (
            shutil.which("hyprctl") if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") else None
        )
    except (OSError, ValueError) as exc:
        return [HealthCheck(k, _TITLES[k], "failed", str(exc)) for k in tuple(_TITLES)[:3]]
    if executable is None:
        reason = (
            "No Hyprland session signature"
            if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
            else "hyprctl is not available on PATH"
        )
        return [HealthCheck(k, _TITLES[k], "unavailable", reason) for k in tuple(_TITLES)[:3]]
    for key, query in (
        ("compositor", "version"),
        ("config_errors", "configerrors"),
        ("displays", "monitors"),
    ):
        try:
            result = run_bounded(
                [executable, "-j", query],
                timeout=2,
                max_bytes=_MAX_QUERY_BYTES,
            )
            if result.returncode:
                raise ValueError(f"hyprctl {query} exited with status {result.returncode}")
            try:
                data = json.loads(result.stdout)
            except RecursionError as exc:
                raise ValueError("IPC response is too deeply nested") from exc
            status: HealthStatus = "available"
            details: tuple[str, ...] = ()
            if key == "compositor":
                if not isinstance(data, dict) or not isinstance(data.get("version"), str):
                    raise ValueError("Expected version object with a version string")
                if not data["version"].strip():
                    raise ValueError("Empty compositor version")
                summary = f"Hyprland {data['version']} (reachable)"
            elif key == "config_errors":
                if not isinstance(data, list) or not all(isinstance(s, str) for s in data):
                    raise ValueError("Expected configuration error strings")
                details = tuple(s for s in data if s.strip())
                status = "failed" if details else "available"
                summary = f"{len(details)} configuration errors reported"
            else:
                if not isinstance(data, list):
                    raise ValueError("Expected a display array")
                displays = []
                for monitor in data:
                    if (
                        not isinstance(monitor, dict)
                        or not isinstance(monitor.get("name"), str)
                        or not monitor["name"].strip()
                    ):
                        raise ValueError("Expected display object with a name")
                    for field in ("width", "height", "refreshRate", "x", "y", "scale"):
                        value = monitor.get(field)
                        if (
                            isinstance(value, bool)
                            or not isinstance(value, (int, float))
                            or (isinstance(value, float) and not math.isfinite(value))
                            or (field not in ("x", "y") and value <= 0)
                        ):
                            raise ValueError(f"Invalid display {field}")
                    displays.append(
                        f"{monitor['name']}: {monitor['width']}x{monitor['height']} "
                        f"@ {monitor['refreshRate']} Hz, scale {monitor['scale']}, "
                        f"position {monitor['x']},{monitor['y']} (effective)"
                    )
                details = tuple(displays)
                summary = f"{len(displays)} connected displays reported"
                status = "available" if displays else "unknown"
            checks.append(HealthCheck(key, _TITLES[key], status, summary, details))
        except subprocess.TimeoutExpired:
            checks.append(HealthCheck(key, _TITLES[key], "failed", f"hyprctl {query} timed out"))
        except (OSError, ValueError, UnicodeError) as exc:
            checks.append(HealthCheck(key, _TITLES[key], "failed", str(exc)))
    return checks


def read_owned_document(path: Path) -> Document | None:
    """Inspect one bounded, stable dedicated file; None denotes empty, unowned output."""
    target = persistence.resolve_target(path)
    before = target.stat()
    if before.st_size > _MAX_OUTPUT_BYTES:
        raise ValueError("Output exceeds the 1 MiB inspection limit")
    fd = os.open(target, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise ValueError("Output is non-regular, hardlinked, or changed during inspection")
        raw = stream.read(_MAX_OUTPUT_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > _MAX_OUTPUT_BYTES:
        raise ValueError("Output exceeds the 1 MiB inspection limit")
    if (
        (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
        != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or persistence.resolve_target(path) != target
        or target.stat() != after
    ):
        raise ValueError("Output changed during inspection")
    return persistence.read_document(raw.decode("utf-8")) if raw else None


def _output_check(path: Path) -> tuple[HealthCheck, Document | None]:
    details = [f"Lexical path: {path.absolute()}"]
    try:
        # This is descriptive only; the persistence resolver remains the ownership guard.
        try:
            resolved = path.resolve(strict=False)
            parent = path.parent.resolve(strict=False)
        except RuntimeError as exc:
            # Older pathlib versions use RuntimeError rather than ELOOP for cycles.
            raise ValueError(f"Symlink cycle: {exc}") from exc
        details.append(f"Resolved destination: {resolved}")
        if path.is_symlink():
            details.append("Output file is a symlink")
        if path.parent.absolute() != parent:
            details.append("Output parent contains a symlink")
        document = read_owned_document(path)
        if document is None:
            return HealthCheck(
                "output", _TITLES["output"], "unknown", "Output is empty", tuple(details)
            ), None
        details.append("Canonical Attune ownership is valid; runtime loading is not established")
        return HealthCheck(
            "output", _TITLES["output"], "available", "Owned Attune output", tuple(details)
        ), document
    except FileNotFoundError as exc:
        return HealthCheck(
            "output",
            _TITLES["output"],
            "unavailable",
            f"Output or parent missing: {exc}",
            tuple(details),
        ), None
    except (OSError, ValueError, UnicodeError) as exc:
        return HealthCheck("output", _TITLES["output"], "failed", str(exc), tuple(details)), None


def _scalar_value(kind: str, value: object, *, runtime: bool) -> tuple[float, ...]:
    if kind == "bool":
        if runtime and type(value) not in (bool, int):
            raise ValueError("Expected runtime bool")
        if runtime and type(value) is int and value not in (0, 1):
            raise ValueError("Expected runtime bool 0 or 1")
        boolean = parse_hyprlang_bool(value)
        if boolean is None:
            raise ValueError("Unrecognized boolean")
        return (float(boolean),)
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError("Expected numeric value")
        if runtime and (
            type(value) not in (int, float) or (kind == "int" and type(value) is not int)
        ):
            raise ValueError(f"Expected runtime {kind}")
        number = float(value)
        if not math.isfinite(number) or (kind == "int" and not number.is_integer()):
            raise ValueError("Invalid finite number")
        return (number,)
    if kind == "vec2" and runtime:
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(type(n) not in (int, float) for n in value)
        ):
            raise ValueError("Expected runtime vec2 numeric pair")
        numbers = tuple(float(n) for n in value)
        if not all(math.isfinite(n) for n in numbers):
            raise ValueError("Invalid finite vector")
        return numbers
    if not isinstance(value, str):
        raise ValueError(f"Expected {kind} string")
    if kind in ("cssgap", "vec2"):
        numbers = tuple(float(token) for token in value.split())
        if not all(math.isfinite(n) for n in numbers):
            raise ValueError("Invalid finite vector")
        if kind == "vec2" and len(numbers) == 2:
            return numbers
        if kind == "cssgap" and 1 <= len(numbers) <= 4:
            if len(numbers) == 1:
                return numbers * 4
            if len(numbers) == 2:
                return numbers * 2
            if len(numbers) == 3:
                return (*numbers, numbers[1])
            return numbers
        raise ValueError("Invalid vector length")
    if kind == "gradient":
        tokens = (normalize_gradient_string(value) if runtime else value).lower().split()
        angle = 0.0
        if tokens and tokens[-1].endswith("deg"):
            angle = float(tokens.pop()[:-3]) % 360
        if not tokens or not math.isfinite(angle):
            raise ValueError("Invalid gradient")
        colors = []
        for token in tokens:
            if re.fullmatch(r"rgba\([0-9a-f]{8}\)", token):
                rgba = token[5:-1]
                argb = rgba[-2:] + rgba[:-2]
            elif re.fullmatch(r"rgb\([0-9a-f]{6}\)", token):
                argb = "ff" + token[4:-1]
            elif re.fullmatch(r"0x[0-9a-f]{8}", token):
                argb = token[2:]
            elif runtime and re.fullmatch(r"[0-9a-f]{8}", token):
                argb = token
            else:
                raise ValueError("Unrecognized color")
            colors.append(float(int(argb, 16)))
        return (*colors, angle)
    raise ValueError(f"Unsupported option type: {kind}")


def _drift_check(document: Document | None, output: HealthCheck) -> HealthCheck:
    details = [
        "Saved scalar options only; monitor, animation definitions and bezier coverage excluded. "
        "Equality does not establish that this file was loaded."
    ]
    if document is None:
        return HealthCheck(
            "drift",
            _TITLES["drift"],
            "unavailable",
            "Saved owned data unavailable",
            (output.summary,),
        )
    values = {line.full_key: line.value for line in document.lines if isinstance(line, Assignment)}
    matching = differing = unknown = attempted = 0
    budget_exhausted = False
    unavailable = None
    try:
        executable = (
            shutil.which("hyprctl") if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") else None
        )
        if executable is None:
            unavailable = "No Hyprland session or hyprctl unavailable"
    except (OSError, ValueError) as exc:
        executable = None
        unavailable = str(exc)
    deadline = time.monotonic() + _DRIFT_SECONDS
    fields = {"cssgap": "css"}
    for key, saved in sorted(values.items()):
        runtime: object = "not observed"
        try:
            option = OPTIONS_BY_KEY.get(key)
            if (
                not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*(?::[A-Za-z_][A-Za-z0-9_.]*)+", key)
                or not (key in GENERAL_OPTIONS or key.startswith(("decoration:", "animations:")))
                or option is None
            ):
                raise ValueError("Unsupported or unsafe option key; not queried")
            kind = option.type
            if kind not in ("int", "float", "bool", "cssgap", "vec2", "gradient"):
                raise ValueError(f"Unsupported option type: {kind}; not queried")
            expected = _scalar_value(kind, saved, runtime=False)
            if unavailable is not None:
                raise ValueError(unavailable)
            remaining = deadline - time.monotonic()
            if remaining <= 0 or attempted >= _MAX_DRIFT_QUERIES:
                budget_exhausted = True
                raise ValueError(
                    "Partial observation: drift time/query budget exhausted; not queried"
                )
            attempted += 1
            result = run_bounded(
                [str(executable), "-j", "getoption", key],
                timeout=min(2.0, remaining),
                max_bytes=_MAX_QUERY_BYTES,
            )
            if result.returncode:
                raise ValueError(f"getoption exited with status {result.returncode}")
            data = json.loads(result.stdout)
            if (
                not isinstance(data, dict)
                or data.get("option") != key
                or data.get("set") is not True
            ):
                raise ValueError("Missing/mismatched option identity or set:true")
            field = fields.get(kind, kind)
            if field not in data:
                raise ValueError(f"Missing runtime {field} field")
            runtime = data[field]
            actual = _scalar_value(kind, runtime, runtime=True)
            equal = len(expected) == len(actual) and all(
                math.isclose(a, b, rel_tol=0, abs_tol=1e-6)
                for a, b in zip(expected, actual, strict=True)
            )
            if equal:
                matching += 1
                comparison = "matching"
            else:
                differing += 1
                comparison = "differing"
        except (OSError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
            unknown += 1
            comparison = f"unknown ({exc})"
        except subprocess.TimeoutExpired:
            unknown += 1
            comparison = "unknown (getoption timed out; partial observation)"
        details.append(f"{key}: saved={saved!r}; runtime={runtime!r}; {comparison}")
    status: HealthStatus = "unknown"
    if unavailable is not None and values:
        status = "unavailable"
    elif matching and not differing and not unknown:
        status = "available"
    summary = f"{matching} matching, {differing} differing, {unknown} unknown saved scalar options"
    if not values:
        summary += "; no saved scalar comparisons"
    if budget_exhausted:
        summary += "; partial observation (time/query budget exhausted)"
    return HealthCheck("drift", _TITLES["drift"], status, summary, tuple(details))


def _validator_check() -> HealthCheck:
    try:
        executable = shutil.which("luac") or shutil.which("lua")
        return HealthCheck(
            "validator",
            _TITLES["validator"],
            "available" if executable else "unavailable",
            "Lua validator found (not invoked)"
            if executable
            else "Neither luac nor lua found on PATH",
            (executable,) if executable else (),
        )
    except (OSError, ValueError) as exc:
        return HealthCheck("validator", _TITLES["validator"], "failed", str(exc))


def _backups_check() -> HealthCheck:
    path = (
        Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        / "attune"
        / "backups"
    )
    details = (
        f"Backup directory: {path}",
        "Candidates are not verified or established as restorable",
    )
    try:
        count = 0
        with os.scandir(path) as entries:
            for index, entry in enumerate(entries):
                if index >= _MAX_BACKUP_ENTRIES:
                    return HealthCheck(
                        "backups",
                        _TITLES["backups"],
                        "unknown",
                        f"At least {count} backup candidates; "
                        f"scan truncated at {_MAX_BACKUP_ENTRIES} entries",
                        details,
                    )
                if re.fullmatch(r"[0-9a-f]{64}\.lua", entry.name) and entry.is_file(
                    follow_symlinks=False
                ):
                    count += 1
        return HealthCheck(
            "backups",
            _TITLES["backups"],
            "available" if count else "unavailable",
            f"{count} regular hash-named backup candidates",
            details,
        )
    except FileNotFoundError:
        return HealthCheck(
            "backups", _TITLES["backups"], "unavailable", "Backup directory is missing", details
        )
    except (OSError, ValueError) as exc:
        return HealthCheck("backups", _TITLES["backups"], "failed", str(exc), details)


def collect_snapshot(output_path: Path | None = None) -> HealthSnapshot:
    """Observe only the dedicated output and allowlisted compositor queries. No writes."""
    checks = _ipc_checks()
    output, document = _output_check(
        output_path if output_path is not None else config.managed_path()
    )
    checks.append(output)
    checks.extend((_validator_check(), _backups_check()))
    checks.append(_drift_check(document, output))
    return HealthSnapshot(datetime.now(UTC).isoformat(), tuple(map(_bounded_check, checks)))


def run_snapshot(
    output_path: Path,
    timeout: float = 10,
    *,
    cancel_event: threading.Event | None = None,
) -> HealthSnapshot:
    """Supervise bounded capture and cleanup of the collector's entire process group."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Health timeout must be finite and positive")
    result = run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.health",
            "--output",
            str(output_path.absolute()),
        ],
        cwd=Path(__file__).absolute().parents[2],
        timeout=timeout,
        max_bytes=_MAX_JSON_BYTES,
        process_group=True,
        cancel_event=cancel_event,
    )
    if result.returncode:
        raise ValueError(f"Health collector exited with status {result.returncode}")
    return HealthSnapshot.from_json(result.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only Health collector")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(collect_snapshot(args.output).to_json())
