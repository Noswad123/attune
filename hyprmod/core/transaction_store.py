"""Explicit private evidence storage and locked metadata checkpoints, never outputs.

Failures may leave partial/orphan evidence. Nothing here repairs or removes it.
Checks narrow local filesystem races; they are not hostile-filesystem isolation.
"""

import fcntl
import hashlib
import os
import re
import secrets
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from hyprmod.core import persistence, scoped_config, scoped_review
from hyprmod.core.route_approval import PathFact
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import (
    MAX_RECORD_BYTES,
    GroupSnapshot,
    Phase,
    RollbackCheckpoint,
    RollbackOperation,
    TransactionIntent,
    canonical_json,
    decode_json,
    fields,
    validate_digest,
    validate_transaction_id,
)

MAX_JOURNALS = 1000
LOCK_TIMEOUT = 5.0


@dataclass(frozen=True, slots=True)
class StoreBinding:
    state_root: Path
    directories: tuple[PathFact, ...]


@dataclass(frozen=True, slots=True)
class VerifiedBlob:
    scope: Scope
    sha256: str
    raw: bytes


@dataclass(frozen=True, slots=True)
class VerifiedTransaction:
    intent: TransactionIntent
    snapshot: GroupSnapshot
    blobs: tuple[VerifiedBlob, ...]
    binding: StoreBinding
    rollback: RollbackOperation | None = None
    rollback_checkpoint: RollbackCheckpoint | None = None
    private_facts: tuple = ()


# Preparation returns exactly the same verified, read-only evidence as loading.
PreparedEvidence = VerifiedTransaction


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


def _directory(path: Path, *, private: bool) -> PathFact:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or (
            stat.S_IMODE(info.st_mode) != 0o700
            if private
            else bool(info.st_mode & 0o7022) or info.st_mode & 0o300 != 0o300
        )
    ):
        raise ValueError(
            f"Expected safe owned {'0700 private ' if private else ''}directory: {path}"
        )
    try:
        (path / ".git").lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValueError(f"Private evidence must be outside Git: {path}")
    return PathFact(str(path), _identity(info))


def _state(state_root: Path) -> Path:
    if (
        not isinstance(state_root, Path)
        or not state_root.is_absolute()
        or str(state_root) != os.path.normpath(str(state_root))
        or len(str(state_root).encode()) > 4096
        or len(state_root.parts) > 128
    ):
        raise ValueError("Expected explicit normalized absolute state_root")
    root = state_root / "attune"
    # Check ancestors and Git markers before creating any children. lstat catches
    # dangling markers and never treats an unreadable marker as absence.
    for path in reversed((state_root, *state_root.parents)):
        info = path.lstat()
        sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in (0, os.getuid())
            or (info.st_mode & 0o022 and not sticky_root)
        ):
            raise ValueError(f"Unsafe state ancestor: {path}")
    _directory(state_root, private=False)
    try:
        root.lstat()
    except FileNotFoundError:
        pass
    else:
        _directory(root, private=True)
    for path in (root, *root.parents):
        try:
            (path / ".git").lstat()
        except FileNotFoundError:
            continue
        raise ValueError(f"Private evidence must be outside Git: {path}")
    return root


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def initialize_store(state_root: Path) -> StoreBinding:
    """Explicit provisioning; call BEFORE inspecting routes and building a review."""
    root = _state(state_root)
    for path in (root, *(root / name for name in ("blobs", "snapshots", "transactions"))):
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _directory(path, private=True)
        _sync_directory(path)
        _sync_directory(path.parent)
    return inspect_store(state_root)


def inspect_store(state_root: Path) -> StoreBinding:
    """Read-only root binding; directory timestamps deliberately do not participate."""
    root = _state(state_root)
    try:
        directories = (_directory(state_root, private=False),) + tuple(
            _directory(path, private=True)
            for path in (root, *(root / n for n in ("blobs", "snapshots", "transactions")))
        )
    except FileNotFoundError as exc:
        raise ValueError(
            "Missing private store; explicitly initialize BEFORE route review"
        ) from exc
    return StoreBinding(state_root, directories)


def revalidate_store(binding: StoreBinding) -> None:
    if inspect_store(binding.state_root) != binding:
        raise ValueError("Private store identity changed")


