"""Read-only canonical scope restore preparation. Invoke off GTK, even directly.

Terminal phase and private digest are local observations, not authentication or
proof either historical side was installed. A draft is never a write permit.
Only the isolated read-only preparation worker has an entry point here.
"""

import argparse
import math
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from hyprmod.core import (
    health,
    layout_guard,
    route_approval,
    scoped_backups,
    scoped_config,
    scoped_review,
    transaction_store,
)
from hyprmod.core.route_approval import InstallationEvidence
from hyprmod.core.scoped_backups import BackupDescriptor
from hyprmod.core.scoped_review import GroupReviewPlan
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import (
    MAX_RECORD_BYTES,
    GroupSnapshot,
    Phase,
    canonical_json,
    decode_json,
    fields,
    plan_from_json,
    plan_to_json,
    route_binding,
    validate_digest,
    validate_transaction_id,
)


def _request(config_root: Path, state_root: Path, txid: str, scope: Scope, side: str) -> None:
    layout_guard.validate_context(config_root)
    layout_guard.validate_context(state_root)
    validate_transaction_id(txid)
    if type(scope) is not Scope or type(side) is not str or side not in ("prior", "proposed"):
        raise ValueError("Expected Scope and prior/proposed side")


def _same_install(historical: InstallationEvidence, current: InstallationEvidence) -> None:
    if (
        (historical.config_root, historical.state_root) != (current.config_root, current.state_root)
        or historical.registry != current.registry
        or tuple(route_binding(r.file) for r in historical.routes)
        != tuple(route_binding(r.file) for r in current.routes)
    ):
        raise ValueError("Restore requires the same installation registry and both route bindings")


def _selected(snapshot: GroupSnapshot, scope: Scope, side: str) -> tuple[str, BackupDescriptor]:
    review = next(r for r in snapshot.plan.scopes if r.scope is scope)
    text = review.previous_text if side == "prior" else review.proposed_text
    digest = review.previous_sha256 if side == "prior" else review.proposed_sha256
    descriptor = scoped_backups.describe_backup(digest + ".lua", text, expected_scope=scope)
    return text, descriptor


