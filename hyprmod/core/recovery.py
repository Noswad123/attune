"""Explicit preservation-first text recovery. The child worker is read-only."""

import argparse
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

from hyprmod.core import config, health, persistence, restoration
from hyprmod.core.focused_ui import ReviewSnapshot

MAX_INPUT_BYTES = restoration.MAX_INPUT_BYTES
MAX_INPUT_LINES = restoration.MAX_INPUT_LINES
MAX_JSON_BYTES = restoration.MAX_JSON_BYTES
_NAME = re.compile(r"[0-9a-f]{64}\.lua")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text(text: str) -> None:
    if not text or len(text.encode()) > MAX_INPUT_BYTES:
        raise ValueError("Recovery requires nonempty text of at most 256 KiB per side")
    if len(text.splitlines()) > MAX_INPUT_LINES:
        raise ValueError("Recovery input exceeds 10000 lines")
    if any((ord(c) < 32 and c not in "\t\r\n") or 127 <= ord(c) <= 159 for c in text):
        raise ValueError("Binary/control characters are not recoverable UTF-8 text")


def _status(text: str) -> Literal["foreign", "invalid"]:
    _text(text)
    try:
        persistence.read_document(text)
    except (ValueError, RecursionError):
        return "invalid" if text.startswith(persistence.MARKER) else "foreign"
    raise ValueError("Owned output requires ordinary restoration instead")


def _backup_root() -> Path:
    root = (
        Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "attune/backups"
    ).resolve(strict=True)
    for parent in (root, *root.parents):
        if (parent / ".git").exists():
            raise ValueError("Recovery backup storage must be outside Git")
    return root


@dataclass(frozen=True)
class RecoveryDraft:
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
    current_status: Literal["foreign", "invalid"]
    preservation_path: str
    preservation_root: str

    def to_json(self) -> str:
        _validate(self)
        text = json.dumps(asdict(self), ensure_ascii=True, allow_nan=False)
        if len(text.encode()) > MAX_JSON_BYTES:
            raise ValueError("Recovery protocol exceeds limit")
        return text

    @classmethod
    def from_json(cls, text: str) -> "RecoveryDraft":
        if len(text.encode()) > MAX_JSON_BYTES:
            raise ValueError("Recovery protocol exceeds limit")

        def unique(pairs):
            data = {}
            for key, value in pairs:
                if key in data:
                    raise ValueError("Duplicate recovery field")
                data[key] = value
            return data

        try:
            data = json.loads(text, object_pairs_hook=unique)
        except RecursionError as exc:
            raise ValueError("Recovery protocol too deeply nested") from exc
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid recovery fields")
        draft = cls(**data)
        _validate(draft)
        return draft


def _validate(draft: RecoveryDraft) -> None:
    for key in RecoveryDraft.__dataclass_fields__:
        value = getattr(draft, key)
        if key in ("added_lines", "removed_lines"):
            if type(value) is not int or not 0 <= value <= MAX_INPUT_LINES:
                raise ValueError("Invalid recovery counts")
        elif not isinstance(value, str):
            raise ValueError("Invalid recovery text")
    for key in (
        "lexical_path",
        "resolved_path",
        "backup_root",
        "preservation_root",
        "preservation_path",
    ):
        value = getattr(draft, key)
        if len(value.encode()) > 4096 or "\0" in value or not Path(value).is_absolute():
            raise ValueError("Recovery requires bounded absolute paths")
    if not _NAME.fullmatch(draft.backup_name):
        raise ValueError("Expected SHA256 backup basename")
    if (
        len(draft.observed_at) > 64
        or "T" not in draft.observed_at
        or datetime.fromisoformat(draft.observed_at).utcoffset() != timedelta(0)
    ):
        raise ValueError("Recovery observation time must be UTC")
    if _status(draft.previous_text) != draft.current_status:
        raise ValueError("Recovery status mismatch")
    _text(draft.proposed_text)
    persistence.read_document(draft.proposed_text)
    if (
        _digest(draft.previous_text) != draft.previous_sha256
        or _digest(draft.proposed_text) != draft.proposed_sha256
        or draft.backup_name != draft.proposed_sha256 + ".lua"
        or draft.preservation_path
        != str(Path(draft.preservation_root) / (draft.previous_sha256 + ".bin"))
    ):
        raise ValueError("Recovery content identity or preservation destination mismatch")
    if restoration.review_diff(draft.previous_text, draft.proposed_text, draft.backup_name) != (
        draft.diff,
        draft.added_lines,
        draft.removed_lines,
    ):
        raise ValueError("Recovery review is not the complete exact diff")


