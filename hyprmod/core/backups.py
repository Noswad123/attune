"""Read-only, hash-addressed backup inspection. No Lua evaluation or restoration."""

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import stat
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from itertools import islice
from pathlib import Path
from typing import Literal

from hyprland_config import Assignment, Document, Keyword

from hyprmod.core import health, persistence

MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * MAX_FILE_BYTES
MAX_ENTRIES = 1000
MAX_CANDIDATES = 64
MAX_COMPARE_BYTES = 256 * 1024
MAX_COMPARE_LINES = 10000
MAX_DIFF_BYTES = 256 * 1024
MAX_DIFF_LINES = 4000
MAX_LINE_BYTES = 4096
MAX_JSON_BYTES = 2 * 1024 * 1024
_NAME = re.compile(r"[0-9a-f]{64}\.lua")
_HASH = re.compile(r"[0-9a-f]{64}")
_ERRORS = (OSError, ValueError, UnicodeError, RecursionError)


@dataclass(frozen=True)
class BackupSummary:
    scalars: int
    monitors: int
    animations: int
    beziers: int


@dataclass(frozen=True)
class BackupInfo:
    name: str
    status: Literal["valid", "invalid", "unavailable"]
    detail: str
    size_bytes: int | None = None
    modified_ns: int | None = None
    sha256: str | None = None
    summary: BackupSummary | None = None


@dataclass(frozen=True)
class CurrentOutput:
    lexical_path: str
    resolved_path: str | None
    status: Literal["owned", "foreign", "invalid", "missing", "unavailable"]
    detail: str
    size_bytes: int | None = None
    modified_ns: int | None = None
    sha256: str | None = None
    summary: BackupSummary | None = None


@dataclass(frozen=True)
class BackupListing:
    observed_at: str
    directory: str
    status: Literal["available", "partial", "unavailable"]
    backups: tuple[BackupInfo, ...]
    notes: tuple[str, ...]

    def to_json(self) -> str:
        text = json.dumps(asdict(self), ensure_ascii=True, allow_nan=False)
        self.from_json(text)
        return text

    @classmethod
    def from_json(cls, text: str) -> "BackupListing":
        data = _envelope(text, {"observed_at", "directory", "status", "backups", "notes"})
        records = data["backups"]
        if not isinstance(records, list) or len(records) > MAX_CANDIDATES:
            raise ValueError("Invalid backup rows")
        rows = tuple(_backup(record) for record in records)
        names = [row.name for row in rows]
        if names != sorted(set(names)):
            raise ValueError("Backup rows must have unique hash-name ordering")
        return cls(
            _stamp(data["observed_at"]),
            _text(data["directory"], 4096),
            _choice(data["status"], ("available", "partial", "unavailable")),
            rows,
            _notes(data["notes"]),
        )


