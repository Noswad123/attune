"""Scoped recovery frontend service. Only read-only work has a child entry point.

Call from off GTK. Commit directly on a non-daemon worker; never timeout-kill it.
DTO hashes bind local observations, not authentication or a one-use capability.
No assessment establishes loader selection, publication history, or runtime state.
"""

import argparse
import math
import stat
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from hyprmod.core import health, layout_guard, route_approval, scoped_review
from hyprmod.core import transaction_inspection as inspection
from hyprmod.core import transaction_publication as publication
from hyprmod.core import transaction_store as store
from hyprmod.core.scoped_review import GroupReviewPlan
from hyprmod.core.transaction_records import (
    MAX_RECORD_BYTES,
    Phase,
    canonical_json,
    decode_json,
    fields,
    plan_from_json,
    plan_to_json,
    validate_digest,
    validate_transaction_id,
)

MAX_ASSESS_BYTES = 1024 * 1024
MAX_ROWS = 32
ACTIONS = ("resume", "rollback", "finalize", "abandon")
MODES = ("legacy-clear", "scope-recovery-required", "blocked")


def _context(config_root: Path, state_root: Path) -> None:
    layout_guard.validate_context(config_root)
    layout_guard.validate_context(state_root)


def _text(value: object) -> None:
    if type(value) is not str or len(value.encode("utf-8")) > 1024:
        raise ValueError("Expected bounded diagnostic text")


def _note(error: object) -> str:
    return str(error).encode("utf-8", "replace")[:1024].decode("utf-8", "ignore")


@dataclass(frozen=True, slots=True)
class CanonicalScope:
    scope: str
    source_sha256: str
    content_id: str


