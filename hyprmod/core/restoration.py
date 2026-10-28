"""Reviewed disk restoration. The disposable worker can only prepare, never commit."""

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from hyprmod.core import config, health, persistence
from hyprmod.core.focused_ui import ReviewSnapshot

MAX_INPUT_BYTES = 256 * 1024
MAX_DIFF_BYTES = 256 * 1024
MAX_DIFF_LINES = 4000
MAX_INPUT_LINES = 10000
MAX_JSON_BYTES = 5 * 1024 * 1024
_NAME = re.compile(r"[0-9a-f]{64}\.lua")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _directory() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "attune/backups"


def _resolved_root() -> Path:
    try:
        return _directory().resolve(strict=True)
    except RuntimeError as exc:
        raise ValueError("Cyclic backup directory symlink") from exc


def _canonical(text: str) -> None:
    if not text or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Restoration requires nonempty output of at most 256 KiB per side")
    if len(text.splitlines()) > MAX_INPUT_LINES:
        raise ValueError("Restoration input exceeds 10000 lines")
    persistence.read_document(text)


def review_diff(previous: str, proposed: str, name: str) -> tuple[str, int, int]:
    sides = previous.splitlines(keepends=True), proposed.splitlines(keepends=True)
    added = removed = 0
    for tag, i, j, k, end in difflib.SequenceMatcher(None, *sides).get_opcodes():
        if tag in ("insert", "replace"):
            added += end - k
        if tag in ("delete", "replace"):
            removed += j - i
    chunks = []
    size = lines = 0
    for line in difflib.unified_diff(*sides, fromfile="current/attune.lua", tofile=name):
        rendered = line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
        size += len(rendered.encode("utf-8"))
        lines += len(rendered.splitlines())
        if size > MAX_DIFF_BYTES or lines > MAX_DIFF_LINES:
            raise ValueError("Complete restoration diff exceeds 256 KiB or 4000 lines; refused")
        chunks.append(rendered)
    return "".join(chunks), added, removed


@dataclass(frozen=True)
class RestoreDraft:
    lexical_path: str
    resolved_path: str
    backup_root: str
    backup_name: str
    previous_text: str
    proposed_text: str
    previous_sha256: str
    proposed_sha256: str
    diff: str
    added_lines: int
    removed_lines: int
    observed_at: str

    def to_json(self) -> str:
        text = json.dumps(asdict(self), ensure_ascii=True, allow_nan=False)
        if len(text.encode()) > MAX_JSON_BYTES:
            raise ValueError("Restoration protocol exceeds limit")
        return text

    @classmethod
    def from_json(cls, text: str) -> "RestoreDraft":
        if len(text.encode("utf-8")) > MAX_JSON_BYTES:
            raise ValueError("Restoration protocol exceeds limit")

        def unique(pairs):
            data = {}
            for key, value in pairs:
                if key in data:
                    raise ValueError("Duplicate restoration field")
                data[key] = value
            return data

        try:
            data = json.loads(text, object_pairs_hook=unique)
        except RecursionError as exc:
            raise ValueError("Restoration protocol too deeply nested") from exc
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid restoration fields")
        draft = cls(**data)
        _validate_draft(draft)
        return draft


def _validate_draft(draft: RestoreDraft) -> None:
    for key in RestoreDraft.__dataclass_fields__:
        value = getattr(draft, key)
        if key in ("added_lines", "removed_lines"):
            if type(value) is not int or not 0 <= value <= MAX_INPUT_LINES:
                raise ValueError("Invalid restoration counts")
        elif not isinstance(value, str):
            raise ValueError("Invalid restoration text")
    if len(draft.diff.encode()) > MAX_DIFF_BYTES or len(draft.diff.splitlines()) > MAX_DIFF_LINES:
        raise ValueError("Restoration review exceeds limits")
    for value in (draft.lexical_path, draft.resolved_path, draft.backup_root):
        if len(value.encode()) > 4096 or not Path(value).is_absolute():
            raise ValueError("Restoration requires bounded absolute paths")
    if not _NAME.fullmatch(draft.backup_name):
        raise ValueError("Expected SHA256 backup basename")
    if len(draft.observed_at) > 64 or "T" not in draft.observed_at:
        raise ValueError("Invalid restoration observation time")
    if datetime.fromisoformat(draft.observed_at).utcoffset() != timedelta(0):
        raise ValueError("Restoration observation time must be UTC")
    for text in (draft.previous_text, draft.proposed_text):
        _canonical(text)
    if (
        _digest(draft.previous_text) != draft.previous_sha256
        or _digest(draft.proposed_text) != draft.proposed_sha256
        or draft.backup_name != draft.proposed_sha256 + ".lua"
    ):
        raise ValueError("Restoration content identity mismatch")
    if review_diff(draft.previous_text, draft.proposed_text, draft.backup_name) != (
        draft.diff,
        draft.added_lines,
        draft.removed_lines,
    ):
        raise ValueError("Restoration review is not the complete exact diff")