@dataclass(frozen=True, slots=True)
class ScopedRestoreDraft:
    config_root: str
    state_root: str
    transaction_id: str
    scope: Scope
    side: str
    source_private_digest: str
    source_phase: Phase
    source_snapshot_id: str
    source_snapshot: GroupSnapshot
    selected_descriptor: BackupDescriptor
    plan: GroupReviewPlan

    def __post_init__(self) -> None:
        if type(self.config_root) is not str or type(self.state_root) is not str:
            raise ValueError("Expected explicit context strings")
        _request(
            Path(self.config_root),
            Path(self.state_root),
            self.transaction_id,
            self.scope,
            self.side,
        )
        validate_digest(self.source_private_digest)
        validate_digest(self.source_snapshot_id)
        if type(self.source_phase) is not Phase or self.source_phase not in (
            Phase.COMMITTED,
            Phase.ABORTED,
        ):
            raise ValueError("Restore source must be terminal")
        if type(self.source_snapshot) is not GroupSnapshot:
            raise ValueError("Expected historical group snapshot")
        self.source_snapshot.__post_init__()
        if self.source_snapshot.snapshot_id != self.source_snapshot_id:
            raise ValueError("Historical snapshot ID mismatch")
        scoped_review.validate_recorded_review(self.plan)
        if (self.plan.evidence.config_root, self.plan.evidence.state_root) != (
            self.config_root,
            self.state_root,
        ):
            raise ValueError("Draft differs from explicit context")
        _same_install(self.source_snapshot.plan.evidence, self.plan.evidence)
        text, descriptor = _selected(self.source_snapshot, self.scope, self.side)
        if type(self.selected_descriptor) is not BackupDescriptor:
            raise ValueError("Expected selected backup descriptor")
        self.selected_descriptor.__post_init__()
        if self.selected_descriptor != descriptor:
            raise ValueError("Selected descriptor differs from historical bytes")
        for review in self.plan.scopes:
            goal = text if review.scope is self.scope else review.previous_text
            if review.proposed_text != goal:
                raise ValueError("Restore must select exact historical bytes and preserve sibling")

    def to_json(self) -> str:
        self.__post_init__()
        data = {name: getattr(self, name) for name in self.__dataclass_fields__}
        data["source_snapshot"] = decode_json(self.source_snapshot.to_json())
        data["selected_descriptor"] = asdict(self.selected_descriptor)
        data["plan"] = decode_json(plan_to_json(self.plan))
        text = canonical_json({"schema": 1, "kind": "scoped-restore-draft", **data})
        decode_json(text)
        return text

    @classmethod
    def from_json(cls, text: str) -> "ScopedRestoreDraft":
        try:
            data = fields(decode_json(text), {"schema", "kind", *cls.__dataclass_fields__}).copy()
            # Apply the aggregate limit to ASCII-escaped transport, not just UTF-8 input.
            decode_json(canonical_json(data))
            schema = data.pop("schema")
            if type(schema) is not int or schema != 1 or data.pop("kind") != "scoped-restore-draft":
                raise ValueError("Unknown restore draft format")
            if type(data["scope"]) is not str or type(data["source_phase"]) is not str:
                raise ValueError("Expected scope and phase strings")
            data["scope"] = Scope(data["scope"])
            data["source_phase"] = Phase(data["source_phase"])
            data["source_snapshot"] = GroupSnapshot.from_json(
                canonical_json(data["source_snapshot"])
            )
            descriptor = fields(
                data["selected_descriptor"], set(BackupDescriptor.__dataclass_fields__)
            ).copy()
            if type(descriptor["counts"]) is not list or type(descriptor["scope"]) is not str:
                raise ValueError("Expected scoped descriptor and count array")
            descriptor["scope"] = Scope(descriptor["scope"])
            descriptor["counts"] = tuple(descriptor["counts"])
            data["selected_descriptor"] = BackupDescriptor(**descriptor)
            data["plan"] = plan_from_json(canonical_json(data["plan"]))
            return cls(**data)
        except (TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as exc:
            raise ValueError("Invalid restore draft") from exc


def prepare_restore(
    config_root: Path, state_root: Path, txid: str, scope: Scope, side: str
) -> ScopedRestoreDraft:
    """Observe CURRENT -> GOAL without snapshots, locks, compilation or publication."""
    _request(config_root, state_root, txid, scope, side)
    ids = transaction_store.refuse_pending_readonly(state_root)
    source = transaction_store.load_transaction(state_root, txid)
    fingerprint = transaction_store.verified_fingerprint_digest(source)
    if source.intent.phase not in (Phase.COMMITTED, Phase.ABORTED):
        raise ValueError("Restore source must be terminal")
    text, descriptor = _selected(source.snapshot, scope, side)
    if not any(
        b.scope is scope and b.sha256 == descriptor.sha256 and b.raw == text.encode("utf-8")
        for b in source.blobs
    ):
        raise ValueError("Selected historical blob missing")
    current = route_approval.inspect_installation(
        config_root / "attune/installation.json", config_root=config_root, state_root=state_root
    )
    _same_install(source.snapshot.plan.evidence, current)
    model = scoped_config.read_document(text, expected_scope=scope)
    if type(model) is not scoped_config.ScopedConfig:
        raise ValueError("Expected canonical scoped source")
    plan = scoped_review.build_review(current, {scope: model})
    if transaction_store.refuse_pending_readonly(state_root) != ids:
        raise ValueError("Transaction IDs changed during preparation")
    fresh = transaction_store.load_transaction(state_root, txid)
    if transaction_store.verified_fingerprint_digest(fresh) != fingerprint:
        raise ValueError("Source private evidence changed during preparation")
    draft = ScopedRestoreDraft(
        str(config_root),
        str(state_root),
        txid,
        scope,
        side,
        fingerprint,
        source.intent.phase,
        source.snapshot.snapshot_id,
        source.snapshot,
        descriptor,
        plan,
    )
    draft.to_json()
    scoped_review.revalidate_review(plan)
    return draft


def run_prepare(
    config_root: Path,
    state_root: Path,
    txid: str,
    scope: Scope,
    side: str,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> ScopedRestoreDraft:
    _request(config_root, state_root, txid, scope, side)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Expected finite positive timeout")
    result = health.run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.scoped_restore",
            "--config-root",
            str(config_root),
            "--state-root",
            str(state_root),
            "--txid",
            txid,
            "--scope",
            scope.value,
            "--side",
            side,
        ],
        timeout=timeout,
        max_bytes=MAX_RECORD_BYTES,
        process_group=True,
        cancel_event=cancel_event,
        cwd=Path(__file__).absolute().parents[2],
    )
    if result.returncode:
        raise ValueError(f"Read-only restore worker refused: {result.stderr[:4096].strip()}")
    draft = ScopedRestoreDraft.from_json(result.stdout)
    if (draft.config_root, draft.state_root, draft.transaction_id, draft.scope, draft.side) != (
        str(config_root),
        str(state_root),
        txid,
        scope,
        side,
    ):
        raise ValueError("Worker returned different restore context/selection")
    return draft


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only scope restore worker")
    parser.add_argument("--config-root", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--txid", required=True)
    parser.add_argument("--scope", required=True, choices=tuple(Scope))
    parser.add_argument("--side", required=True, choices=("prior", "proposed"))
    args = parser.parse_args()
    try:
        print(
            prepare_restore(
                args.config_root, args.state_root, args.txid, Scope(args.scope), args.side
            ).to_json()
        )
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(
            1, f"{str(error).encode('utf-8', 'replace')[:4096].decode('utf-8', 'ignore')}\n"
        )
