"""Inactive, read-only canonical v2 group review, not commit or file-load approval.

This is a non-atomic local advisory observation, not a security permit. Neither
Lua compilation nor semantic/write validation is performed. Size/line limits do
not bound direct filesystem latency or diff CPU wall time. Future M3.4 clients
must supervise this work off GTK; this slice deliberately has no worker or wiring.
"""

import difflib
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hyprmod.core import persistence, route_approval, scoped_config
from hyprmod.core.route_approval import InstallationEvidence
from hyprmod.core.scoped_config import ScopedConfig
from hyprmod.core.scopes import Scope

MAX_INPUT_BYTES = 256 * 1024
MAX_INPUT_LINES = 10000
MAX_DIFF_BYTES = 256 * 1024
MAX_DIFF_LINES = 4000


@dataclass(frozen=True, slots=True)
class ScopeReview:
    scope: Scope
    lexical_path: str
    resolved_path: str
    previous_text: str
    proposed_text: str
    previous_sha256: str
    proposed_sha256: str
    previous_content_id: str
    proposed_content_id: str
    diff: str
    diff_sha256: str
    added_lines: int
    removed_lines: int


@dataclass(frozen=True, slots=True)
class GroupReviewPlan:
    evidence: InstallationEvidence
    scopes: tuple[ScopeReview, ...]
    changed_scopes: tuple[Scope, ...]
    review_hash: str
    observed_at: str

    @property
    def notice(self) -> str:
        return (
            "Read-only canonical proposal, not commit or file-load approval. "
            "No compile, semantic, or write validation. Non-atomic local advisory "
            "observation, not a security permit."
        )


def _bounded(text: str) -> None:
    if type(text) is not str or not text or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Review requires nonempty text of at most 256 KiB per side")
    if len(text.splitlines()) > MAX_INPUT_LINES:
        raise ValueError("Review input exceeds 10000 lines")


def _candidate(scope: Scope, config: ScopedConfig) -> str:
    if type(scope) is not Scope or type(config) is not ScopedConfig or config.scope is not scope:
        raise ValueError("Expected Scope key and matching ScopedConfig payload; no conversion")
    # Bound caller-supplied models before reconstruction or Lua text rendering.
    size = records = 0
    for field in (config.values, config.beziers, config.animations, config.monitors):
        if type(field) is not tuple:
            raise ValueError("Expected immutable canonical payload")
        for record in field:
            records += 1
            parts = record if type(record) is tuple else (record,)
            for part in parts:
                if type(part) is not str:
                    raise ValueError("Expected canonical string payload")
                size += len(part.encode("utf-8"))
            if size > MAX_INPUT_BYTES or records > MAX_INPUT_LINES:
                raise ValueError("Review payload exceeds input limits")
    canonical = ScopedConfig(scope, config.payload())
    if canonical != config:
        raise ValueError("Noncanonical or cross-scope payload")
    text = scoped_config.build_text(canonical)
    _bounded(text)
    return text


def _diff(previous: str, proposed: str, scope: Scope) -> tuple[str, int, int]:
    chunks = []
    size = lines = added = removed = 0
    for index, line in enumerate(
        difflib.unified_diff(
            previous.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile=f"current/{scope.value}",
            tofile=f"proposed/{scope.value}",
        )
    ):
        rendered = line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
        size += len(rendered.encode("utf-8"))
        lines += len(rendered.splitlines())
        if size > MAX_DIFF_BYTES or lines > MAX_DIFF_LINES:
            raise ValueError("Complete scope diff exceeds 256 KiB or 4000 lines; refused")
        if index >= 2:
            added += line.startswith("+")
            removed += line.startswith("-")
        chunks.append(rendered)
    return "".join(chunks), added, removed


def _review_hash(
    evidence: InstallationEvidence,
    scopes: tuple[ScopeReview, ...],
    changed: tuple[Scope, ...],
) -> str:
    data = {
        "evidence_hash": evidence.evidence_hash,
        "scopes": [asdict(review) for review in scopes],
        "changed_scopes": changed,
    }
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def build_review(
    evidence: InstallationEvidence, proposals: Mapping[Scope, ScopedConfig]
) -> GroupReviewPlan:
    """Read only the two explicit approved routes, including unchanged siblings."""
    fresh = route_approval.revalidate(evidence)
    if not isinstance(proposals, Mapping):
        raise ValueError("Expected scoped proposal mapping")
    candidates = {scope: _candidate(scope, config) for scope, config in proposals.items()}
    reviews = []
    for route in fresh.routes:
        scope = route.scope
        raw = persistence.read_stable(Path(route.file.path.resolved_path), limit=MAX_INPUT_BYTES)
        if hashlib.sha256(raw).hexdigest() != route.file.source_sha256:
            raise ValueError("Current scope bytes differ from fresh route evidence")
        previous = raw.decode("utf-8")
        _bounded(previous)
        prior = scoped_config.read_document(previous, expected_scope=scope)
        if not isinstance(prior, ScopedConfig) or prior.content_id != route.content_id:
            raise ValueError("Expected existing proof-approved canonical v2 scope")
        proposed = candidates.get(scope, previous)
        candidate = scoped_config.read_document(proposed, expected_scope=scope)
        if not isinstance(candidate, ScopedConfig):
            raise ValueError("Explicit legacy conversion required")
        diff, added, removed = _diff(previous, proposed, scope)
        reviews.append(
            ScopeReview(
                scope,
                route.file.path.lexical_path,
                route.file.path.resolved_path,
                previous,
                proposed,
                route.file.source_sha256,
                scoped_config.byte_hash(proposed),
                prior.content_id,
                candidate.content_id,
                diff,
                scoped_config.byte_hash(diff),
                added,
                removed,
            )
        )
    # Detect drift during either read or diff, including same-byte link changes.
    route_approval.revalidate(fresh)
    scopes = tuple(reviews)
    changed = tuple(r.scope for r in scopes if r.previous_text != r.proposed_text)
    return GroupReviewPlan(
        fresh, scopes, changed, _review_hash(fresh, scopes, changed), datetime.now(UTC).isoformat()
    )