@dataclass(frozen=True, slots=True)
class TransactionRow:
    transaction_id: str
    validity: str
    phase: str | None
    rollback_direction: bool | None
    actual_status: str
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LayoutAssessment:
    config_root: str
    state_root: str
    mode: str
    registry_condition: str
    canonical_pair: tuple[CanonicalScope, ...]
    registry_error: str | None
    transactions: tuple[TransactionRow, ...]
    truncated: bool
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.config_root) is not str or type(self.state_root) is not str:
            raise ValueError("Expected context strings")
        _context(Path(self.config_root), Path(self.state_root))
        if self.mode not in MODES or self.registry_condition not in (
            "absent",
            "valid",
            "invalid-or-uninspectable",
        ):
            raise ValueError("Unknown assessment frame")
        if type(self.truncated) is not bool:
            raise ValueError("Invalid truncation flag")
        if type(self.canonical_pair) is not tuple or len(self.canonical_pair) not in (0, 2):
            raise ValueError("Expected empty or complete canonical pair")
        for index, item in enumerate(self.canonical_pair):
            if type(item) is not CanonicalScope or item.scope != ("appearance", "displays")[index]:
                raise ValueError("Invalid canonical scope order")
            validate_digest(item.source_sha256)
            validate_digest(item.content_id)
        if self.registry_error is not None:
            _text(self.registry_error)
        if type(self.transactions) is not tuple or len(self.transactions) > MAX_ROWS:
            raise ValueError("Invalid bounded transaction rows")
        ids = []
        for row in self.transactions:
            if type(row) is not TransactionRow:
                raise ValueError("Expected immutable transaction row")
            ids.append(validate_transaction_id(row.transaction_id))
            if (
                row.validity not in ("verified", "invalid")
                or row.phase not in (None, *(p.value for p in Phase))
                or (row.rollback_direction is not None and type(row.rollback_direction) is not bool)
                or row.actual_status not in tuple(s.value for s in inspection.OverallStatus)
            ):
                raise ValueError("Invalid transaction observation")
            if (
                row.validity == "verified" and (row.phase is None or row.rollback_direction is None)
            ) or (
                row.validity == "invalid"
                and (
                    row.phase is not None
                    or row.rollback_direction is not None
                    or row.actual_status != "conflict"
                )
            ):
                raise ValueError("Transaction validity contradicts recorded observation")
            self._notes(row.notes)
        if ids != sorted(set(ids)):
            raise ValueError("Invalid transaction ordering")
        self._notes(self.notes)
        if bool(self.canonical_pair) != (self.registry_condition == "valid"):
            raise ValueError("Registry condition contradicts canonical pair observation")
        if (self.registry_error is not None) != (
            self.registry_condition == "invalid-or-uninspectable"
        ):
            raise ValueError("Registry condition contradicts inspection error")
        if self.mode == "legacy-clear" and (
            self.registry_condition != "absent"
            or self.transactions
            or self.truncated
            or self.registry_error is not None
            or self.notes
        ):
            raise ValueError("Legacy-clear contradicts blocking evidence")
        if self.mode != "blocked" and (
            self.truncated
            or self.registry_error is not None
            or self.notes
            or any(
                r.validity == "invalid" or r.actual_status == "conflict" for r in self.transactions
            )
        ):
            raise ValueError("Unhealthy observation must block")
        if self.mode == "scope-recovery-required" and (
            self.registry_condition == "absent" and not self.transactions
        ):
            raise ValueError("Recovery-required needs scoped evidence")

    @staticmethod
    def _notes(notes: tuple[str, ...]) -> None:
        if type(notes) is not tuple or len(notes) > 16:
            raise ValueError("Invalid bounded notes")
        for note in notes:
            _text(note)

    def to_json(self) -> str:
        self.__post_init__()
        text = canonical_json({"schema": 1, "kind": "scoped-layout-assessment", **asdict(self)})
        if len(text.encode("ascii")) > MAX_ASSESS_BYTES:
            raise ValueError("Assessment exceeds 1 MiB")
        return text

    @classmethod
    def from_json(cls, text: str) -> "LayoutAssessment":
        if type(text) is not str or len(text.encode("utf-8")) > MAX_ASSESS_BYTES:
            raise ValueError("Assessment exceeds 1 MiB")
        data = fields(decode_json(text), {"schema", "kind", *cls.__dataclass_fields__}).copy()
        schema = data.pop("schema")
        if type(schema) is not int or schema != 1 or data.pop("kind") != "scoped-layout-assessment":
            raise ValueError("Unknown assessment format")
        if type(data["canonical_pair"]) is not list or type(data["transactions"]) is not list:
            raise ValueError("Expected observation arrays")
        data["canonical_pair"] = tuple(
            CanonicalScope(**fields(r, set(CanonicalScope.__dataclass_fields__)))
            for r in data["canonical_pair"]
        )
        rows = []
        for record in data["transactions"]:
            row = fields(record, set(TransactionRow.__dataclass_fields__)).copy()
            if type(row["notes"]) is not list:
                raise ValueError("Expected notes array")
            row["notes"] = tuple(row["notes"])
            rows.append(TransactionRow(**row))
        data["transactions"] = tuple(rows)
        if type(data["notes"]) is not list:
            raise ValueError("Expected notes array")
        data["notes"] = tuple(data["notes"])
        return cls(**data)