@dataclass(frozen=True)
class BackupComparison:
    observed_at: str
    backup: BackupInfo
    current: CurrentOutput
    status: Literal["compared", "too_large", "error"]
    diff: str
    added_lines: int | None
    removed_lines: int | None
    truncated: bool
    notes: tuple[str, ...]

    def to_json(self) -> str:
        text = json.dumps(asdict(self), ensure_ascii=True, allow_nan=False)
        self.from_json(text)
        return text

    @classmethod
    def from_json(cls, text: str) -> "BackupComparison":
        data = _envelope(text, set(cls.__dataclass_fields__))
        current = _record(data["current"], set(CurrentOutput.__dataclass_fields__))
        output = CurrentOutput(
            _text(current["lexical_path"], 4096),
            None if current["resolved_path"] is None else _text(current["resolved_path"], 4096),
            _choice(current["status"], ("owned", "foreign", "invalid", "missing", "unavailable")),
            _text(current["detail"]),
            *_evidence(current),
        )
        status: Literal["compared", "too_large", "error"] = _choice(
            data["status"], ("compared", "too_large", "error")
        )
        diff = _text(data["diff"], MAX_DIFF_BYTES)
        if len(diff.splitlines()) > MAX_DIFF_LINES or any(
            len(line.encode("utf-8")) > MAX_LINE_BYTES for line in diff.splitlines()
        ):
            raise ValueError("Diff exceeds rendering limits")
        added, removed = (
            _integer(data[key], MAX_COMPARE_LINES) for key in ("added_lines", "removed_lines")
        )
        if type(data["truncated"]) is not bool:
            raise ValueError("Invalid truncation flag")
        backup = _backup(data["backup"])
        if output.status in ("owned", "foreign", "invalid") and (
            output.sha256 is None
            or output.size_bytes is None
            or output.size_bytes > MAX_FILE_BYTES
            or output.modified_ns is None
        ):
            raise ValueError("Readable output requires stable read evidence")
        if (output.summary is not None) != (output.status == "owned"):
            raise ValueError("Only owned output has a canonical summary")
        if output.status == "missing" and any(
            item is not None
            for item in (output.size_bytes, output.modified_ns, output.sha256, output.summary)
        ):
            raise ValueError("Missing output must not claim read evidence")
        if status in ("compared", "too_large"):
            if backup.status != "valid" or output.status == "unavailable":
                raise ValueError("Comparison requires readable evidence")
        if status == "compared":
            if added is None or removed is None:
                raise ValueError("Comparison requires line counts")
            if not diff and (added or removed) and not data["truncated"]:
                raise ValueError("Changed comparison requires diff or truncation evidence")
        elif diff or added is not None or removed is not None or data["truncated"]:
            raise ValueError("Uncomputed comparison must not claim diff results")
        return cls(
            _stamp(data["observed_at"]),
            backup,
            output,
            status,
            diff,
            added,
            removed,
            data["truncated"],
            _notes(data["notes"]),
        )


