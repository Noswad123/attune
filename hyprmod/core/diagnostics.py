"""Allowlisted, read-only projection of Health observations for sharing."""

import re
from datetime import UTC, datetime

from hyprmod.core.health import HealthSnapshot

_CHECKS = {
    "compositor": (
        "Compositor",
        r"Hyprland v?[0-9]+\.[0-9]+\.[0-9]+(?:-?(?:rc|beta|dev)[0-9]*)? \(reachable\)",
    ),
    "config_errors": ("Configuration Errors", r"[0-9]+ configuration errors reported"),
    "displays": ("Displays", r"[0-9]+ connected displays reported"),
    "output": ("Attune Output", r"Owned Attune output|Output is empty"),
    "validator": ("Lua Validator", r"Lua validator found \(not invoked\)"),
    "backups": (
        "Backups",
        r"[0-9]+ regular hash-named backup candidates|"
        r"At least [0-9]+ backup candidates; scan truncated at [0-9]+ entries",
    ),
    "drift": (
        "Saved / Runtime Drift",
        r"[0-9]+ matching, [0-9]+ differing, [0-9]+ unknown saved scalar options"
        r"(?:; no saved scalar comparisons)?"
        r"(?:; partial observation \(time/query budget exhausted\))?",
    ),
}
_STATUS_TEXT = {
    "available": "Observation available; raw details omitted.",
    "unavailable": "Observation unavailable; raw details omitted.",
    "unknown": "Observation inconclusive; raw details omitted.",
    "failed": "Observation failed; raw error details omitted.",
}


def build_diagnostics_report(snapshot: HealthSnapshot, *, stale: bool = False) -> str:
    """Build a bounded summary without exporting arbitrary collector text."""
    try:
        stamp = datetime.fromisoformat(snapshot.observed_at)
        observed = (
            stamp.astimezone(UTC).isoformat() if stamp.utcoffset() is not None else "Unavailable"
        )
    except ValueError:
        observed = "Unavailable"
    lines = [
        "Attune Diagnostics (summary v1)",
        "Redacted summary; inspect before sharing; "
        "not guaranteed to remove all identifying details.",
        f"Observation: {'STALE - ' if stale else ''}{observed}",
        "Output presence does not establish runtime loading.",
        "Backup candidates are not validated as restorable.",
        "Drift covers saved scalar options only; equality does not establish file loading.",
        "Raw errors, paths, configuration, display identities and drift values are omitted.",
    ]
    checks = {check.key: check for check in snapshot.checks if check.key in _CHECKS}
    for key, (title, pattern) in _CHECKS.items():
        check = checks.get(key)
        status = check.status if check is not None and check.status in _STATUS_TEXT else "unknown"
        summary = _STATUS_TEXT[status]
        if check is not None and len(check.summary) <= 256:
            # Failed checks only retain explicitly numeric error/drift counts, never errors.
            if (status != "failed" or key in ("config_errors", "drift")) and re.fullmatch(
                pattern, check.summary, flags=re.ASCII
            ):
                summary = check.summary
        lines.extend(("", f"{title}: {status}", summary))
    return "\n".join(lines) + "\n"
