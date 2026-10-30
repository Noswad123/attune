"""Metadata-only legacy exclusion. Absence is not proof of loader selection."""

import os
import stat
from pathlib import Path


def validate_context(root: Path) -> None:
    if (
        not isinstance(root, Path)
        or not root.is_absolute()
        or str(root) != os.path.normpath(str(root))
        or len(str(root).encode("utf-8")) > 4096
        or len(root.parts) > 128
        or any(ord(c) < 32 or ord(c) == 127 for c in str(root))
    ):
        raise ValueError("Expected explicit bounded normalized absolute config/state roots")


def metadata(path: Path) -> os.stat_result | None:
    """Refuse unsafe ancestors, including dangling links; never follow them."""
    for parent in reversed(path.parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            return None
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in (0, os.getuid())
            or not info.st_mode & 0o444
            or not info.st_mode & 0o111
            or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))
        ):
            raise ValueError(f"Unsafe or unreadable layout ancestor: {parent}")
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def block_reason(config_root: Path, state_root: Path) -> str | None:
    """Any registry or journal evidence excludes v1 writes, including terminal history."""
    try:
        validate_context(config_root)
        validate_context(state_root)
        if metadata(config_root / "attune/installation.json") is not None:
            return "Installation registry is present; scoped assessment/recovery is required"
        directory = state_root / "attune/transactions"
        info = metadata(directory)
        if info is None:
            return None
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            return "Unsafe or unreadable transaction directory; legacy writes are blocked"
        with os.scandir(directory) as entries:
            if next(entries, None) is not None:
                return "Transaction evidence is present; scoped assessment/recovery is required"
        if directory.lstat() != info:
            return "Transaction directory changed during layout assessment"
        return None
    except (OSError, ValueError) as exc:
        return f"Cannot establish a clear legacy layout: {exc}"
