"""Canonical scope restore review and explicit backend commit. Invoke off GTK.

Terminal phase and private digest are local observations, not authentication or
proof either historical side was installed. A draft is never a write permit.
Only read-only listing and preparation have isolated worker entry points.
"""

import argparse
import math
import sys
import threading
from dataclasses import asdict, dataclass, is_dataclass, replace
from dataclasses import fields as dataclass_fields
from pathlib import Path
from types import UnionType
from typing import Literal, get_args, get_origin, get_type_hints

from hyprmod.core import (
    health,
    layout_guard,
    route_approval,
    scoped_backups,
    scoped_config,
    scoped_review,
    transaction_store,
)
from hyprmod.core import transaction_publication as publication
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

MAX_LIST_BYTES = 1024 * 1024
MAX_SOURCE_TRANSACTIONS = 32


def _notes(value: tuple[str, ...]) -> None:
    if type(value) is not tuple or len(value) > 16:
        raise ValueError("Expected at most 16 immutable diagnostic notes")
    try:
        if any(type(n) is not str or not 1 <= len(n.encode("utf-8")) <= 1024 for n in value):
            raise ValueError("Expected nonempty notes bounded to 1024 UTF-8 bytes")
    except UnicodeError as exc:
        raise ValueError("Expected UTF-8 notes") from exc


def _reason(error: Exception) -> tuple[str, ...]:
    text = str(error).encode("utf-8", "replace")[:1024].decode("utf-8", "ignore")
    return (text or "Evidence inspection refused",)


@dataclass(frozen=True, slots=True)
class RestoreSourceRow:
    scope: Scope
    side: str
    descriptor: BackupDescriptor

    def __post_init__(self) -> None:
        if (
            type(self.scope) is not Scope
            or type(self.side) is not str
            or self.side not in ("prior", "proposed")
        ):
            raise ValueError("Expected Scope and prior/proposed side")
        if type(self.descriptor) is not BackupDescriptor:
            raise ValueError("Expected backup descriptor")
        self.descriptor.__post_init__()
        if self.descriptor.kind != "scoped-v2" or self.descriptor.scope is not self.scope:
            raise ValueError("Expected matching canonical v2 scoped descriptor")


@dataclass(frozen=True, slots=True)
class RestoreTransactionRow:
    transaction_id: str
    validity: str
    phase: Phase | None
    eligibility: str
    notes: tuple[str, ...]
    sources: tuple[RestoreSourceRow, ...]

    def __post_init__(self) -> None:
        validate_transaction_id(self.transaction_id)
        _notes(self.notes)
        if type(self.validity) is not str or self.validity not in ("verified", "invalid"):
            raise ValueError("Unknown transaction validity")
        if type(self.eligibility) is not str or self.eligibility not in ("reviewable", "blocked"):
            raise ValueError("Unknown source eligibility")
        if type(self.sources) is not tuple:
            raise ValueError("Expected immutable sources")
        if self.validity == "invalid":
            if (
                self.phase is not None
                or self.sources
                or self.eligibility != "blocked"
                or not self.notes
            ):
                raise ValueError("Invalid transaction must be blocked without phase or sources")
            return
        if type(self.phase) is not Phase:
            raise ValueError("Expected verified phase")
        if len(self.sources) != 4:
            raise ValueError("Expected all four historical sources")
        for source, expected in zip(
            self.sources, ((s, side) for s in Scope for side in ("prior", "proposed")), strict=True
        ):
            if type(source) is not RestoreSourceRow:
                raise ValueError("Expected restore source row")
            source.__post_init__()
            if (source.scope, source.side) != expected:
                raise ValueError("Expected fixed scope/side source order")
        if self.eligibility == "reviewable" and self.phase not in (Phase.COMMITTED, Phase.ABORTED):
            raise ValueError("Reviewable source must be terminal")
        if self.eligibility == "blocked" and not self.notes:
            raise ValueError("Blocked transaction requires a reason")


