"""Explicit private evidence storage only. No output publication or journal advancement.

Failures may leave partial/orphan evidence. Nothing here repairs or removes it.
Checks narrow local filesystem races; they are not hostile-filesystem isolation.
"""

import fcntl
import hashlib
import os
import secrets
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from hyprmod.core import persistence, scoped_config, scoped_review
from hyprmod.core.route_approval import PathFact
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import (
    MAX_RECORD_BYTES,
    GroupSnapshot,
    Phase,
    TransactionIntent,
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


def _publish(binding: StoreBinding, path: Path, raw: bytes) -> None:
    revalidate_store(binding)
    _directory(path.parent, private=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
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
    with os.scandir(directory) as children:
        first = next(children, None)
        if first is None or first.name != "intent.json" or next(children, None) is not None:
            raise ValueError("Incomplete or unknown transaction directory")
    intent_raw = _read(binding, directory / "intent.json", MAX_RECORD_BYTES)
    data = fields(
        decode_json(intent_raw.decode("utf-8")),
        {"schema", "kind", *TransactionIntent.__dataclass_fields__},
    )
    snapshot_id = validate_digest(data["snapshot_id"])
    snapshot_raw = _read(
        binding, root / "snapshots" / (snapshot_id + ".json"), MAX_RECORD_BYTES - len(intent_raw)
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
            raw = _read(
                binding,
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
    return VerifiedTransaction(intent, snapshot, tuple(blobs), binding)


def _pending(binding: StoreBinding) -> None:
    root = binding.state_root / "attune/transactions"
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_JOURNALS:
                raise ValueError("Journal scan exceeds 1000 entries")
            validate_transaction_id(entry.name)
            verified = load_transaction(binding.state_root, entry.name)
            if verified.intent.phase not in (Phase.COMMITTED, Phase.ABORTED):
                raise ValueError("Unresolved prior transaction blocks preparation")


def prepare_transaction(
    plan: scoped_review.GroupReviewPlan,
    *,
    state_root: Path,
    transaction_id: str | None = None,
    cancel_event: threading.Event | None = None,
) -> PreparedEvidence | None:
    """Persist prepared/empty-progress evidence only; partial writes may remain on failure."""
    scoped_review.validate_recorded_review(plan)
    if not isinstance(state_root, Path) or str(state_root) != plan.evidence.state_root:
        raise ValueError("Explicit state context differs from review")
    if transaction_id is not None:
        validate_transaction_id(transaction_id)

    def check() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Evidence preparation cancelled")

    check()
    if not plan.changed_scopes:
        scoped_review.revalidate_review(plan)
        check()
        return None
    binding = inspect_store(state_root)
    root = state_root / "attune"
    lock_path = root / "persistence.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "a+b") as lock:
        if _signature(os.fstat(lock.fileno())) != _signature(_file_info(lock_path)):
            raise ValueError("Unsafe or changed persistence lock")
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            check()
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Persistence lock timed out") from None
                time.sleep(0.05)
        check()
        revalidate_store(binding)
        if _signature(os.fstat(lock.fileno())) != _signature(_file_info(lock_path)):
            raise ValueError("Persistence lock changed while waiting")
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