def _file_info(path: Path) -> os.stat_result:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise ValueError(f"Expected private owned single-link 0600 regular file: {path}")
    return info


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (*_identity(info), info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(binding: StoreBinding, path: Path, limit: int) -> bytes:
    revalidate_store(binding)
    if path.parent.parent.name == "transactions":
        _directory(path.parent, private=True)
    before = _file_info(path)
    if before.st_size > limit:
        raise ValueError("Private evidence exceeds read limit")
    raw = persistence.read_stable(path, limit=limit)
    if _signature(before) != _signature(_file_info(path)):
        raise ValueError("Private file changed during read")
    revalidate_store(binding)
    return raw


def _publish(
    binding: StoreBinding, path: Path, raw: bytes, *, reuse_identical: bool = True
) -> None:
    revalidate_store(binding)
    _directory(path.parent, private=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if not reuse_identical:
            raise FileExistsError(f"Checkpoint scratch already exists: {path}") from None
        if _read(binding, path, len(raw)) != raw:
            raise ValueError(f"Immutable evidence collision: {path}") from None
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    if _read(binding, path, len(raw)) != raw:
        raise ValueError("Private evidence verification failed")
    # Reused immutable records must be durable too, including prior failed writes.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if _signature(os.fstat(fd)) != _signature(_file_info(path)):
            raise ValueError("Private evidence changed before sync")
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_directory(path.parent)


def load_transaction(state_root: Path, transaction_id: str) -> VerifiedTransaction:
    """Verify historical evidence, never current outputs or write authority."""
    validate_transaction_id(transaction_id)
    binding = inspect_store(state_root)
    root = state_root / "attune"
    directory = root / "transactions" / transaction_id
    directory_fact = _directory(directory, private=True)
    read_facts = []

    def read_record(path: Path, limit: int) -> bytes:
        identity = _signature(_file_info(path))
        raw = _read(binding, path, limit)
        if _signature(_file_info(path)) != identity:
            raise ValueError("Private record changed during bundle load")
        read_facts.append((str(path), identity, hashlib.sha256(raw).hexdigest()))
        return raw

    names = set()
    with os.scandir(directory) as children:
        for index, child in enumerate(children):
            if index >= MAX_JOURNALS:
                raise ValueError("Transaction entry limit exceeded")
            if re.fullmatch(
                r"\.(intent|rollback|rollback-checkpoint)\.json\.[0-9a-f]{32}\.tmp", child.name
            ):
                # Unpublished scratch is never authority, promoted, or cleaned on load.
                if _file_info(Path(child.path)).st_size > MAX_RECORD_BYTES:
                    raise ValueError("Oversized checkpoint scratch")
            else:
                names.add(child.name)
    if "intent.json" not in names or names - {
        "intent.json",
        "rollback.json",
        "rollback-checkpoint.json",
    }:
        raise ValueError("Incomplete or unknown transaction directory")
    if "rollback-checkpoint.json" in names and "rollback.json" not in names:
        raise ValueError("Orphan rollback checkpoint")
    intent_raw = read_record(directory / "intent.json", MAX_RECORD_BYTES)
    data = fields(
        decode_json(intent_raw.decode("utf-8")),
        {"schema", "kind", *TransactionIntent.__dataclass_fields__},
    )
    snapshot_id = validate_digest(data["snapshot_id"])
    snapshot_raw = read_record(
        root / "snapshots" / (snapshot_id + ".json"), MAX_RECORD_BYTES - len(intent_raw)
    )
    if hashlib.sha256(snapshot_raw).hexdigest() != snapshot_id:
        raise ValueError("Snapshot filename hash mismatch")
    snapshot = GroupSnapshot.from_json(snapshot_raw.decode("utf-8"))
    intent = TransactionIntent.from_json(intent_raw.decode("utf-8"), snapshot=snapshot)
    if intent.transaction_id != transaction_id or snapshot.plan.evidence.state_root != str(
        state_root
    ):
        raise ValueError("Transaction context mismatch")
    budget = MAX_RECORD_BYTES - len(intent_raw) - len(snapshot_raw)
    blobs = []
    for review in snapshot.plan.scopes:
        for digest, text in (
            (review.previous_sha256, review.previous_text),
            (review.proposed_sha256, review.proposed_text),
        ):
            if any(b.sha256 == digest for b in blobs):
                continue
            raw = read_record(
                root / "blobs" / (digest + ".lua"),
                min(scoped_review.MAX_INPUT_BYTES, budget),
            )
            budget -= len(raw)
            if hashlib.sha256(raw).hexdigest() != digest or raw != text.encode("utf-8"):
                raise ValueError("Blob hash or recorded bytes mismatch")
            scoped_config.read_document(raw.decode("utf-8"), expected_scope=review.scope)
            blobs.append(VerifiedBlob(review.scope, digest, raw))
    revalidate_store(binding)
    if _directory(directory, private=True) != directory_fact:
        raise ValueError("Transaction directory identity changed during load")
    rollback = checkpoint = None
    if "rollback.json" in names:
        rollback = RollbackOperation.from_json(
            read_record(directory / "rollback.json", MAX_RECORD_BYTES).decode("ascii"),
            snapshot=snapshot,
        )
        if intent.phase is Phase.COMMITTED:
            raise ValueError("Committed transaction has rollback operation")
        if "rollback-checkpoint.json" in names:
            checkpoint = RollbackCheckpoint.from_json(
                read_record(directory / "rollback-checkpoint.json", MAX_RECORD_BYTES).decode(
                    "ascii"
                ),
                operation=rollback,
            )
        if intent.phase is Phase.ABORTED and (checkpoint is None or not checkpoint.complete):
            raise ValueError("Aborted parent has incomplete rollback")
    bundle = VerifiedTransaction(intent, snapshot, tuple(blobs), binding, rollback, checkpoint)
    facts = _capture_private_facts(bundle)
    if facts != (directory_fact, tuple(read_facts)):
        raise ValueError("Private evidence changed across bundle load")
    return replace(bundle, private_facts=facts)


def _pending(binding: StoreBinding, selected: str | None = None) -> tuple[str, ...]:
    revalidate_store(binding)
    ids = list_transaction_ids(binding.state_root)
    for txid in ids:
        verified = load_transaction(binding.state_root, txid)
        if txid != selected and verified.intent.phase not in (Phase.COMMITTED, Phase.ABORTED):
            raise ValueError("Unresolved prior transaction blocks preparation")
    if list_transaction_ids(binding.state_root) != ids:
        raise ValueError("Transaction listing changed during pending scan")
    revalidate_store(binding)
    return ids


def refuse_pending_readonly(state_root: Path) -> tuple[str, ...]:
    """Verify every bounded journal and refuse pending work without creating a lock."""
    return _pending(inspect_store(state_root))


class StoreSession:
    """Exclusive, bounded-lock session. Construct through exclusive_store_session only."""

    def __init__(self, binding: StoreBinding, fd: int, cancel_event: threading.Event | None):
        self.binding = binding
        self.fd = fd
        self.cancel_event = cancel_event
        self.lock_identity = _signature(os.fstat(fd))

    def check(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise InterruptedError("Transaction cancelled")
        revalidate_store(self.binding)
        path = self.binding.state_root / "attune/persistence.lock"
        if self.lock_identity != _signature(_file_info(path)) or self.lock_identity != _signature(
            os.fstat(self.fd)
        ):
            raise ValueError("Persistence lock identity changed")
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def refuse_other_pending(self, selected: str | None = None) -> None:
        self.check()
        _pending(self.binding, selected)

    def prepare(
        self, plan: scoped_review.GroupReviewPlan, transaction_id: str | None = None
    ) -> PreparedEvidence:
        scoped_review.validate_recorded_review(plan)
        binding = self.binding
        state_root = binding.state_root
        if str(state_root) != plan.evidence.state_root or not plan.changed_scopes:
            raise ValueError("Expected changed plan in explicit store context")
        if transaction_id is not None:
            validate_transaction_id(transaction_id)
        check = self.check
        check()
        root = state_root / "attune"
        scoped_review.revalidate_review(plan)
        _pending(binding)
        snapshot = GroupSnapshot(plan)
        txid = transaction_id if transaction_id is not None else secrets.token_hex(16)
        intent = TransactionIntent(
            txid,
            snapshot.snapshot_id,
            plan.review_hash,
            plan.evidence.registry,
            plan.changed_scopes,
        )
        blobs = {
            digest: text.encode("utf-8")
            for r in plan.scopes
            for digest, text in (
                (r.previous_sha256, r.previous_text),
                (r.proposed_sha256, r.proposed_text),
            )
        }
        snapshot_raw = snapshot.to_json().encode("ascii")
        intent_raw = intent.to_json().encode("ascii")
        if len(snapshot_raw) + len(intent_raw) + sum(map(len, blobs.values())) > MAX_RECORD_BYTES:
            raise ValueError("Transaction exceeds total 8 MiB evidence limit")
        for digest, raw in blobs.items():
            check()
            _publish(binding, root / "blobs" / (digest + ".lua"), raw)
        check()
        _publish(binding, root / "snapshots" / (snapshot.snapshot_id + ".json"), snapshot_raw)
        check()
        for digest, raw in blobs.items():
            if _read(binding, root / "blobs" / (digest + ".lua"), len(raw)) != raw:
                raise ValueError("Blob changed before intent publication")
        if (
            _read(binding, root / "snapshots" / (snapshot.snapshot_id + ".json"), len(snapshot_raw))
            != snapshot_raw
        ):
            raise ValueError("Snapshot changed before intent publication")
        directory = root / "transactions" / txid
        revalidate_store(binding)
        directory.mkdir(mode=0o700)
        _directory(directory, private=True)
        _sync_directory(directory)
        _sync_directory(directory.parent)
        # Recheck the original evidence, never refresh a stale binding away.
        scoped_review.revalidate_review(plan)
        check()
        _publish(binding, directory / "intent.json", intent_raw)
        return load_transaction(state_root, txid)

    def sync_evidence(self, bundle: VerifiedTransaction) -> None:
        self.check()
        before = verified_fingerprint(bundle)
        root = self.binding.state_root / "attune"
        for blob in bundle.blobs:
            _publish(self.binding, root / "blobs" / (blob.sha256 + ".lua"), blob.raw)
        _publish(
            self.binding,
            root / "snapshots" / (bundle.snapshot.snapshot_id + ".json"),
            bundle.snapshot.to_json().encode("ascii"),
        )
        directory = root / "transactions" / bundle.intent.transaction_id
        _publish(self.binding, directory / "intent.json", bundle.intent.to_json().encode("ascii"))
        if bundle.rollback is not None:
            _publish(
                self.binding, directory / "rollback.json", bundle.rollback.to_json().encode("ascii")
            )
        if bundle.rollback_checkpoint is not None:
            _publish(
                self.binding,
                directory / "rollback-checkpoint.json",
                bundle.rollback_checkpoint.to_json().encode("ascii"),
            )
        if (
            verified_fingerprint(
                load_transaction(self.binding.state_root, bundle.intent.transaction_id)
            )
            != before
        ):
            raise ValueError("Private evidence changed during synchronization")

    def checkpoint(
        self,
        expected: VerifiedTransaction,
        record: TransactionIntent | RollbackOperation | RollbackCheckpoint,
        *,
        fingerprint: tuple,
    ) -> VerifiedTransaction:
        self.check()
        state = self.binding.state_root
        txid = expected.intent.transaction_id
        if (
            verified_fingerprint(expected) != fingerprint
            or verified_fingerprint(load_transaction(state, txid)) != fingerprint
        ):
            raise ValueError("Private checkpoint compare failed")
        if isinstance(record, TransactionIntent):
            record.validate_snapshot(expected.snapshot)
            old = expected.intent
            if old.phase in (Phase.COMMITTED, Phase.ABORTED) or record.transaction_id != txid:
                raise ValueError("Terminal or mismatched checkpoint")
            if expected.rollback is not None:
                if (
                    record.phase is not Phase.ABORTED
                    or expected.rollback_checkpoint is None
                    or not expected.rollback_checkpoint.complete
                ):
                    raise ValueError("Rollback direction is locked")
            elif record.phase not in (Phase.PUBLISHING, Phase.COMMITTED, Phase.ABORTED):
                raise ValueError("Illegal journal transition")
            name = "intent.json"
        elif isinstance(record, RollbackOperation):
            record.validate_snapshot(expected.snapshot)
            if expected.rollback is not None or expected.intent.phase in (
                Phase.COMMITTED,
                Phase.ABORTED,
            ):
                raise ValueError("Rollback already exists or parent terminal")
            name = "rollback.json"
        else:
            if expected.rollback is None:
                raise ValueError("Missing rollback operation")
            record.validate_operation(expected.rollback)
            old_checkpoint = expected.rollback_checkpoint
            if old_checkpoint is not None and old_checkpoint.complete:
                raise ValueError("Illegal rollback checkpoint transition")
            name = "rollback-checkpoint.json"
        directory = state / "attune/transactions" / txid
        raw = record.to_json().encode("ascii")
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError("Checkpoint exceeds limit")
        temporary = directory / ("." + name + "." + secrets.token_hex(16) + ".tmp")
        _publish(self.binding, temporary, raw, reuse_identical=False)
        self.check()
        if verified_fingerprint(load_transaction(state, txid)) != fingerprint:
            raise ValueError("Private evidence changed before checkpoint replacement")
        temporary_identity = _signature(_file_info(temporary))
        if _read(self.binding, temporary, MAX_RECORD_BYTES) != raw:
            raise ValueError("Checkpoint scratch changed")
        if _signature(_file_info(temporary)) != temporary_identity:
            raise ValueError("Checkpoint scratch identity changed")
        os.replace(temporary, directory / name)
        _sync_directory(directory)
        loaded = load_transaction(state, txid)
        after = verified_fingerprint(loaded)
        changed_path = str(directory / name)
        if (
            after[1] != fingerprint[1]
            or tuple(f for f in after[2] if f[0] != changed_path)
            != tuple(f for f in fingerprint[2] if f[0] != changed_path)
            or (
                loaded.intent
                if name == "intent.json"
                else loaded.rollback
                if name == "rollback.json"
                else loaded.rollback_checkpoint
            )
            != record
        ):
            raise ValueError("Unrelated private evidence changed during checkpoint")
        return loaded


@contextmanager
def exclusive_store_session(state_root: Path, *, cancel_event: threading.Event | None = None):
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("Transaction cancelled")
    binding = inspect_store(state_root)
    path = state_root / "attune/persistence.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if _signature(os.fstat(fd)) != _signature(_file_info(path)):
            raise ValueError("Unsafe or changed persistence lock")
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Transaction cancelled")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Persistence lock timed out") from None
                time.sleep(0.05)
        session = StoreSession(binding, fd, cancel_event)
        session.check()
        yield session
    finally:
        os.close(fd)


def _capture_private_facts(bundle: VerifiedTransaction) -> tuple:
    root = bundle.binding.state_root / "attune"
    directory = root / "transactions" / bundle.intent.transaction_id
    records = [
        (directory / "intent.json", MAX_RECORD_BYTES),
        (root / "snapshots" / (bundle.snapshot.snapshot_id + ".json"), MAX_RECORD_BYTES),
    ]
    records.extend(
        (root / "blobs" / (b.sha256 + ".lua"), scoped_review.MAX_INPUT_BYTES) for b in bundle.blobs
    )
    if bundle.rollback is not None:
        records.append((directory / "rollback.json", MAX_RECORD_BYTES))
    if bundle.rollback_checkpoint is not None:
        records.append((directory / "rollback-checkpoint.json", MAX_RECORD_BYTES))
    facts = []
    for path, limit in records:
        before = _signature(_file_info(path))
        raw = _read(bundle.binding, path, limit)
        if before != _signature(_file_info(path)):
            raise ValueError("Private evidence changed during fingerprint")
        facts.append((str(path), before, hashlib.sha256(raw).hexdigest()))
    return (_directory(directory, private=True), tuple(facts))


def verified_fingerprint(bundle: VerifiedTransaction) -> tuple:
    """Bind private record identities and exact bytes, excluding unpublished scratch."""
    facts = _capture_private_facts(bundle)
    if facts != bundle.private_facts:
        raise ValueError("Private evidence identity or bytes changed since load")
    return (replace(bundle, private_facts=()), *facts)


def verified_fingerprint_digest(bundle: VerifiedTransaction) -> str:
    """Stable local identity/record-hash transport, never repr or serialized authority."""
    verified_fingerprint(bundle)
    directory, records = bundle.private_facts
    payload = {
        "schema": 1,
        "binding": asdict(bundle.binding),
        "directory": asdict(directory),
        "records": records,
    }
    payload["binding"]["state_root"] = str(bundle.binding.state_root)
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


def list_transaction_ids(state_root: Path) -> tuple[str, ...]:
    """Bounded read-only listing. Unknown/unsafe entries are errors, never skipped."""
    binding = inspect_store(state_root)
    directory = state_root / "attune/transactions"
    before = directory.lstat()
    names = []
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_JOURNALS:
                raise ValueError("Journal scan exceeds 1000 entries")
            validate_transaction_id(entry.name)
            _directory(Path(entry.path), private=True)
            names.append(entry.name)
    revalidate_store(binding)
    if directory.lstat() != before:
        raise ValueError("Transaction listing changed during observation")
    return tuple(sorted(names))


def prepare_transaction(
    plan: scoped_review.GroupReviewPlan,
    *,
    state_root: Path,
    transaction_id: str | None = None,
    cancel_event: threading.Event | None = None,
) -> PreparedEvidence | None:
    """Persist prepared evidence only; partial writes may remain on failure."""
    scoped_review.validate_recorded_review(plan)
    if not isinstance(state_root, Path) or str(state_root) != plan.evidence.state_root:
        raise ValueError("Explicit state context differs from review")
    if transaction_id is not None:
        validate_transaction_id(transaction_id)
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("Evidence preparation cancelled")
    if not plan.changed_scopes:
        scoped_review.revalidate_review(plan)
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Evidence preparation cancelled")
        return None
    with exclusive_store_session(state_root, cancel_event=cancel_event) as session:
        return session.prepare(plan, transaction_id)
