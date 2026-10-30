"""Read-only interrupted-state observations, never recovery authority.

Direct calls have no filesystem/diff wall-clock guarantee. Repeated observations
narrow local races, not an atomic snapshot or hostile-filesystem isolation. No
classification establishes publication history or compositor runtime state.
Evidence hashes are fingerprints, not authentication or serialized authority.
"""

import os
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from hyprmod.core import route_approval, transaction_store
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import route_binding, validate_transaction_id
from hyprmod.core.transaction_store import StoreBinding


class OverallStatus(StrEnum):
    ALL_PRIOR = "all-prior"
    ALL_PROPOSED = "all-proposed"
    MIXED = "mixed"
    CONFLICT = "conflict"


class ScopeStatus(StrEnum):
    PRIOR = "prior"
    PROPOSED = "proposed"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class ScopeObservation:
    scope: Scope
    status: ScopeStatus
    prior_sha256: str | None
    proposed_sha256: str | None
    current_sha256: str | None
    prior_content_id: str | None
    proposed_content_id: str | None
    current_content_id: str | None


@dataclass(frozen=True, slots=True)
class TransactionObservation:
    status: OverallStatus
    scopes: tuple[ScopeObservation, ...]
    binding: StoreBinding | None
    snapshot_id: str | None
    review_hash: str | None
    prior_evidence_hash: str | None
    current_evidence_hash: str | None
    observed_at: str
    notes: tuple[str, ...]


def _explicit_path(value: Path) -> None:
    text = str(value)
    if (
        not isinstance(value, Path)
        or not value.is_absolute()
        or text != os.path.normpath(text)
        or len(text.encode("utf-8")) > 4096
        or len(value.parts) > 128
        or any(unicodedata.category(c) in {"Cc", "Cf"} or c in "~$`" for c in text)
    ):
        raise ValueError("Expected explicit bounded normalized absolute context")


def classify_transaction(
    state_root: Path, transaction_id: str, *, config_root: Path
) -> TransactionObservation:
    """Reload private evidence and classify actual canonical bytes in explicit context.

    Phase/progress are advisory even when recorded as committed. Known mixtures
    imply no repair action. This API never invokes publication or recovery.
    """
    bundle = None
    current = None
    statuses: dict[Scope, ScopeStatus] = {}
    notes = [
        "Read-only, non-atomic local observation, not a write permit or runtime claim. "
        "Journal phase/progress are advisory; recovery requires a separate explicit review."
    ]
    try:
        _explicit_path(state_root)
        _explicit_path(config_root)
        validate_transaction_id(transaction_id)
        bundle = transaction_store.load_transaction(state_root, transaction_id)
        transaction_store.revalidate_store(bundle.binding)
        plan = bundle.snapshot.plan
        old = plan.evidence
        if (old.config_root, old.state_root) != (str(config_root), str(state_root)):
            raise ValueError("Stored review differs from explicit config/state context")
        if not plan.changed_scopes:
            raise ValueError("No-op journals are unsupported")
        private_facts = transaction_store.verified_fingerprint(bundle)
        registry_path = config_root / "attune/installation.json"
        current = route_approval.inspect_installation(
            registry_path, config_root=config_root, state_root=state_root
        )
        if (
            current.config_root != old.config_root
            or current.state_root != old.state_root
            or current.registry != old.registry
            or current.protected != old.protected
        ):
            raise ValueError("Registry or protected/context evidence changed; fresh review needed")
        for review, prior, actual in zip(plan.scopes, old.routes, current.routes, strict=True):
            status = ScopeStatus.CONFLICT
            if actual.scope is not review.scope or prior.scope is not review.scope:
                raise ValueError("Scope binding changed")
            if review.scope not in plan.changed_scopes:
                if actual == prior:
                    status = ScopeStatus.UNCHANGED
            elif route_binding(actual.file) == route_binding(prior.file):
                identity = (actual.file.source_sha256, actual.content_id)
                if identity == (review.previous_sha256, review.previous_content_id):
                    status = ScopeStatus.PRIOR
                elif identity == (review.proposed_sha256, review.proposed_content_id):
                    status = ScopeStatus.PROPOSED
            statuses[review.scope] = status
        if bundle.rollback is not None:
            initial = bundle.rollback.initial_review
            for scope, actual, first in zip(
                Scope, current.routes, initial.evidence.routes, strict=True
            ):
                if scope not in bundle.rollback.restore_scopes and actual != first:
                    statuses[scope] = ScopeStatus.CONFLICT
            notes.append("Rollback direction locked; explicit fresh rollback completion required")
        fresh = route_approval.inspect_installation(
            registry_path, config_root=config_root, state_root=state_root
        )
        if fresh.evidence_hash != current.evidence_hash:
            raise ValueError(
                "Current installation changed during classification; fresh review needed"
            )
        transaction_store.revalidate_store(bundle.binding)
        reloaded = transaction_store.load_transaction(state_root, transaction_id)
        if reloaded != bundle or transaction_store.verified_fingerprint(reloaded) != private_facts:
            raise ValueError(
                "Private transaction changed during classification; fresh review needed"
            )
        transaction_store.revalidate_store(bundle.binding)
        changed = {statuses[scope] for scope in plan.changed_scopes}
        if ScopeStatus.CONFLICT in statuses.values():
            overall = OverallStatus.CONFLICT
            notes.append("Scope bytes, identity, or binding changed; fresh review needed")
        elif changed == {ScopeStatus.PRIOR}:
            overall = OverallStatus.ALL_PRIOR
        elif changed == {ScopeStatus.PROPOSED}:
            overall = OverallStatus.ALL_PROPOSED
        else:
            overall = OverallStatus.MIXED
    except (OSError, ValueError, RuntimeError) as exc:
        overall = OverallStatus.CONFLICT
        statuses = {}
        # Keep diagnostics local and bounded, including unusually long OS errors.
        notes.append(str(exc).encode("utf-8", errors="replace")[:1024].decode("utf-8", "ignore"))

    scopes = []
    for index, scope in enumerate(Scope):
        review = bundle.snapshot.plan.scopes[index] if bundle is not None else None
        route = current.routes[index] if current is not None else None
        scopes.append(
            ScopeObservation(
                scope,
                statuses.get(scope, ScopeStatus.CONFLICT),
                review.previous_sha256 if review else None,
                review.proposed_sha256 if review else None,
                route.file.source_sha256 if route else None,
                review.previous_content_id if review else None,
                review.proposed_content_id if review else None,
                route.content_id if route else None,
            )
        )
    return TransactionObservation(
        overall,
        tuple(scopes),
        bundle.binding if bundle else None,
        bundle.snapshot.snapshot_id if bundle else None,
        bundle.snapshot.plan.review_hash if bundle else None,
        bundle.snapshot.plan.evidence.evidence_hash if bundle else None,
        current.evidence_hash if current else None,
        datetime.now(UTC).isoformat(),
        tuple(notes),
    )
