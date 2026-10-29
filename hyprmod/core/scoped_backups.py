"""Inactive, pure backup metadata. Canonical identity is not restore authority."""

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from hyprland_config import Assignment, Keyword

from hyprmod.core import persistence, scoped_config
from hyprmod.core.scopes import Scope


@dataclass(frozen=True, slots=True)
class BackupDescriptor:
    name: str
    kind: Literal["legacy-full-bundle", "scoped-v2"]
    version: int
    scope: Scope | None
    content_id: str | None
    sha256: str
    size_bytes: int
    # values, beziers, animations, monitors; legacy counts cover the entire bundle.
    counts: tuple[int, ...]

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or re.fullmatch(r"[0-9a-f]{64}\.lua", self.name) is None
            or type(self.sha256) is not str
            or self.sha256 != self.name[:-4]
        ):
            raise ValueError("Expected matching lowercase hash basename and byte identity")
        if (
            type(self.size_bytes) is not int
            or not 1 <= self.size_bytes <= scoped_config.MAX_INPUT_BYTES
        ):
            raise ValueError("Invalid backup byte size")
        if (
            type(self.counts) is not tuple
            or len(self.counts) != 4
            or any(
                type(n) is not int or not 0 <= n <= scoped_config.MAX_INPUT_BYTES
                for n in self.counts
            )
        ):
            raise ValueError("Invalid canonical counts")
        if type(self.version) is not int or type(self.kind) is not str:
            raise ValueError("Invalid backup classification")
        if self.kind == "legacy-full-bundle":
            if self.version != 1 or self.scope is not None or self.content_id is not None:
                raise ValueError("Legacy data must remain a full bundle")
        elif self.kind == "scoped-v2":
            if (
                self.version != 2
                or type(self.scope) is not Scope
                or type(self.content_id) is not str
                or re.fullmatch(r"[0-9a-f]{64}", self.content_id) is None
                or (self.scope == Scope.APPEARANCE and self.counts[3] != 0)
                or (self.scope == Scope.DISPLAYS and any(self.counts[:3]))
            ):
                raise ValueError("Invalid scoped identity or counts")
        else:
            raise ValueError("Unknown backup classification")


def describe_backup(
    backup_name: str, text: str, *, expected_scope: Scope | None = None
) -> BackupDescriptor:
    """Verify supplied bytes and canonical format, not Lua syntax or restorability."""
    if type(backup_name) is not str or re.fullmatch(r"[0-9a-f]{64}\.lua", backup_name) is None:
        raise ValueError("Expected lowercase SHA-256 backup basename")
    if expected_scope is not None and type(expected_scope) is not Scope:
        raise ValueError("Expected a known Scope")
    if type(text) is not str or len(text) > scoped_config.MAX_INPUT_BYTES:
        raise ValueError("Expected bounded UTF-8 text")
    try:
        raw = text.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Expected UTF-8 text") from exc
    if not 0 < len(raw) <= scoped_config.MAX_INPUT_BYTES:
        raise ValueError("Expected nonempty bounded UTF-8 text")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != backup_name[:-4]:
        raise ValueError("Backup byte hash does not match basename")
    parsed = scoped_config.read_document(text, expected_scope=expected_scope)
    if isinstance(parsed, scoped_config.LegacyBundle):
        document = persistence.read_document(parsed.text)
        counts = (
            sum(isinstance(line, Assignment) for line in document.lines),
            *(
                sum(isinstance(line, Keyword) and line.key == key for line in document.lines)
                for key in ("bezier", "animation", "monitor")
            ),
        )
        return BackupDescriptor(
            backup_name, "legacy-full-bundle", 1, None, None, digest, len(raw), counts
        )
    return BackupDescriptor(
        backup_name,
        "scoped-v2",
        2,
        parsed.scope,
        parsed.content_id,
        digest,
        len(raw),
        tuple(len(getattr(parsed, key)) for key in ("values", "beziers", "animations", "monitors")),
    )
