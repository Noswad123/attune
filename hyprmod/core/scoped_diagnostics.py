"""Inactive explicit filesystem observations and a pure allowlisted projection.

Collection must be supervised off GTK by a future caller. No worker, discovery,
runtime inspection, or application integration is activated here.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from hyprmod.core import route_approval
from hyprmod.core.scoped_config import MAX_INPUT_BYTES
from hyprmod.core.scopes import Scope


@dataclass(frozen=True, slots=True)
class ScopeObservation:
    scope: Scope
    content_id: str
    sha256: str
    counts: tuple[int, ...]
    version: Literal[2] = field(default=2, init=False)

    def __post_init__(self) -> None:
        if type(self.scope) is not Scope or type(self.version) is not int or self.version != 2:
            raise ValueError("Invalid scope or version")
        for digest in (self.content_id, self.sha256):
            if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("Invalid content identity")
        if (
            type(self.counts) is not tuple
            or len(self.counts) != 4
            or any(type(n) is not int or not 0 <= n <= MAX_INPUT_BYTES for n in self.counts)
            or (self.scope == Scope.APPEARANCE and self.counts[3] != 0)
            or (self.scope == Scope.DISPLAYS and any(self.counts[:3]))
        ):
            raise ValueError("Invalid canonical counts")


@dataclass(frozen=True, slots=True)
class ScopedDiagnosticsObservation:
    observed_at: str
    evidence_hash: str
    scopes: tuple[ScopeObservation, ...]
    status: Literal["observed"] = field(default="observed", init=False)

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status != "observed":
            raise ValueError("Invalid observation status")
        if (
            type(self.observed_at) is not str
            or len(self.observed_at) > 64
            or "T" not in self.observed_at
        ):
            raise ValueError("Invalid UTC observation time")
        try:
            offset = datetime.fromisoformat(self.observed_at).utcoffset()
        except ValueError:
            raise ValueError("Invalid UTC observation time") from None
        if offset != timedelta(0):
            raise ValueError("Expected UTC observation time")
        if (
            type(self.evidence_hash) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.evidence_hash) is None
        ):
            raise ValueError("Invalid evidence identity")
        if type(self.scopes) is not tuple or len(self.scopes) != len(Scope):
            raise ValueError("Expected both scopes")
        for scope, summary in zip(Scope, self.scopes, strict=True):
            if type(summary) is not ScopeObservation or summary.scope is not scope:
                raise ValueError("Invalid scope observation or order")
            summary.__post_init__()


def collect_scoped_diagnostics(
    evidence: route_approval.InstallationEvidence,
) -> ScopedDiagnosticsObservation:
    """Reread explicit filesystem context; stale evidence raises ApprovalError."""
    if type(evidence) is not route_approval.InstallationEvidence:
        raise ValueError("Expected explicit installation evidence")
    binding = evidence.evidence_hash
    fresh = route_approval.revalidate(evidence)
    if fresh.evidence_hash != binding:
        raise route_approval.ApprovalError("Installation changed since observation")
    return ScopedDiagnosticsObservation(
        fresh.observed_at,
        fresh.evidence_hash,
        tuple(
            ScopeObservation(route.scope, route.content_id, route.file.source_sha256, route.counts)
            for route in fresh.routes
        ),
    )


def build_scoped_diagnostics_report(
    observation: ScopedDiagnosticsObservation, *, stale: bool = False
) -> str:
    """Project known facts only. Rendering never rechecks filesystem freshness."""
    if type(observation) is not ScopedDiagnosticsObservation or type(stale) is not bool:
        raise ValueError("Invalid diagnostics report input")
    observation.__post_init__()
    stamp = datetime.fromisoformat(observation.observed_at).astimezone(UTC).isoformat()
    lines = [
        "Attune Scoped Diagnostics (summary v1)",
        "Redacted bounded summary; inspect before sharing. Counts and time may identify activity.",
        f"{'STALE - previous observation' if stale else 'Recorded observation'}: {stamp}",
        "Freshly revalidated at collection time only; this report does not recheck freshness.",
        "Observed filesystem facts, not loaded configuration or runtime state.",
        "Permission checks are observations, not write authority or a write permit.",
        "Hashes are content identities, not authentication; "
        "all hashes are omitted from this report.",
        "Canonical verification is not Lua syntax or semantic validation, or restorability.",
        "No journal or split writer is active; no runtime IPC or Lua validation was performed.",
        "Paths, registry content, usernames, UIDs, inodes, "
        "link targets and raw values are omitted.",
        "Independent reads are not an atomic snapshot or a hostile-filesystem security guarantee.",
    ]
    for summary in observation.scopes:
        values, beziers, animations, monitors = summary.counts
        lines.extend(
            (
                "",
                f"{summary.scope.value}: observed canonical v2",
                f"values: {values}; beziers: {beziers}; "
                f"animations: {animations}; monitors: {monitors}",
            )
        )
    return "\n".join(lines) + "\n"