def _record(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Invalid backup protocol fields")
    return value


def _envelope(text: str, keys: set[str]) -> dict:
    if len(text) > MAX_JSON_BYTES or len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("Backup response exceeds size limit")

    def unique(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate protocol field")
            result[key] = value
        return result

    try:
        return _record(json.loads(text, object_pairs_hook=unique), keys)
    except RecursionError as exc:
        raise ValueError("Backup response is too deeply nested") from exc


def _text(value: object, limit: int = 1024) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
        raise ValueError("Invalid or oversized protocol text")
    return value


def _choice[T: str](value: object, choices: tuple[T, ...]) -> T:
    for choice in choices:
        if type(value) is str and value == choice:
            return choice
    raise ValueError("Invalid protocol status")


def _integer(value: object, maximum: int, minimum: int = 0) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid protocol integer")
    return value


def _stamp(value: object) -> str:
    text = _text(value, 64)
    if "T" not in text or datetime.fromisoformat(text).utcoffset() != timedelta(0):
        raise ValueError("Observation time must be ISO8601 UTC")
    return text


def _notes(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError("Invalid protocol notes")
    return tuple(_text(note) for note in value)


def _evidence(data: dict) -> tuple[int | None, int | None, str | None, BackupSummary | None]:
    size = _integer(data["size_bytes"], 2**63 - 1)
    modified = _integer(data["modified_ns"], 2**63 - 1, -(2**63))
    digest = data["sha256"]
    if digest is not None and (not isinstance(digest, str) or not _HASH.fullmatch(digest)):
        raise ValueError("Invalid content identity")
    summary = data["summary"]
    if summary is not None:
        record = _record(summary, set(BackupSummary.__dataclass_fields__))
        counts = [
            _integer(record[key], MAX_FILE_BYTES) for key in BackupSummary.__dataclass_fields__
        ]
        if any(count is None for count in counts):
            raise ValueError("Missing summary count")
        summary = BackupSummary(**record)
    return size, modified, digest, summary


def _backup(value: object) -> BackupInfo:
    data = _record(value, set(BackupInfo.__dataclass_fields__))
    name = _text(data["name"], 68)
    _validate_name(name)
    info = BackupInfo(
        name,
        _choice(data["status"], ("valid", "invalid", "unavailable")),
        _text(data["detail"]),
        *_evidence(data),
    )
    if info.status == "valid" and (
        info.sha256 != name[:-4]
        or info.summary is None
        or info.size_bytes is None
        or info.size_bytes > MAX_FILE_BYTES
        or info.modified_ns is None
    ):
        raise ValueError("Valid backup requires canonical hash evidence")
    if info.status != "valid" and info.summary is not None:
        raise ValueError("Unverified backup must not claim a canonical summary")
    return info


def _validate_name(name: str) -> None:
    if not _NAME.fullmatch(name):
        raise ValueError("Expected a lowercase SHA256 backup basename: HASH.lua")


def _directory() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "attune/backups"


def _summary(document: Document) -> BackupSummary:
    return BackupSummary(
        sum(isinstance(line, Assignment) for line in document.lines),
        *(
            sum(isinstance(line, Keyword) and line.key == key for line in document.lines)
            for key in ("monitor", "animation", "bezier")
        ),
    )


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
        info.st_nlink,
    )


def _read(root: int, name: str) -> tuple[bytes, os.stat_result]:
    before = os.stat(name, dir_fd=root, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("Refusing symlink, hardlink or non-regular file")
    if before.st_size > MAX_FILE_BYTES:
        raise ValueError("File exceeds 1 MiB inspection limit")
    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=root)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _signature(opened) != _signature(before):
            raise ValueError("File changed before inspection")
        raw = stream.read(MAX_FILE_BYTES)
        after = os.fstat(stream.fileno())
    if len(raw) != opened.st_size:
        raise ValueError("File exceeds limit or changed size during inspection")
    if _signature(opened) != _signature(after) or _signature(
        os.stat(name, dir_fd=root, follow_symlinks=False)
    ) != _signature(after):
        raise ValueError("File changed during inspection")
    return raw, after


def _decode(raw: bytes) -> str:
    text = raw.decode("utf-8")
    if any((ord(c) < 32 and c not in "\t\r\n") or 127 <= ord(c) <= 159 for c in text):
        raise ValueError("Binary/control characters are not inspectable UTF-8 text")
    return text


def _detail(value: object) -> str:
    return (
        str(value)
        .encode("utf-8", errors="backslashreplace")[:1024]
        .decode("utf-8", errors="ignore")
    )


def _inspect_backup(root: int, name: str) -> tuple[BackupInfo, str | None, int]:
    raw = None
    info = None
    digest = None
    try:
        info = os.stat(name, dir_fd=root, follow_symlinks=False)
        raw, info = _read(root, name)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != name[:-4]:
            raise ValueError("Content SHA256 does not match backup basename")
        text = _decode(raw)
        if not text:
            raise ValueError("Empty backup is not canonical Attune output")
        summary = _summary(persistence.read_document(text))
        return (
            BackupInfo(
                name,
                "valid",
                "Hash and canonical ownership verified; not runtime-validated",
                len(raw),
                info.st_mtime_ns,
                digest,
                summary,
            ),
            text,
            len(raw),
        )
    except _ERRORS as exc:
        status = "unavailable" if isinstance(exc, OSError) else "invalid"
        return (
            BackupInfo(
                name,
                status,
                _detail(exc),
                info.st_size if info is not None else None,
                info.st_mtime_ns if info is not None else None,
                digest,
            ),
            None,
            len(raw) if raw is not None else MAX_FILE_BYTES,
        )


def collect_list(output_path: Path, *, backup_dir: Path | None = None) -> BackupListing:
    """Inspect hash-name order, not save history. backup_dir is a pure-test seam only."""
    directory = backup_dir if backup_dir is not None else _directory()
    notes = [
        "Hash-name ordering is not save history. Filesystem modified time is not last-save time.",
        "Rejected-entry metadata is descriptive; SHA256 requires a stable content read.",
    ]
    rows = []
    status: Literal["available", "partial", "unavailable"] = "available"
    try:
        root = os.open(directory.resolve(strict=True), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with os.scandir(root) as entries:
                names = [entry.name for entry in islice(entries, MAX_ENTRIES)]
            if len(names) == MAX_ENTRIES:
                notes.append(
                    "Directory scan capped at 1000 entries; further entries may be omitted."
                )
                status = "partial"
            candidates = sorted(name for name in names if _NAME.fullmatch(name))
            if len(candidates) > MAX_CANDIDATES:
                notes.append(
                    f"{len(candidates) - MAX_CANDIDATES} hash-named candidates omitted (64 cap)."
                )
                status = "partial"
            consumed = 0
            for name in candidates[:MAX_CANDIDATES]:
                # Reserve a full read so changed/invalid files cannot exceed the total budget.
                if consumed + MAX_FILE_BYTES > MAX_TOTAL_BYTES:
                    rows.append(
                        BackupInfo(name, "unavailable", "Omitted: 16 MiB read budget exhausted")
                    )
                    status = "partial"
                    continue
                row, _, used = _inspect_backup(root, name)
                consumed += used
                rows.append(row)
                if row.status != "valid":
                    status = "partial"
            if any("budget" in row.detail for row in rows):
                notes.append("Some candidates omitted after the total read budget was exhausted.")
        finally:
            os.close(root)
    except _ERRORS as exc:
        status = "unavailable"
        notes.append(_detail(f"Backup directory unavailable: {exc}"))
    return BackupListing(
        datetime.now(UTC).isoformat(), str(directory.absolute()), status, tuple(rows), tuple(notes)
    )


def _current(path: Path) -> tuple[CurrentOutput, str | None]:
    lexical = str(path.absolute())
    target = None
    try:
        target = persistence.resolve_target(path)
        root = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                os.stat(target.name, dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                if persistence.resolve_target(path) != target or target.exists():
                    raise ValueError("Output changed during missing-file inspection") from None
                return CurrentOutput(
                    lexical, str(target), "missing", "Missing output; comparing to empty"
                ), ""
            raw, info = _read(root, target.name)
        finally:
            os.close(root)
        if persistence.resolve_target(path) != target or _signature(target.stat()) != _signature(
            info
        ):
            raise ValueError("Output destination changed during inspection")
        digest = hashlib.sha256(raw).hexdigest()
        try:
            text = _decode(raw)
        except _ERRORS as exc:
            return CurrentOutput(
                lexical,
                str(target),
                "unavailable",
                _detail(exc),
                len(raw),
                info.st_mtime_ns,
                digest,
            ), None
        summary = None
        status: Literal["owned", "foreign", "invalid"] = "foreign"
        detail = "Foreign output; raw UTF-8 comparison only, not safe to overwrite"
        if text.startswith(persistence.MARKER):
            try:
                summary = _summary(persistence.read_document(text))
                status = "owned"
                detail = "Canonical ownership verified; runtime loading is not established"
            except _ERRORS as exc:
                status = "invalid"
                detail = _detail(f"Invalid Attune output; raw UTF-8 comparison only: {exc}")
        return CurrentOutput(
            lexical, str(target), status, detail, len(raw), info.st_mtime_ns, digest, summary
        ), text
    except _ERRORS as exc:
        return CurrentOutput(
            lexical, str(target) if target else None, "unavailable", _detail(exc)
        ), None


def collect_compare(
    output_path: Path,
    backup_name: str,
    *,
    backup_dir: Path | None = None,
) -> BackupComparison:
    """Compute backup-to-current diff in the collector, never in a GTK callback."""
    _validate_name(backup_name)
    directory = backup_dir if backup_dir is not None else _directory()
    try:
        root = os.open(directory.resolve(strict=True), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            backup, saved, _ = _inspect_backup(root, backup_name)
        finally:
            os.close(root)
    except _ERRORS as exc:
        backup = BackupInfo(backup_name, "unavailable", _detail(exc))
        saved = None
    current, text = _current(output_path)
    observed = datetime.now(UTC).isoformat()
    notes = [
        "Direction: backup -> current. Modified times are filesystem metadata, not save history.",
        "Evidence covers independent stable reads, not an atomic pair or live state.",
    ]
    if saved is None or text is None:
        notes.append("Comparison unavailable; inspect backup and current details.")
        return BackupComparison(
            observed, backup, current, "error", "", None, None, False, tuple(notes)
        )
    sides = [saved.splitlines(keepends=True), text.splitlines(keepends=True)]
    if any(len(side.encode("utf-8")) > MAX_COMPARE_BYTES for side in (saved, text)) or any(
        len(lines) > MAX_COMPARE_LINES for lines in sides
    ):
        notes.append(
            "Comparison too large: maximum 256 KiB and 10000 lines per side. No diff computed."
        )
        return BackupComparison(
            observed, backup, current, "too_large", "", None, None, False, tuple(notes)
        )
    added = removed = 0
    chunks = []
    used = lines_used = 0
    truncated = False
    # autojunk bounds repetitive input; the supervised child's deadline bounds CPU work.
    matcher = difflib.SequenceMatcher(None, sides[0], sides[1])
    for tag, i, j, k, end in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            added += end - k
        if tag in ("delete", "replace"):
            removed += j - i
    for line in difflib.unified_diff(
        sides[0], sides[1], fromfile=backup_name, tofile="current/attune.lua"
    ):
        rendered = line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
        size = len(rendered.encode("utf-8"))
        count = len(rendered.splitlines())
        if (
            size > MAX_LINE_BYTES
            or used + size > MAX_DIFF_BYTES
            or lines_used + count > MAX_DIFF_LINES
        ):
            truncated = True
            break
        chunks.append(rendered)
        used += size
        lines_used += count
    if truncated:
        notes.append(
            "Diff truncated at byte, line or 4096-byte row limit; counts cover the full inputs."
        )
    return BackupComparison(
        observed,
        backup,
        current,
        "compared",
        "".join(chunks),
        added,
        removed,
        truncated,
        tuple(notes),
    )


def _worker(
    output_path: Path, operation: list[str], cancel_event: threading.Event | None, timeout: float
) -> str:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Backup timeout must be finite and positive")
    result = health.run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.backups",
            "--output",
            str(output_path.absolute()),
            *operation,
        ],
        cwd=Path(__file__).absolute().parents[2],
        timeout=timeout,
        max_bytes=MAX_JSON_BYTES,
        process_group=True,
        cancel_event=cancel_event,
    )
    if result.returncode:
        raise ValueError(f"Backup collector exited with status {result.returncode}")
    return result.stdout


def run_list(
    output_path: Path, *, cancel_event: threading.Event | None = None, timeout: float = 10
) -> BackupListing:
    return BackupListing.from_json(_worker(output_path, ["list"], cancel_event, timeout))


def run_compare(
    output_path: Path,
    backup_name: str,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 10,
) -> BackupComparison:
    _validate_name(backup_name)
    result = BackupComparison.from_json(
        _worker(output_path, ["compare", backup_name], cancel_event, timeout)
    )
    if result.backup.name != backup_name:
        raise ValueError("Backup worker returned a different content identity")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only backup collector")
    parser.add_argument("--output", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    commands.add_parser("compare").add_argument("backup_name")
    args = parser.parse_args()
    if args.command == "list":
        print(collect_list(args.output).to_json())
    else:
        print(collect_compare(args.output, args.backup_name).to_json())