def assess_layout(config_root: Path, state_root: Path) -> LayoutAssessment:
    """Observe only the configured registry, canonical pair, and private journals."""
    _context(config_root, state_root)
    condition = "absent"
    pair = ()
    registry_error = None
    rows = []
    notes = []
    truncated = False
    try:
        if layout_guard.metadata(config_root / "attune/installation.json") is not None:
            condition = "invalid-or-uninspectable"
            evidence = route_approval.inspect_installation(
                config_root / "attune/installation.json",
                config_root=config_root,
                state_root=state_root,
            )
            pair = tuple(
                CanonicalScope(r.scope.value, r.file.source_sha256, r.content_id)
                for r in evidence.routes
            )
            condition = "valid"
    except (OSError, ValueError, RuntimeError) as exc:
        condition = "invalid-or-uninspectable"
        registry_error = _note(exc)
    try:
        directory = state_root / "attune/transactions"
        info = layout_guard.metadata(directory)
        if info is not None:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("Unsafe transaction directory")
            ids = store.list_transaction_ids(state_root)
            truncated = len(ids) > MAX_ROWS
            if truncated:
                notes.append("Transaction rows truncated; layout is not legacy-clear")
            for txid in ids[:MAX_ROWS]:
                try:
                    bundle = store.load_transaction(state_root, txid)
                    observed = inspection.classify_transaction(
                        state_root, txid, config_root=config_root
                    )
                    rows.append(
                        TransactionRow(
                            txid,
                            "verified",
                            bundle.intent.phase.value,
                            bundle.rollback is not None,
                            observed.status.value,
                            observed.notes,
                        )
                    )
                except (OSError, ValueError, RuntimeError) as exc:
                    rows.append(
                        TransactionRow(txid, "invalid", None, None, "conflict", (_note(exc),))
                    )
    except (OSError, ValueError, RuntimeError) as exc:
        notes.append(_note(exc))
    reason = layout_guard.block_reason(config_root, state_root)
    unhealthy = (
        registry_error is not None
        or notes
        or truncated
        or any(r.validity == "invalid" or r.actual_status == "conflict" for r in rows)
    )
    mode = (
        "blocked"
        if unhealthy
        else "scope-recovery-required"
        if reason or condition == "valid" or rows
        else "legacy-clear"
    )
    if reason and condition == "absent" and not rows and not notes:
        mode = "blocked"
        notes.append(_note(reason))
    return LayoutAssessment(
        str(config_root),
        str(state_root),
        mode,
        condition,
        pair,
        registry_error,
        tuple(rows),
        truncated,
        tuple(notes),
    )


@dataclass(frozen=True, slots=True)
class ScopedRecoveryDraft:
    config_root: str
    state_root: str
    transaction_id: str
    action: str
    private_digest: str
    snapshot_id: str
    original_review_hash: str
    plan: GroupReviewPlan

    def __post_init__(self) -> None:
        if type(self.config_root) is not str or type(self.state_root) is not str:
            raise ValueError("Expected explicit context strings")
        _context(Path(self.config_root), Path(self.state_root))
        validate_transaction_id(self.transaction_id)
        if type(self.action) is not str or self.action not in ACTIONS:
            raise ValueError("Unknown recovery action")
        for value in (self.private_digest, self.snapshot_id, self.original_review_hash):
            validate_digest(value)
        scoped_review.validate_recorded_review(self.plan)
        if (self.plan.evidence.config_root, self.plan.evidence.state_root) != (
            self.config_root,
            self.state_root,
        ):
            raise ValueError("Draft differs from explicit config/state context")

    def to_json(self) -> str:
        self.__post_init__()
        data = {name: getattr(self, name) for name in self.__dataclass_fields__ if name != "plan"}
        data["plan"] = decode_json(plan_to_json(self.plan))
        text = canonical_json({"schema": 1, "kind": "scoped-recovery-draft", **data})
        decode_json(text)
        return text

    @classmethod
    def from_json(cls, text: str) -> "ScopedRecoveryDraft":
        data = fields(decode_json(text), {"schema", "kind", *cls.__dataclass_fields__}).copy()
        schema = data.pop("schema")
        if type(schema) is not int or schema != 1 or data.pop("kind") != "scoped-recovery-draft":
            raise ValueError("Unknown recovery draft format")
        data["plan"] = plan_from_json(canonical_json(data["plan"]))
        return cls(**data)


def _prepare(config_root: Path, state_root: Path, txid: str, action: str) -> ScopedRecoveryDraft:
    _context(config_root, state_root)
    validate_transaction_id(txid)
    if action not in ACTIONS:
        raise ValueError("Unknown recovery action")
    before = store.verified_fingerprint_digest(store.load_transaction(state_root, txid))
    review = publication.review_recovery(state_root, txid, action, config_root=config_root)
    bundle = store.load_transaction(state_root, txid)
    after = store.verified_fingerprint_digest(bundle)
    if before != after or store.verified_fingerprint(bundle) != review.private_fingerprint:
        raise ValueError("Private evidence changed during preparation")
    return ScopedRecoveryDraft(
        str(config_root),
        str(state_root),
        txid,
        action,
        after,
        bundle.snapshot.snapshot_id,
        bundle.snapshot.plan.review_hash,
        review.plan,
    )