def _read_bound(draft: RecoveryDraft) -> None:
    if str(persistence.recovery_root()) != draft.preservation_root:
        raise ValueError("Preservation root changed since review")
    root = _backup_root()
    if str(root) != draft.backup_root:
        raise ValueError("Backup root changed since review")
    raw = persistence.read_stable(root / draft.backup_name, limit=MAX_INPUT_BYTES)
    if (
        raw != draft.proposed_text.encode()
        or hashlib.sha256(raw).hexdigest() != draft.proposed_sha256
    ):
        raise ValueError("Selected backup changed since review")
    target = persistence.resolve_target(Path(draft.lexical_path))
    if str(target) != draft.resolved_path:
        raise ValueError("Destination changed since review")
    previous = persistence.read_stable(target, limit=MAX_INPUT_BYTES)
    if (
        previous != draft.previous_text.encode()
        or _status(previous.decode()) != draft.current_status
    ):
        raise ValueError("Current output changed since review")
    if (
        persistence.resolve_target(Path(draft.lexical_path)) != target
        or _backup_root() != root
        or str(persistence.recovery_root()) != draft.preservation_root
    ):
        raise ValueError("Recovery paths changed during read")


def prepare_recovery(output_path: Path, backup_name: str) -> RecoveryDraft:
    """Read-only collector; use run_prepare from the UI for a bounded wait."""
    if not _NAME.fullmatch(backup_name):
        raise ValueError("Expected SHA256 backup basename")
    path = output_path.absolute()
    target = persistence.resolve_target(path)
    root = _backup_root()
    preserved = persistence.recovery_root()
    previous = persistence.read_stable(target, limit=MAX_INPUT_BYTES).decode("utf-8")
    status = _status(previous)
    proposed = persistence.read_stable(root / backup_name, limit=MAX_INPUT_BYTES).decode("utf-8")
    _text(proposed)
    persistence.read_document(proposed)
    if _digest(proposed) + ".lua" != backup_name:
        raise ValueError("Backup content identity mismatch")
    # The damaged/foreign original is evidence only, never compiler input.
    persistence.validate_lua(proposed)
    diff, added, removed = restoration.review_diff(previous, proposed, backup_name)
    draft = RecoveryDraft(
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
        status,
        str(preserved / (_digest(previous) + ".bin")),
        str(preserved),
    )
    _validate(draft)
    _read_bound(draft)
    return draft


def run_prepare(
    output_path: Path,
    backup_name: str,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> RecoveryDraft:
    if not _NAME.fullmatch(backup_name):
        raise ValueError("Expected SHA256 backup basename")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Recovery timeout must be finite and positive")
    result = health.run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.recovery",
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
        raise ValueError(f"Recovery preparation failed: {result.stderr[-2048:]}")
    draft = RecoveryDraft.from_json(result.stdout)
    if draft.lexical_path != str(output_path.absolute()) or draft.backup_name != backup_name:
        raise ValueError("Recovery worker returned a different selection")
    _read_bound(draft)
    return draft


@dataclass(frozen=True)
class RecoveryResult:
    status: Literal["recovered"]
    resolved_path: Path
    preservation_path: Path


class RecoveryFailure(ValueError):
    def __init__(self, message: str, *, may_have_written: bool = False):
        super().__init__(message)
        self.may_have_written = may_have_written


def commit_recovery(
    draft: RecoveryDraft, *, cancel_event: threading.Event | None = None
) -> RecoveryResult:
    """Call directly on a non-daemon worker, never a timeout-killed subprocess.

    No IPC/reload is sent, but external watchers may auto-reload replaced output.
    Preserved raw bytes are manual evidence, not necessarily executable/restorable Lua.
    """
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Recovery cancelled before replacement")
        _validate(draft)
        _read_bound(draft)
        preserved = persistence.persist_recovery(
            ReviewSnapshot(
                Path(draft.lexical_path),
                draft.previous_text,
                draft.proposed_text,
                Path(draft.resolved_path),
            ),
            preservation=persistence.RecoveryPreservation(
                Path(draft.preservation_root), Path(draft.preservation_path)
            ),
            expected_source=lambda: _read_bound(draft),
            cancel_event=cancel_event,
        )
    except (OSError, ValueError, RecursionError, RuntimeError) as exc:
        uncertain = isinstance(exc, persistence.PersistenceFailure) and exc.may_have_written
        if uncertain:
            config.invalidate_cache()
        message = str(exc)
        if not uncertain:
            message += "; configuration not replaced; preservation/state files may exist"
        raise RecoveryFailure(message, may_have_written=uncertain) from exc
    config.invalidate_cache()
    return RecoveryResult("recovered", Path(draft.resolved_path), preserved)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only recovery preparation")
    parser.add_argument("--output", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare").add_argument("backup_name")
    args = parser.parse_args()
    print(prepare_recovery(args.output, args.backup_name).to_json())
