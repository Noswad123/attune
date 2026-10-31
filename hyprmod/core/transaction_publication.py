"""Explicit disk publication with reviewed recovery, not split editor activation.

Call mutators on a non-daemon worker, never a killable child. Lock acquisition is
bounded to five seconds and each compile check to ten seconds; filesystem work
has no hard total deadline. Callers must invalidate editors on success or any
scope/journal uncertainty, including failures. Hashes bind local
observations, not authentication. Separate renames are not pair-atomic.
"""

import hashlib
import os
import secrets
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from hyprmod.core import persistence, route_approval, scoped_config, scoped_review
from hyprmod.core import transaction_inspection as inspection
from hyprmod.core import transaction_store as store
from hyprmod.core.scoped_review import GroupReviewPlan
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import (
    Phase,
    RollbackCheckpoint,
    RollbackOperation,
    route_binding,
    validate_transaction_id,
)


@dataclass(frozen=True, slots=True)
class PublicationResult:
    transaction_id: str | None
    outcome: str
    pending: bool
    scope_may_have_changed: bool
    journal_may_have_changed: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryReview:
    state_root: Path
    config_root: Path
    transaction_id: str
    action: str
    plan: GroupReviewPlan
    private_fingerprint: tuple


def review_recovery(
    state_root: Path, txid: str, action: str, *, config_root: Path
) -> RecoveryReview:
    """Read-only exact CURRENT-to-GOAL review; every attempt needs a fresh object."""
    if action not in ("resume", "rollback", "finalize", "abandon"):
        raise ValueError("Unknown recovery action")
    bundle = store.load_transaction(state_root, txid)
    fingerprint = store.verified_fingerprint(bundle)
    if bundle.intent.phase in (Phase.COMMITTED, Phase.ABORTED):
        raise ValueError("Terminal transaction cannot be replayed")
    observation = inspection.classify_transaction(state_root, txid, config_root=config_root)
    if observation.status is inspection.OverallStatus.CONFLICT:
        raise ValueError("Recovery conflict: " + "; ".join(observation.notes))
    if bundle.rollback is not None:
        if action != "rollback":
            raise ValueError("Rollback direction is locked")
    elif (
        (action == "abandon" and observation.status is not inspection.OverallStatus.ALL_PRIOR)
        or (
            action == "finalize" and observation.status is not inspection.OverallStatus.ALL_PROPOSED
        )
        or (action == "resume" and observation.status is inspection.OverallStatus.ALL_PROPOSED)
        or (action == "rollback" and observation.status is inspection.OverallStatus.ALL_PRIOR)
    ):
        raise ValueError("Action is not allowed for actual current group")
    current = route_approval.inspect_installation(
        config_root / "attune/installation.json", config_root=config_root, state_root=state_root
    )
    if current.evidence_hash != observation.current_evidence_hash:
        raise ValueError("Installation changed during recovery review")
    proposals = {}
    for original in bundle.snapshot.plan.scopes:
        text = (
            original.previous_text if action in ("rollback", "abandon") else original.proposed_text
        )
        document = scoped_config.read_document(text, expected_scope=original.scope)
        if not isinstance(document, scoped_config.ScopedConfig):
            raise ValueError("Expected verified scope goal")
        proposals[original.scope] = document
    plan = scoped_review.build_review(current, proposals)
    if bundle.rollback is not None:
        if any(s not in bundle.rollback.restore_scopes for s in plan.changed_scopes):
            raise ValueError("Rollback would write outside initial restore scopes")
        if (
            bundle.rollback_checkpoint is not None
            and bundle.rollback_checkpoint.complete
            and plan.changed_scopes
        ):
            raise ValueError("Completed rollback actual bytes changed")
    if store.verified_fingerprint(store.load_transaction(state_root, txid)) != fingerprint:
        raise ValueError("Private evidence changed during recovery review")
    return RecoveryReview(state_root, config_root, txid, action, plan, fingerprint)


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _stage_identity(path: Path) -> tuple[int, ...]:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise ValueError("Unsafe output stage")
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
    )