def _run(
    config_root: Path,
    state_root: Path,
    operation: str,
    args: list[str],
    cancel_event: threading.Event | None,
    timeout: float,
    limit: int,
) -> str:
    _context(config_root, state_root)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Expected finite positive timeout")
    result = health.run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.scoped_recovery",
            operation,
            "--config-root",
            str(config_root),
            "--state-root",
            str(state_root),
            *args,
        ],
        timeout=timeout,
        max_bytes=limit,
        process_group=True,
        cancel_event=cancel_event,
        cwd=Path(__file__).absolute().parents[2],
    )
    if result.returncode:
        raise ValueError(f"Read-only recovery worker refused: {result.stderr[:4096].strip()}")
    return result.stdout


def run_assess(
    config_root: Path,
    state_root: Path,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 15,
) -> LayoutAssessment:
    result = LayoutAssessment.from_json(
        _run(config_root, state_root, "assess", [], cancel_event, timeout, MAX_ASSESS_BYTES)
    )
    if (result.config_root, result.state_root) != (str(config_root), str(state_root)):
        raise ValueError("Worker returned different config/state context")
    return result


def run_prepare_action(
    config_root: Path,
    state_root: Path,
    txid: str,
    action: str,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> ScopedRecoveryDraft:
    validate_transaction_id(txid)
    if action not in ACTIONS:
        raise ValueError("Unknown recovery action")
    draft = ScopedRecoveryDraft.from_json(
        _run(
            config_root,
            state_root,
            "prepare",
            ["--txid", txid, "--action", action],
            cancel_event,
            timeout,
            MAX_RECORD_BYTES,
        )
    )
    if (draft.config_root, draft.state_root, draft.transaction_id, draft.action) != (
        str(config_root),
        str(state_root),
        txid,
        action,
    ):
        raise ValueError("Worker returned different recovery context/action")
    return draft


def commit_action(
    draft: ScopedRecoveryDraft, *, cancel_event: threading.Event | None = None
) -> publication.PublicationResult:
    """Direct mutator. Caller owns non-daemon worker lifetime and independent sticky flags."""
    try:
        if threading.current_thread().daemon:
            raise ValueError("Recovery commit requires a non-daemon worker")
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Recovery cancelled before delegation")
        checked = ScopedRecoveryDraft.from_json(draft.to_json())
        review = publication.review_recovery(
            Path(checked.state_root),
            checked.transaction_id,
            checked.action,
            config_root=Path(checked.config_root),
        )
        bundle = store.load_transaction(Path(checked.state_root), checked.transaction_id)
        if (
            store.verified_fingerprint_digest(bundle) != checked.private_digest
            or store.verified_fingerprint(bundle) != review.private_fingerprint
            or bundle.snapshot.snapshot_id != checked.snapshot_id
            or bundle.snapshot.plan.review_hash != checked.original_review_hash
            or review.plan.review_hash != checked.plan.review_hash
            or review.plan.scopes != checked.plan.scopes
            or review.plan.changed_scopes != checked.plan.changed_scopes
            or review.plan.evidence.evidence_hash != checked.plan.evidence.evidence_hash
        ):
            raise ValueError("Recovery draft is stale or changed; prepare a fresh action")
    except (OSError, ValueError, RuntimeError) as exc:
        return publication.PublicationResult(
            draft.transaction_id, "failed", True, False, False, _note(exc)
        )
    # Do not wrap or reinterpret backend outcomes: its uncertainty flags are sticky.
    return publication.commit_recovery(review, cancel_event=cancel_event)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only scoped recovery worker")
    parser.add_argument("operation", choices=("assess", "prepare"))
    parser.add_argument("--config-root", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--txid")
    parser.add_argument("--action", choices=ACTIONS)
    args = parser.parse_args()
    try:
        if args.operation == "assess":
            if args.txid is not None or args.action is not None:
                raise ValueError("Assessment does not accept recovery action arguments")
            print(assess_layout(args.config_root, args.state_root).to_json())
        else:
            if args.txid is None or args.action is None:
                raise ValueError("Preparation requires transaction ID and action")
            print(_prepare(args.config_root, args.state_root, args.txid, args.action).to_json())
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{_note(error)}\n")