def validate_recorded_review(plan: GroupReviewPlan) -> GroupReviewPlan:
    """Validate historical semantics only. No filesystem IO or write authority."""
    if (
        type(plan) is not GroupReviewPlan
        or type(plan.scopes) is not tuple
        or len(plan.scopes) != len(Scope)
        or type(plan.changed_scopes) is not tuple
        or any(type(scope) is not Scope for scope in plan.changed_scopes)
    ):
        raise ValueError("Invalid group review structure")
    if (
        type(plan.observed_at) is not str
        or len(plan.observed_at) > 64
        or "T" not in plan.observed_at
        or datetime.fromisoformat(plan.observed_at).utcoffset() != timedelta(0)
    ):
        raise ValueError("Review observation must be UTC")
    if type(plan.evidence) is not InstallationEvidence:
        raise ValueError("Expected installation evidence")
    evidence = InstallationEvidence.from_json(plan.evidence.to_json())
    if evidence != plan.evidence:
        raise ValueError("Noncanonical evidence structure")
    for scope, review, route in zip(Scope, plan.scopes, evidence.routes, strict=True):
        if type(review) is not ScopeReview or review.scope is not scope:
            raise ValueError("Expected both scopes in fixed order")
        for name in ScopeReview.__dataclass_fields__:
            value = getattr(review, name)
            expected = int if name in ("added_lines", "removed_lines") else str
            if name != "scope" and type(value) is not expected:
                raise ValueError("Invalid scope review field")
        _bounded(review.previous_text)
        _bounded(review.proposed_text)
        if (
            len(review.diff.encode("utf-8")) > MAX_DIFF_BYTES
            or len(review.diff.splitlines()) > MAX_DIFF_LINES
        ):
            raise ValueError("Review diff exceeds limits")
        candidate = scoped_config.read_document(review.proposed_text, expected_scope=scope)
        prior = scoped_config.read_document(review.previous_text, expected_scope=scope)
        if not isinstance(candidate, ScopedConfig) or not isinstance(prior, ScopedConfig):
            raise ValueError("Expected canonical scoped proposal")
        diff, added, removed = _diff(review.previous_text, review.proposed_text, scope)
        if (
            review.lexical_path != route.file.path.lexical_path
            or review.resolved_path != route.file.path.resolved_path
            or review.previous_sha256 != route.file.source_sha256
            or review.previous_sha256 != scoped_config.byte_hash(review.previous_text)
            or review.proposed_sha256 != scoped_config.byte_hash(review.proposed_text)
            or review.previous_content_id != prior.content_id
            or review.previous_content_id != route.content_id
            or review.proposed_content_id != candidate.content_id
            or route.counts
            != tuple(
                len(getattr(prior, name))
                for name in ("values", "beziers", "animations", "monitors")
            )
            or (review.diff, review.added_lines, review.removed_lines) != (diff, added, removed)
            or review.diff_sha256 != scoped_config.byte_hash(diff)
        ):
            raise ValueError("Recorded scope differs from canonical evidence or exact diff")
    changed = tuple(r.scope for r in plan.scopes if r.previous_text != r.proposed_text)
    if (
        type(plan.review_hash) is not str
        or plan.changed_scopes != changed
        or _review_hash(evidence, plan.scopes, changed) != plan.review_hash
    ):
        raise ValueError("Review differs from rederived complete plan")
    return plan


def revalidate_review(plan: GroupReviewPlan) -> GroupReviewPlan:
    """Rederive canonical proposals and all review semantics against the filesystem."""
    validate_recorded_review(plan)
    proposals = {}
    for review in plan.scopes:
        candidate = scoped_config.read_document(review.proposed_text, expected_scope=review.scope)
        if not isinstance(candidate, ScopedConfig):
            raise ValueError("Expected canonical scoped proposal")
        proposals[review.scope] = candidate
    fresh = build_review(plan.evidence, proposals)
    if fresh.review_hash != plan.review_hash:
        raise ValueError("Review differs from rederived complete plan")
    return fresh