def _execute(
    session: store.StoreSession,
    bundle: store.VerifiedTransaction,
    plan: GroupReviewPlan,
    action: str,
    flags: list[bool],
    fingerprint: tuple,
    expected_source: Callable[[], None] | None = None,
) -> PublicationResult:
    state = session.binding.state_root
    txid = bundle.intent.transaction_id
    expected = plan.evidence
    stages: dict[Scope, tuple[Path, tuple[int, ...]]] = {}

    def check() -> None:
        session.check()
        session.refuse_other_pending(txid)
        route_approval.revalidate(expected)
        if store.verified_fingerprint(store.load_transaction(state, txid)) != fingerprint:
            raise ValueError("Private evidence changed since reviewed operation")
        if expected_source is not None:
            expected_source()

    def checkpoint(record) -> None:
        nonlocal bundle, fingerprint
        check()
        flags[1] = True
        bundle = session.checkpoint(bundle, record, fingerprint=fingerprint)
        fingerprint = store.verified_fingerprint(bundle)

    check()
    # Abandon only closes all-prior evidence; it must remain possible after a
    # missing/failed compiler prevented publication in the first place.
    if action != "abandon":
        for review in plan.scopes:
            for text in (review.previous_text, review.proposed_text):
                session.check()
                persistence.validate_lua(text)
                if expected_source is not None:
                    check()
    check()
    flags[1] = True
    session.sync_evidence(bundle)
    check()
    try:
        for review, route in zip(plan.scopes, expected.routes, strict=True):
            if review.scope not in plan.changed_scopes:
                continue
            session.check()
            target = Path(route.file.path.resolved_path)
            path = target.parent / (".attune-" + secrets.token_hex(16) + ".tmp")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(review.proposed_text.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            stages[review.scope] = (path, _stage_identity(path))
        check()
        if action == "rollback":
            if bundle.rollback is None:
                operation = RollbackOperation(
                    bundle.snapshot.snapshot_id,
                    bundle.snapshot.plan.review_hash,
                    hashlib.sha256(repr(fingerprint).encode("utf-8")).hexdigest(),
                    plan,
                    plan.changed_scopes,
                )
                checkpoint(operation)
            operation = bundle.rollback
            if operation is None:
                raise ValueError("Missing rollback operation")
            if bundle.rollback_checkpoint is None:
                checkpoint(RollbackCheckpoint(operation.operation_sha256))
        elif action == "resume":
            checkpoint(replace(bundle.intent, phase=Phase.PUBLISHING, progress=()))

        for review in plan.scopes:
            if review.scope not in stages:
                continue
            path, identity = stages[review.scope]
            check()
            if _stage_identity(path) != identity or persistence.read_stable(
                path, limit=scoped_review.MAX_INPUT_BYTES
            ) != review.proposed_text.encode("utf-8"):
                raise ValueError("Output stage changed")
            # Revalidate after reading the stage, immediately before replacement.
            check()
            if _stage_identity(path) != identity or persistence.read_stable(
                path, limit=scoped_review.MAX_INPUT_BYTES
            ) != review.proposed_text.encode("utf-8"):
                raise ValueError("Output stage changed during final preflight")
            route = next(r for r in expected.routes if r.scope is review.scope)
            target = Path(route.file.path.resolved_path)
            if expected_source is not None:
                expected_source()
            flags[0] = True
            os.replace(path, target)
            _sync_directory(target.parent)
            fresh = route_approval.inspect_installation(
                Path(expected.config_root) / "attune/installation.json",
                config_root=Path(expected.config_root),
                state_root=state,
            )
            if fresh.registry != expected.registry or fresh.protected != expected.protected:
                raise ValueError("Context changed after replacement")
            for before, after in zip(expected.routes, fresh.routes, strict=True):
                if before.scope is not review.scope:
                    if before != after:
                        raise ValueError("Unwritten scope changed")
                elif (
                    route_binding(before.file) != route_binding(after.file)
                    or after.file.source_sha256 != review.proposed_sha256
                    or _stage_identity(target) != identity
                ):
                    raise ValueError("Replaced scope binding or bytes changed")
            expected = fresh
            if action == "rollback":
                operation = bundle.rollback
                if operation is None:
                    raise ValueError("Missing rollback operation")
                complete_scopes = []
                for scope in operation.restore_scopes:
                    original = next(r for r in bundle.snapshot.plan.scopes if r.scope is scope)
                    actual = next(r for r in expected.routes if r.scope is scope)
                    if actual.file.source_sha256 != original.previous_sha256:
                        break
                    complete_scopes.append(scope)
                checkpoint(RollbackCheckpoint(operation.operation_sha256, tuple(complete_scopes)))
            else:
                progress = []
                for scope in bundle.intent.changed_scopes:
                    original = next(r for r in bundle.snapshot.plan.scopes if r.scope is scope)
                    actual = next(r for r in expected.routes if r.scope is scope)
                    if actual.file.source_sha256 != original.proposed_sha256:
                        break
                    progress.append(scope)
                checkpoint(replace(bundle.intent, phase=Phase.PUBLISHING, progress=tuple(progress)))

        check()
        for review, route in zip(plan.scopes, expected.routes, strict=True):
            if route.file.source_sha256 != review.proposed_sha256:
                raise ValueError("Final group differs from reviewed goals")
            fd = os.open(route.file.path.resolved_path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            _sync_directory(Path(route.file.path.resolved_path).parent)
        check()
        if action == "rollback":
            operation = bundle.rollback
            if operation is None:
                raise ValueError("Missing rollback operation")
            if bundle.rollback_checkpoint is None or not bundle.rollback_checkpoint.complete:
                checkpoint(
                    RollbackCheckpoint(operation.operation_sha256, operation.restore_scopes, True)
                )
        terminal = Phase.ABORTED if action in ("rollback", "abandon") else Phase.COMMITTED
        checkpoint(
            replace(
                bundle.intent,
                phase=terminal,
                progress=bundle.intent.changed_scopes
                if terminal is Phase.COMMITTED
                else bundle.intent.progress,
            )
        )
        route_approval.revalidate(expected)
        if expected_source is not None:
            expected_source()
        return PublicationResult(txid, terminal.value, False, flags[0], flags[1])
    finally:
        for path, identity in stages.values():
            try:
                if _stage_identity(path) == identity:
                    path.unlink()
            except FileNotFoundError:
                pass


def publish_reviewed(
    plan: GroupReviewPlan,
    *,
    state_root: Path,
    config_root: Path,
    transaction_id: str | None = None,
    cancel_event: threading.Event | None = None,
    expected_source: Callable[[], None] | None = None,
) -> PublicationResult:
    """Publish reviewed goals; expected_source is a read-only check under the writer lock."""
    flags = [False, False]
    txid = transaction_id
    try:
        scoped_review.validate_recorded_review(plan)
        if txid is not None:
            validate_transaction_id(txid)
            if not plan.changed_scopes:
                raise ValueError("No-op cannot select a transaction journal")
        if (str(state_root), str(config_root)) != (
            plan.evidence.state_root,
            plan.evidence.config_root,
        ):
            raise ValueError("Explicit config/state context differs from review")
        with store.exclusive_store_session(state_root, cancel_event=cancel_event) as session:
            scoped_review.revalidate_review(plan)
            session.refuse_other_pending(txid)
            if expected_source is not None:
                expected_source()
            if not plan.changed_scopes:
                for review in plan.scopes:
                    session.check()
                    persistence.validate_lua(review.previous_text)
                scoped_review.revalidate_review(plan)
                session.refuse_other_pending()
                if expected_source is not None:
                    expected_source()
                session.check()
                return PublicationResult(None, "no-op", False, flags[0], flags[1])
            allocated = txid is None
            candidate = txid or secrets.token_hex(16)
            directory = state_root / "attune/transactions" / candidate
            if allocated and os.path.lexists(directory):
                raise ValueError("Generated transaction ID already exists")
            txid = candidate
            if not allocated and os.path.lexists(directory):
                bundle = store.load_transaction(state_root, txid)
                if (
                    bundle.intent.phase is not Phase.PREPARED
                    or bundle.rollback is not None
                    or bundle.snapshot.plan != plan
                ):
                    raise ValueError("Selected journal is not the exact reviewed PREPARED plan")
            else:
                flags[1] = True
                bundle = session.prepare(plan, txid)
            return _execute(
                session,
                bundle,
                plan,
                "resume",
                flags,
                store.verified_fingerprint(bundle),
                expected_source,
            )
    except (OSError, ValueError, RuntimeError) as exc:
        return PublicationResult(txid, "failed", txid is not None, flags[0], flags[1], str(exc))


def commit_recovery(
    review: RecoveryReview, *, cancel_event: threading.Event | None = None
) -> PublicationResult:
    """Revalidate the exact review under lock, then perform only its selected action."""
    flags = [False, False]
    try:
        with store.exclusive_store_session(review.state_root, cancel_event=cancel_event) as session:
            scoped_review.validate_recorded_review(review.plan)
            fresh = review_recovery(
                review.state_root,
                review.transaction_id,
                review.action,
                config_root=review.config_root,
            )
            if (
                fresh.plan.review_hash != review.plan.review_hash
                or fresh.private_fingerprint != review.private_fingerprint
            ):
                raise ValueError("Recovery review is stale or changed")
            session.refuse_other_pending(review.transaction_id)
            scoped_review.revalidate_review(review.plan)
            bundle = store.load_transaction(review.state_root, review.transaction_id)
            return _execute(
                session, bundle, review.plan, review.action, flags, review.private_fingerprint
            )
    except (OSError, ValueError, RuntimeError) as exc:
        return PublicationResult(
            review.transaction_id, "failed", True, flags[0], flags[1], str(exc)
        )