def _read_bound(draft: RestoreDraft) -> None:
    root = _resolved_root()
    if str(root) != draft.backup_root:
        raise ValueError("Backup root changed since review")
    raw = persistence.read_stable(root / draft.backup_name, limit=MAX_INPUT_BYTES)
    if (
        raw != draft.proposed_text.encode()
        or hashlib.sha256(raw).hexdigest() + ".lua" != draft.backup_name
    ):
        raise ValueError("Selected backup changed since review")
    target = persistence.resolve_target(Path(draft.lexical_path))
    if str(target) != draft.resolved_path:
        raise ValueError("Destination changed since review")
    if persistence.read_stable(target, limit=MAX_INPUT_BYTES) != draft.previous_text.encode():
        raise ValueError("Current output changed since review")
    if persistence.resolve_target(Path(draft.lexical_path)) != target:
        raise ValueError("Destination changed during read")
    if _resolved_root() != root:
        raise ValueError("Backup root changed during read")


def prepare_restore(output_path: Path, backup_name: str) -> RestoreDraft:
    """Read-only collector; GUI callers should use the supervised run_prepare instead."""
    if not _NAME.fullmatch(backup_name):
        raise ValueError("Expected SHA256 backup basename")
    path = output_path.absolute()
    target = persistence.resolve_target(path)
    root = _resolved_root()
    previous = persistence.read_stable(target, limit=MAX_INPUT_BYTES).decode("utf-8")
    proposed = persistence.read_stable(root / backup_name, limit=MAX_INPUT_BYTES).decode("utf-8")
    for text in (previous, proposed):
        _canonical(text)
        persistence.validate_lua(text)
    diff, added, removed = review_diff(previous, proposed, backup_name)
    draft = RestoreDraft(
        str(path),
        str(target),
        str(root),
        backup_name,
        previous,
        proposed,
        _digest(previous),
        _digest(proposed),
        diff,
        added,
        removed,
        datetime.now(UTC).isoformat(),
    )
    _validate_draft(draft)
    _read_bound(draft)
    return draft


def run_prepare(
    output_path: Path,
    backup_name: str,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> RestoreDraft:
    if not _NAME.fullmatch(backup_name):
        raise ValueError("Expected SHA256 backup basename")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Restoration timeout must be finite and positive")
    result = health.run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.restoration",
            "--output",
            str(output_path.absolute()),
            "prepare",
            backup_name,
        ],
        cwd=Path(__file__).absolute().parents[2],
        timeout=timeout,
        max_bytes=MAX_JSON_BYTES,
        process_group=True,
        cancel_event=cancel_event,
    )
    if result.returncode:
        raise ValueError(f"Restoration preparation failed: {result.stderr[-2048:]}")
    draft = RestoreDraft.from_json(result.stdout)
    if draft.lexical_path != str(output_path.absolute()) or draft.backup_name != backup_name:
        raise ValueError("Restoration worker returned a different selection")
    return draft


@dataclass(frozen=True)
class RestoreResult:
    status: Literal["restored", "unchanged"]
    resolved_path: Path
    backup_path: Path | None


class RestoreFailure(ValueError):
    def __init__(self, message: str, *, may_have_written: bool = False):
        super().__init__(message)
        self.may_have_written = may_have_written


def commit_restore(
    draft: RestoreDraft, *, cancel_event: threading.Event | None = None
) -> RestoreResult:
    """Call directly on a non-daemon worker, never a timeout-killed subprocess.

    This writes watched disk output; an external compositor may auto-reload it.
    """
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Restoration cancelled before replacement")
        _validate_draft(draft)
        _read_bound(draft)
        backup = persistence.persist_snapshot(
            ReviewSnapshot(
                Path(draft.lexical_path),
                draft.previous_text,
                draft.proposed_text,
                Path(draft.resolved_path),
            ),
            expected_source=lambda: _read_bound(draft),
            cancel_event=cancel_event,
        )
    except (OSError, ValueError, RecursionError) as exc:
        uncertain = isinstance(exc, persistence.PersistenceFailure) and exc.may_have_written
        if uncertain:
            config.invalidate_cache()
        raise RestoreFailure(
            str(exc),
            may_have_written=uncertain,
        ) from exc
    # Recovery can retry editor construction in this process without a full restart.
    config.invalidate_cache()
    return RestoreResult(
        "unchanged" if draft.previous_text == draft.proposed_text else "restored",
        Path(draft.resolved_path),
        backup,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only restoration preparation")
    parser.add_argument("--output", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare").add_argument("backup_name")
    args = parser.parse_args()
    print(prepare_restore(args.output, args.backup_name).to_json())
