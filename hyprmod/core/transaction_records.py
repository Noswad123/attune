"""Pure ordinary split-save evidence. Historical records are never write permits."""

import hashlib
import json
import re
import stat
from dataclasses import asdict, dataclass
from enum import StrEnum

from hyprmod.core.route_approval import FileEvidence, InstallationEvidence
from hyprmod.core.scoped_review import GroupReviewPlan, ScopeReview, validate_recorded_review
from hyprmod.core.scopes import Scope

MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 24


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def fields(value: object, names: set[str]) -> dict:
    if type(value) is not dict or set(value) != names:
        raise ValueError("Unexpected record fields")
    return value


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate record field")
        result[key] = value
    return result


def decode_json(text: str) -> object:
    if type(text) is not str or len(text.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError("Record exceeds 8 MiB transport limit")
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("Record nesting exceeds limit")
        elif char in "]}":
            depth -= 1
    try:
        return json.loads(text, object_pairs_hook=_unique, parse_constant=_invalid_constant)
    except (RecursionError, OverflowError) as exc:
        raise ValueError("Invalid record JSON") from exc


def _invalid_constant(value: str) -> object:
    raise ValueError(f"Invalid JSON constant: {value}")


def validate_transaction_id(value: str) -> str:
    if type(value) is not str or re.fullmatch("[0-9a-f]{32}", value) is None:
        raise ValueError("Transaction ID must be 32 lowercase hexadecimal characters")
    return value


def validate_digest(value: str) -> str:
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("Expected lowercase SHA-256")
    return value


def route_binding(file: FileEvidence) -> tuple:
    """Exclude only the resolved regular leaf; preserve every link and ancestor."""
    proof = file.path
    return (
        proof.lexical_path,
        proof.resolved_path,
        tuple(
            (fact.path, (), None)
            if fact.path == proof.resolved_path and fact.identity and stat.S_ISREG(fact.identity[2])
            else (fact.path, fact.identity, fact.link_target)
            for fact in proof.facts
        ),
        file.git_context,
    )


def _scopes(value: object) -> tuple[Scope, ...]:
    if type(value) is not list or any(type(s) is not str for s in value):
        raise ValueError("Expected scope array")
    result = tuple(Scope(s) for s in value)
    if not result or result != tuple(s for s in Scope if s in result):
        raise ValueError("Expected nonempty fixed-order changed scopes")
    return result


def _plan_data(plan: GroupReviewPlan) -> dict:
    return {
        "evidence": json.loads(plan.evidence.to_json()),
        "scopes": [asdict(s) for s in plan.scopes],
        "changed_scopes": list(plan.changed_scopes),
        "review_hash": plan.review_hash,
        "observed_at": plan.observed_at,
    }


def _plan_from(value: object) -> GroupReviewPlan:
    data = fields(value, set(GroupReviewPlan.__dataclass_fields__))
    evidence = InstallationEvidence.from_json(canonical_json(data["evidence"]))
    scopes = data["scopes"]
    if type(scopes) is not list or len(scopes) != len(Scope):
        raise ValueError("Expected both scope reviews")
    reviews = []
    for record in scopes:
        item = fields(record, set(ScopeReview.__dataclass_fields__)).copy()
        item["scope"] = Scope(item["scope"])
        reviews.append(ScopeReview(**item))
    return GroupReviewPlan(
        evidence,
        tuple(reviews),
        () if data["changed_scopes"] == [] else _scopes(data["changed_scopes"]),
        data["review_hash"],
        data["observed_at"],
    )


def plan_to_json(plan: GroupReviewPlan) -> str:
    validate_recorded_review(plan)
    text = canonical_json(_plan_data(plan))
    decode_json(text)
    return text


def plan_from_json(text: str) -> GroupReviewPlan:
    try:
        return validate_recorded_review(_plan_from(decode_json(text)))
    except (TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise ValueError(f"Invalid recorded plan: {exc}") from exc


class PriorKind(StrEnum):
    PRESENT_OWNED = "present-owned"
    ABSENT = "absent"
    PRESENT_EMPTY = "present-empty"


class Phase(StrEnum):
    PREPARED = "prepared"
    PUBLISHING = "publishing"
    COMMITTED = "committed"
    ABORTED = "aborted"


@dataclass(frozen=True, slots=True)
class GroupSnapshot:
    plan: GroupReviewPlan
    prior_kinds: tuple[PriorKind, ...] = (PriorKind.PRESENT_OWNED, PriorKind.PRESENT_OWNED)

    def __post_init__(self) -> None:
        validate_recorded_review(self.plan)
        if not self.plan.changed_scopes:
            raise ValueError("No-op has no transaction snapshot")
        if (
            type(self.prior_kinds) is not tuple
            or self.prior_kinds != (PriorKind.PRESENT_OWNED, PriorKind.PRESENT_OWNED)
            or any(type(k) is not PriorKind for k in self.prior_kinds)
        ):
            raise ValueError("Only present-owned priors supported; migration is not implemented")

    def to_json(self) -> str:
        text = canonical_json(
            {
                "schema": 1,
                "kind": "ordinary-split-save",
                "prior_kinds": self.prior_kinds,
                "plan": _plan_data(self.plan),
            }
        )
        if len(text.encode("utf-8")) > MAX_RECORD_BYTES:
            raise ValueError("Snapshot exceeds transport limit")
        return text

    @property
    def snapshot_id(self) -> str:
        return hashlib.sha256(self.to_json().encode("ascii")).hexdigest()

    @classmethod
    def from_json(cls, text: str) -> "GroupSnapshot":
        data = fields(decode_json(text), {"schema", "kind", "prior_kinds", "plan"})
        if (
            type(data["schema"]) is not int
            or data["schema"] != 1
            or data["kind"] != "ordinary-split-save"
        ):
            raise ValueError("Unsupported snapshot format")
        kinds = data["prior_kinds"]
        if type(kinds) is not list or len(kinds) != len(Scope):
            raise ValueError("Expected both prior kinds")
        return cls(_plan_from(data["plan"]), tuple(PriorKind(k) for k in kinds))


@dataclass(frozen=True, slots=True)
class TransactionIntent:
    transaction_id: str
    snapshot_id: str
    review_hash: str
    registry: FileEvidence
    changed_scopes: tuple[Scope, ...]
    phase: Phase = Phase.PREPARED
    progress: tuple[Scope, ...] = ()

    def __post_init__(self) -> None:
        validate_transaction_id(self.transaction_id)
        validate_digest(self.snapshot_id)
        validate_digest(self.review_hash)
        if type(self.registry) is not FileEvidence:
            raise ValueError("Expected typed registry evidence")
        if (
            type(self.changed_scopes) is not tuple
            or any(type(s) is not Scope for s in self.changed_scopes)
            or _scopes([s.value for s in self.changed_scopes]) != self.changed_scopes
        ):
            # StrEnum values are strings on transport, but typed models require Scope.
            raise ValueError("Invalid changed scopes")
        if (
            type(self.phase) is not Phase
            or type(self.progress) is not tuple
            or any(type(s) is not Scope for s in self.progress)
            or self.progress != self.changed_scopes[: len(self.progress)]
            or (self.phase is Phase.PREPARED and self.progress)
            or (self.phase is Phase.COMMITTED and self.progress != self.changed_scopes)
        ):
            raise ValueError("Invalid advisory progress prefix or phase")

    def validate_snapshot(self, snapshot: GroupSnapshot) -> None:
        if (
            self.snapshot_id != snapshot.snapshot_id
            or self.review_hash != snapshot.plan.review_hash
            or self.registry != snapshot.plan.evidence.registry
            or self.changed_scopes != snapshot.plan.changed_scopes
        ):
            raise ValueError("Intent does not bind snapshot and registry")

    def to_json(self) -> str:
        text = canonical_json({"schema": 1, "kind": "ordinary-split-save", **asdict(self)})
        if len(text.encode("utf-8")) > MAX_RECORD_BYTES:
            raise ValueError("Intent exceeds transport limit")
        return text

    @classmethod
    def from_json(cls, text: str, *, snapshot: GroupSnapshot) -> "TransactionIntent":
        data = fields(decode_json(text), {"schema", "kind", *cls.__dataclass_fields__})
        if (
            type(data["schema"]) is not int
            or data["schema"] != 1
            or data["kind"] != "ordinary-split-save"
        ):
            raise ValueError("Unsupported intent format")
        if canonical_json(data["registry"]) != canonical_json(
            asdict(snapshot.plan.evidence.registry)
        ):
            raise ValueError("Registry identity mismatch")
        progress = data["progress"]
        if type(progress) is not list or any(type(s) is not str for s in progress):
            raise ValueError("Expected progress array")
        result = cls(
            data["transaction_id"],
            data["snapshot_id"],
            data["review_hash"],
            snapshot.plan.evidence.registry,
            _scopes(data["changed_scopes"]),
            Phase(data["phase"]),
            tuple(Scope(s) for s in progress),
        )
        result.validate_snapshot(snapshot)
        return result


@dataclass(frozen=True, slots=True)
class RollbackOperation:
    snapshot_id: str
    original_review_hash: str
    private_fingerprint_sha256: str
    initial_review: GroupReviewPlan
    restore_scopes: tuple[Scope, ...]

    @property
    def operation_sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode("ascii")).hexdigest()

    def validate_snapshot(self, snapshot: GroupSnapshot) -> None:
        validate_digest(self.private_fingerprint_sha256)
        validate_recorded_review(self.initial_review)
        original = snapshot.plan
        if (
            self.snapshot_id != snapshot.snapshot_id
            or self.original_review_hash != original.review_hash
            or self.initial_review.evidence.registry != original.evidence.registry
            or self.initial_review.evidence.config_root != original.evidence.config_root
            or self.initial_review.evidence.state_root != original.evidence.state_root
            or self.initial_review.evidence.protected != original.evidence.protected
            or self.restore_scopes != self.initial_review.changed_scopes
            or not self.restore_scopes
            or any(s not in original.changed_scopes for s in self.restore_scopes)
        ):
            raise ValueError("Rollback does not bind original transaction")
        for prior, actual in zip(
            original.evidence.routes, self.initial_review.evidence.routes, strict=True
        ):
            if route_binding(prior.file) != route_binding(actual.file) or (
                prior.scope not in original.changed_scopes and prior != actual
            ):
                raise ValueError("Rollback initial evidence differs from original bindings")
        for old, review in zip(original.scopes, self.initial_review.scopes, strict=True):
            if review.proposed_text != old.previous_text or review.previous_text not in (
                old.previous_text,
                old.proposed_text,
            ):
                raise ValueError("Rollback goals must be verified original prior bytes")

    def to_json(self) -> str:
        return canonical_json(
            {
                "schema": 1,
                "kind": "ordinary-rollback",
                "snapshot_id": self.snapshot_id,
                "original_review_hash": self.original_review_hash,
                "private_fingerprint_sha256": self.private_fingerprint_sha256,
                "initial_review": _plan_data(self.initial_review),
                "restore_scopes": self.restore_scopes,
            }
        )

    @classmethod
    def from_json(cls, text: str, *, snapshot: GroupSnapshot) -> "RollbackOperation":
        data = fields(decode_json(text), {"schema", "kind", *cls.__dataclass_fields__})
        if (
            type(data["schema"]) is not int
            or data["schema"] != 1
            or data["kind"] != "ordinary-rollback"
        ):
            raise ValueError("Unsupported rollback record")
        result = cls(
            data["snapshot_id"],
            data["original_review_hash"],
            data["private_fingerprint_sha256"],
            _plan_from(data["initial_review"]),
            _scopes(data["restore_scopes"]),
        )
        result.validate_snapshot(snapshot)
        return result


@dataclass(frozen=True, slots=True)
class RollbackCheckpoint:
    operation_sha256: str
    progress: tuple[Scope, ...] = ()
    complete: bool = False

    def validate_operation(self, operation: RollbackOperation) -> None:
        if (
            self.operation_sha256 != operation.operation_sha256
            or type(self.progress) is not tuple
            or any(type(s) is not Scope for s in self.progress)
            or self.progress != operation.restore_scopes[: len(self.progress)]
            or type(self.complete) is not bool
            or (self.complete and self.progress != operation.restore_scopes)
        ):
            raise ValueError("Invalid rollback checkpoint")

    def to_json(self) -> str:
        return canonical_json({"schema": 1, "kind": "rollback-checkpoint", **asdict(self)})

    @classmethod
    def from_json(cls, text: str, *, operation: RollbackOperation) -> "RollbackCheckpoint":
        data = fields(decode_json(text), {"schema", "kind", *cls.__dataclass_fields__})
        if (
            type(data["schema"]) is not int
            or data["schema"] != 1
            or data["kind"] != "rollback-checkpoint"
        ):
            raise ValueError("Unsupported rollback checkpoint")
        if type(data["progress"]) is not list:
            raise ValueError("Expected rollback progress array")
        result = cls(
            data["operation_sha256"], tuple(Scope(s) for s in data["progress"]), data["complete"]
        )
        result.validate_operation(operation)
        return result