@dataclass(frozen=True, slots=True)
class ScopedRestoreListing:
    config_root: str
    state_root: str
    status: str
    scan_complete: bool
    truncated: bool
    transactions: tuple[RestoreTransactionRow, ...]
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.config_root) is not str or type(self.state_root) is not str:
            raise ValueError("Expected explicit context strings")
        layout_guard.validate_context(Path(self.config_root))
        layout_guard.validate_context(Path(self.state_root))
        if type(self.status) is not str or self.status not in ("observed", "blocked"):
            raise ValueError("Unknown listing status")
        if type(self.scan_complete) is not bool or type(self.truncated) is not bool:
            raise ValueError("Expected boolean scan flags")
        if not self.scan_complete and self.status != "blocked":
            raise ValueError("Incomplete scan must block listing")
        _notes(self.notes)
        if self.status == "blocked" and not self.notes:
            raise ValueError("Blocked listing requires a reason")
        if type(self.transactions) is not tuple or len(self.transactions) > MAX_SOURCE_TRANSACTIONS:
            raise ValueError("Expected bounded immutable transaction rows")
        ids = []
        for row in self.transactions:
            if type(row) is not RestoreTransactionRow:
                raise ValueError("Expected restore transaction row")
            row.__post_init__()
            ids.append(row.transaction_id)
            if self.status == "blocked" and row.eligibility != "blocked":
                raise ValueError("Globally blocked listing cannot offer reviewable sources")
            if self.status == "observed" and (
                row.validity != "verified" or row.phase not in (Phase.COMMITTED, Phase.ABORTED)
            ):
                raise ValueError("Observed listing requires complete terminal journal verification")
        if ids != sorted(set(ids)):
            raise ValueError("Expected sorted unique transaction IDs")
        if self.truncated and len(ids) != MAX_SOURCE_TRANSACTIONS:
            raise ValueError("Truncated listing requires a full display page")
        if (
            len(
                canonical_json(
                    {"schema": 1, "kind": "scoped-restore-listing", **asdict(self)}
                ).encode("ascii")
            )
            > MAX_LIST_BYTES
        ):
            raise ValueError("Listing exceeds 1 MiB transport limit")

    def to_json(self) -> str:
        self.__post_init__()
        text = canonical_json({"schema": 1, "kind": "scoped-restore-listing", **asdict(self)})
        decode_json(text)
        return text

    @classmethod
    def from_json(cls, text: str) -> "ScopedRestoreListing":
        try:
            if type(text) is not str or len(text.encode("utf-8")) > MAX_LIST_BYTES:
                raise ValueError("Listing exceeds 1 MiB transport limit")
            data = fields(decode_json(text), {"schema", "kind", *cls.__dataclass_fields__}).copy()
            if len(canonical_json(data).encode("ascii")) > MAX_LIST_BYTES:
                raise ValueError("Listing exceeds 1 MiB transport limit")
            schema = data.pop("schema")
            if (
                type(schema) is not int
                or schema != 1
                or data.pop("kind") != "scoped-restore-listing"
            ):
                raise ValueError("Unknown restore listing format")
            if type(data["notes"]) is not list or type(data["transactions"]) is not list:
                raise ValueError("Expected note and transaction arrays")
            if len(data["transactions"]) > MAX_SOURCE_TRANSACTIONS:
                raise ValueError("Too many transaction rows")
            rows = []
            for value in data["transactions"]:
                row = fields(value, set(RestoreTransactionRow.__dataclass_fields__)).copy()
                if type(row["notes"]) is not list or type(row["sources"]) is not list:
                    raise ValueError("Expected note and source arrays")
                if row["phase"] is not None:
                    if type(row["phase"]) is not str:
                        raise ValueError("Expected phase string")
                    row["phase"] = Phase(row["phase"])
                sources = []
                if len(row["sources"]) > 4:
                    raise ValueError("Too many historical sources")
                for value in row["sources"]:
                    source = fields(value, set(RestoreSourceRow.__dataclass_fields__)).copy()
                    descriptor = fields(
                        source["descriptor"], set(BackupDescriptor.__dataclass_fields__)
                    ).copy()
                    if (
                        type(source["scope"]) is not str
                        or type(descriptor["scope"]) is not str
                        or type(descriptor["counts"]) is not list
                    ):
                        raise ValueError("Expected scoped descriptor and count array")
                    source["scope"] = Scope(source["scope"])
                    descriptor["scope"] = Scope(descriptor["scope"])
                    descriptor["counts"] = tuple(descriptor["counts"])
                    source["descriptor"] = BackupDescriptor(**descriptor)
                    sources.append(RestoreSourceRow(**source))
                row["notes"] = tuple(row["notes"])
                row["sources"] = tuple(sources)
                rows.append(RestoreTransactionRow(**row))
            data["notes"] = tuple(data["notes"])
            data["transactions"] = tuple(rows)
            return cls(**data)
        except (TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as exc:
            raise ValueError("Invalid restore listing") from exc


def list_sources(config_root: Path, state_root: Path) -> ScopedRestoreListing:
    """Observe bounded historical choices, never publication proof or restore authority."""
    layout_guard.validate_context(config_root)
    layout_guard.validate_context(state_root)
    notes: tuple[str, ...] = ()
    complete = True
    try:
        ids = transaction_store.refuse_pending_readonly(state_root)
    except (OSError, ValueError, RuntimeError) as exc:
        complete = False
        notes = _reason(exc)
        try:
            ids = transaction_store.list_transaction_ids(state_root)
        except (OSError, ValueError, RuntimeError):
            ids = ()
    current = None
    try:
        current = route_approval.inspect_installation(
            config_root / "attune/installation.json", config_root=config_root, state_root=state_root
        )
    except (OSError, ValueError, RuntimeError) as exc:
        notes = notes or _reason(exc)
    rows = []
    fingerprints = {}
    for txid in ids[:MAX_SOURCE_TRANSACTIONS]:
        try:
            source = transaction_store.load_transaction(state_root, txid)
            fingerprints[txid] = transaction_store.verified_fingerprint_digest(source)
            sources = tuple(
                RestoreSourceRow(scope, side, _selected(source.snapshot, scope, side)[1])
                for scope in Scope
                for side in ("prior", "proposed")
            )
            reason = notes
            if not reason and current is not None:
                try:
                    _same_install(source.snapshot.plan.evidence, current)
                except ValueError as exc:
                    reason = _reason(exc)
            if source.intent.phase not in (Phase.COMMITTED, Phase.ABORTED):
                reason = reason or ("Restore source must be terminal",)
            rows.append(
                RestoreTransactionRow(
                    txid,
                    "verified",
                    source.intent.phase,
                    "blocked" if reason else "reviewable",
                    reason,
                    sources,
                )
            )
        except (OSError, ValueError, RuntimeError) as exc:
            reason = _reason(exc)
            rows.append(RestoreTransactionRow(txid, "invalid", None, "blocked", reason, ()))
            notes = notes or reason
    try:
        if transaction_store.refuse_pending_readonly(state_root) != ids:
            raise ValueError("Transaction IDs changed during listing")
    except (OSError, ValueError, RuntimeError) as exc:
        complete = False
        notes = notes or _reason(exc)
    try:
        for txid, fingerprint in fingerprints.items():
            fresh = transaction_store.load_transaction(state_root, txid)
            if transaction_store.verified_fingerprint_digest(fresh) != fingerprint:
                raise ValueError("Source private evidence changed during listing")
        if current is not None:
            route_approval.revalidate(current)
    except (OSError, ValueError, RuntimeError) as exc:
        notes = notes or _reason(exc)
    if notes:
        rows = [replace(row, eligibility="blocked", notes=row.notes or notes) for row in rows]
    result = ScopedRestoreListing(
        str(config_root),
        str(state_root),
        "blocked" if notes else "observed",
        complete,
        len(ids) > MAX_SOURCE_TRANSACTIONS,
        tuple(rows),
        notes,
    )
    result.to_json()
    return result


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


def commit_restore(
    draft: ScopedRestoreDraft, *, cancel_event: threading.Event | None = None
) -> publication.PublicationResult:
    """Commit directly; caller owns the non-daemon worker lifetime and sticky flags."""
    try:
        if threading.current_thread().daemon:
            raise ValueError("Restore commit requires a non-daemon worker")
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Restore cancelled before delegation")
        if type(draft) is not ScopedRestoreDraft:
            raise ValueError("Expected exact ScopedRestoreDraft")

        def immutable(value: object, expected: object) -> None:
            if get_origin(expected) is Literal:
                expected = type(get_args(expected)[0])
            if get_origin(expected) is UnionType:
                if value is None and type(None) in get_args(expected):
                    return
                expected = next(t for t in get_args(expected) if t is not type(None))
            if get_origin(expected) is tuple:
                if type(value) is not tuple:
                    raise ValueError("Expected original immutable restore tuple")
                for item in value:
                    immutable(item, get_args(expected)[0])
                return
            if type(value) is not expected:
                raise ValueError("Expected exact original restore field type")
            if not is_dataclass(value):
                return
            hints = get_type_hints(type(value))
            for field in dataclass_fields(value):
                immutable(getattr(value, field.name), hints[field.name])

        # JSON normalization must not conceal mutable containers in the original DTO.
        immutable(draft, ScopedRestoreDraft)
        draft.__post_init__()
        checked = ScopedRestoreDraft.from_json(draft.to_json())
    except (OSError, ValueError, RuntimeError, TypeError, AttributeError, RecursionError) as exc:
        return publication.PublicationResult(None, "failed", False, False, False, str(exc))

    def expected_source() -> None:
        source = transaction_store.load_transaction(
            Path(checked.state_root), checked.transaction_id
        )
        if (
            transaction_store.verified_fingerprint_digest(source) != checked.source_private_digest
            or source.intent.phase is not checked.source_phase
            or source.snapshot.snapshot_id != checked.source_snapshot_id
            or source.snapshot != checked.source_snapshot
        ):
            raise ValueError("Restore source changed; prepare a fresh review")
        _same_install(source.snapshot.plan.evidence, checked.plan.evidence)
        text, descriptor = _selected(source.snapshot, checked.scope, checked.side)
        selected = next(r for r in checked.plan.scopes if r.scope is checked.scope)
        if (
            descriptor != checked.selected_descriptor
            or text != selected.proposed_text
            or not any(
                b.scope is checked.scope
                and b.sha256 == descriptor.sha256
                and b.raw == text.encode("utf-8")
                for b in source.blobs
            )
        ):
            raise ValueError("Selected historical evidence changed")

    return publication.publish_reviewed(
        checked.plan,
        state_root=Path(checked.state_root),
        config_root=Path(checked.config_root),
        cancel_event=cancel_event,
        expected_source=expected_source,
    )


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
            "prepare",
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


def run_list(
    config_root: Path,
    state_root: Path,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> ScopedRestoreListing:
    layout_guard.validate_context(config_root)
    layout_guard.validate_context(state_root)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Expected finite positive timeout")
    result = health.run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.scoped_restore",
            "list",
            "--config-root",
            str(config_root),
            "--state-root",
            str(state_root),
        ],
        timeout=timeout,
        max_bytes=MAX_LIST_BYTES,
        process_group=True,
        cancel_event=cancel_event,
        cwd=Path(__file__).absolute().parents[2],
    )
    if result.returncode:
        raise ValueError(f"Read-only listing worker refused: {result.stderr[:4096].strip()}")
    listing = ScopedRestoreListing.from_json(result.stdout)
    if (listing.config_root, listing.state_root) != (str(config_root), str(state_root)):
        raise ValueError("Worker returned different listing context")
    return listing


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only scope restore worker")
    modes = parser.add_subparsers(dest="mode", required=True)
    listing_parser = modes.add_parser("list")
    prepare_parser = modes.add_parser("prepare")
    for mode in (listing_parser, prepare_parser):
        mode.add_argument("--config-root", required=True, type=Path)
        mode.add_argument("--state-root", required=True, type=Path)
    prepare_parser.add_argument("--txid", required=True)
    prepare_parser.add_argument("--scope", required=True, type=Scope, choices=tuple(Scope))
    prepare_parser.add_argument("--side", required=True, choices=("prior", "proposed"))
    args = parser.parse_args()
    try:
        if args.mode == "list":
            print(list_sources(args.config_root, args.state_root).to_json())
        else:
            print(
                prepare_restore(
                    args.config_root, args.state_root, args.txid, args.scope, args.side
                ).to_json()
            )
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(
            1, f"{str(error).encode('utf-8', 'replace')[:4096].decode('utf-8', 'ignore')}\n"
        )
