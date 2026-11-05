"""File safety for the two fixed, independently reviewed generated outputs."""

import fcntl
import hashlib
import json
import os
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from hyprmod.core import persistence, route_approval
from hyprmod.core.scopes import SCOPE_BASENAMES

Kind = Literal["bindings", "input"]
MAX_INPUT_BYTES = 1024 * 1024
LOCK_TIMEOUT = 5.0
_SIBLING_BASENAMES = frozenset(
    {
        "attune.lua",
        *SCOPE_BASENAMES.values(),
        "attune-bindings.lua",
        "attune-input.lua",
        "keybindings.tsv",
    }
)


def _names(kind: Kind) -> tuple[str, str, str]:
    if kind == "bindings":
        return "attune-bindings.lua", "bindings.lock", "bindings-backups"
    if kind == "input":
        return "attune-input.lua", "input.lock", "input-backups"
    raise ValueError("Unknown owned output kind")


@dataclass(frozen=True, slots=True)
class OwnedBaseline:
    config_root: str
    state_root: str
    lexical_path: str
    resolved_path: str
    status: str
    text: str
    proof: route_approval.PathProof
    protected: tuple[route_approval.PathProof, ...]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OwnedSaveResult:
    outcome: str
    baseline: OwnedBaseline | None
    backup_path: str | None
    may_have_written: bool
    error: str | None


def _safe_parent(target: Path) -> None:
    parent = target.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
        or parent.st_mode & 0o300 != 0o300
        or parent.st_mode & 0o7022
    ):
        raise ValueError("Bindings require an existing safe owned writable parent")


def _private_file(path: Path, *, private: bool = True) -> None:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_mode & 0o7111
        or info.st_mode & 0o022
        or info.st_mode & 0o600 != 0o600
        or (private and stat.S_IMODE(info.st_mode) != 0o600)
    ):
        raise ValueError("Expected owned single-link safe file" + (" 0600" if private else ""))


def _protected_paths(kind: Kind, config: Path) -> tuple[Path, ...]:
    basename, _, _ = _names(kind)
    names = (
        "hyprland.lua",
        "hyprland.conf",
        "attune.lua",
        *SCOPE_BASENAMES.values(),
        "keybindings.tsv",
        "keybindings-bridge.lua",
        "attune-bindings.lua",
        "attune-input.lua",
    )
    return (
        *(config / "hypr" / name for name in names if name != basename),
        config / "attune/installation.json",
    )


def _protected_from(value: object) -> tuple[route_approval.PathProof, ...]:
    if type(value) is not list or len(value) > 32:
        raise ValueError("Invalid protected proofs transport")
    return tuple(route_approval._proof_from(p) for p in value)


def validate_protected(
    protected: tuple[route_approval.PathProof, ...],
    paths: tuple[Path, ...],
    own: route_approval.PathProof,
) -> None:
    if type(protected) is not tuple or len(protected) != len(paths):
        raise ValueError("Expected immutable protected proofs for exact config context")
    own_leaves = [f.identity[:2] for f in own.facts if f.path == own.resolved_path and f.identity]
    for proof, path in zip(protected, paths, strict=True):
        if type(proof) is not route_approval.PathProof:
            raise ValueError("Expected exact protected path proof")
        checked = route_approval._proof_from(json.loads(route_approval._json(asdict(proof))))
        if checked != proof or proof.lexical_path != str(path):
            raise ValueError("Protected paths differ from config context")
        if any(
            route_approval._overlap(a, b)
            for a in (own.lexical_path, own.resolved_path)
            for b in (proof.lexical_path, proof.resolved_path)
        ) or any(
            f.path == proof.resolved_path and f.identity and f.identity[:2] in own_leaves
            for f in proof.facts
        ):
            raise ValueError("Owned output and protected paths collide or alias")


def _protection_binding(proof: route_approval.PathProof) -> tuple:
    mutable = Path(proof.lexical_path).name in _SIBLING_BASENAMES
    facts = []
    for fact in proof.facts:
        identity = fact.identity
        if (
            mutable
            and fact.path == proof.resolved_path
            and fact.link_target is None
            and (
                not identity
                or (
                    len(identity) == 9
                    and stat.S_ISREG(identity[2])
                    and identity[3] == os.getuid()
                    and identity[5] == 1
                    and not identity[2] & 0o7133
                    and identity[2] & 0o600 == 0o600
                )
            )
        ):
            identity = ()
        facts.append((fact.path, identity, fact.link_target))
    return proof.lexical_path, proof.resolved_path, tuple(facts)


def same_protection(
    original: tuple[route_approval.PathProof, ...],
    current: tuple[route_approval.PathProof, ...],
) -> bool:
    """Compare observed protection, permitting only safe sibling file leaf changes."""
    return tuple(_protection_binding(p) for p in original) == tuple(
        _protection_binding(p) for p in current
    )


def validate_baseline(
    kind: Kind, baseline: OwnedBaseline, *, read_text: Callable[[str], object]
) -> None:
    basename, _, _ = _names(kind)
    for value in (
        baseline.config_root,
        baseline.state_root,
        baseline.lexical_path,
        baseline.resolved_path,
    ):
        if type(value) is not str:
            raise ValueError("Expected string owned output context")
        route_approval._path(value)
    if (
        Path(baseline.lexical_path) != Path(baseline.config_root) / "hypr" / basename
        or Path(baseline.resolved_path).name != basename
    ):
        raise ValueError("Owned output requires fixed lexical and resolved basename")
    if type(baseline.proof) is not route_approval.PathProof:
        raise ValueError("Expected exact path proof")
    proof = baseline.proof
    if route_approval._proof_from(json.loads(route_approval._json(asdict(proof)))) != proof:
        raise ValueError("Invalid owned output path proof")
    if (proof.lexical_path, proof.resolved_path) != (baseline.lexical_path, baseline.resolved_path):
        raise ValueError("Invalid owned output path proof")
    validate_protected(
        baseline.protected, _protected_paths(kind, Path(baseline.config_root)), proof
    )
    if type(baseline.status) is not str or baseline.status not in {"absent", "empty", "owned"}:
        raise ValueError("Invalid owned baseline status")
    if type(baseline.text) is not str or len(baseline.text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Invalid owned baseline text")
    if baseline.status == "owned":
        read_text(baseline.text)
    elif baseline.text != "":
        raise ValueError("Absent/empty baseline must have no text")
    leaf = [fact for fact in proof.facts if fact.path == baseline.resolved_path]
    if not leaf or bool(leaf[-1].identity) != (baseline.status != "absent"):
        raise ValueError("Baseline existence differs from proof")
    if baseline.status != "absent":
        identity = leaf[-1].identity
        if (
            len(identity) != 9
            or not stat.S_ISREG(identity[2])
            or identity[3] != os.getuid()
            or identity[5] != 1
            or identity[2] & 0o7133
            or identity[2] & 0o600 != 0o600
            or identity[6] != len(baseline.text.encode("utf-8"))
        ):
            raise ValueError("Baseline proof must describe exact safe file bytes")


def observe(
    kind: Kind, config_root: Path, state_root: Path, *, read_text: Callable[[str], object]
) -> OwnedBaseline:
    basename, _, _ = _names(kind)
    config = route_approval._path(config_root)
    state = route_approval._path(state_root)
    lexical = config / "hypr" / basename
    proof = route_approval._resolve(lexical, absent=True)
    target = Path(proof.resolved_path)
    if target.name != basename:
        raise ValueError("Resolved owned output basename must be " + basename)
    _safe_parent(target)
    protected = tuple(
        route_approval._resolve(path, absent=True) for path in _protected_paths(kind, config)
    )
    route_approval._collisions(
        (proof,), (*protected, route_approval._resolve(state / "attune", absent=True))
    )
    git = route_approval._git_context(proof, outside=False)
    leaf = route_approval._fact(target)
    raw = b""
    status = "absent"
    if leaf.identity:
        if leaf.identity[6]:
            evidence, raw = route_approval._read_file(lexical, registry=False, outside=False)
            if evidence.path != proof:
                raise ValueError("Owned output route changed during read")
            status = "owned"
        else:
            _private_file(target, private=False)
            raw = persistence.read_stable(target, limit=MAX_INPUT_BYTES)
            if raw:
                raise ValueError("Empty owned output changed during read")
            status = "empty"
    text = raw.decode("utf-8")
    if status == "owned":
        read_text(text)
    # Own source identity is independent of sibling protection and private state creation.
    dependencies = (*proof.facts, *git)
    if any(
        route_approval._fact(Path(f.path)) != f
        for f in (*dependencies, *(f for p in protected for f in p.facts))
    ):
        raise ValueError("Owned output dependencies changed during observation")
    if route_approval._resolve(lexical, absent=True) != proof:
        raise ValueError("Owned output route changed during observation")
    return OwnedBaseline(
        str(config),
        str(state),
        str(lexical),
        str(target),
        status,
        text,
        route_approval.PathProof(str(lexical), str(target), tuple(dependencies)),
        protected,
    )


def persist_reviewed(
    kind: Kind,
    baseline: OwnedBaseline,
    proposed_text: str,
    *,
    read_text: Callable[[str], object],
    observe_current: Callable[[], OwnedBaseline],
    cancel_event: threading.Event | None = None,
) -> OwnedSaveResult:
    attempted = False
    backup = None
    backup_verified = False
    try:
        _, lock_name, backup_name = _names(kind)
        if threading.current_thread().daemon:
            raise ValueError("Owned Save requires a direct non-daemon worker")
        validate_baseline(kind, baseline, read_text=read_text)
        read_text(proposed_text)
        state_root = Path(baseline.state_root)
        target = Path(baseline.resolved_path)

        def check_source():
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Owned Save cancelled before publication")
            if observe_current() != baseline:
                raise ValueError("Owned source or route changed; review again")

        check_source()
        state = state_root / "attune"
        backups = state / backup_name
        lock_path = state / lock_name
        state_proof = route_approval._resolve(state_root, absent=True)
        if any(f.link_target is not None for f in state_proof.facts):
            raise ValueError("State ancestors must not be symlinks")
        route_approval._git_context(state_proof, outside=True)
        if not state_root.exists():
            _safe_parent(state_root)
        for directory in (state_root, state, backups):
            if directory.exists() or directory.is_symlink():
                if directory == state_root:
                    _safe_parent(directory / "placeholder")
                else:
                    persistence._private_directory(directory, create=False)
        if lock_path.exists() or lock_path.is_symlink():
            _private_file(lock_path)
        if route_approval._fact(backups / ".git").identity:
            raise ValueError("Owned backups must be outside Git working trees")
        route_approval._git_context(route_approval._resolve(backups, absent=True), outside=True)
        if baseline.status != "absent":
            candidate = backups / (baseline.sha256 + ".lua")
            if candidate.exists() or candidate.is_symlink():
                _private_file(candidate)
                if persistence.read_stable(candidate) != baseline.text.encode("utf-8"):
                    raise ValueError("Owned backup collision")
        route_approval._collisions(
            (route_approval._resolve(target, absent=True),),
            (route_approval._resolve(state, absent=True),),
        )
        for fact in state_proof.facts:
            if route_approval._fact(Path(fact.path)) != fact:
                raise ValueError("State route changed before creation")
        if not state_root.exists():
            state_root.mkdir(mode=0o700)
        persistence._private_directory(state, create=True)
        if any(f.identity and route_approval._fact(Path(f.path)) != f for f in state_proof.facts):
            raise ValueError("State ancestors changed during creation")
        state_facts = route_approval._resolve(state).facts
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        with os.fdopen(fd, "r+b") as lock:
            _private_file(lock_path)
            lock_fact = route_approval._fact(lock_path)
            if route_approval._stat_identity(os.fstat(lock.fileno())) != lock_fact.identity:
                raise ValueError("Lock changed before acquisition")

            def check_state():
                if route_approval._fact(backups / ".git").identity:
                    raise ValueError("Owned backups must be outside Git working trees")
                route_approval._git_context(
                    route_approval._resolve(backups, absent=True), outside=True
                )
                for fact in (*state_facts, lock_fact):
                    if route_approval._fact(Path(fact.path)) != fact:
                        raise ValueError("Owned state or lock changed")
                _private_file(lock_path)
                persistence._private_directory(state, create=False)
                if backups.exists() or backups.is_symlink():
                    persistence._private_directory(backups, create=False)

            deadline = time.monotonic() + LOCK_TIMEOUT
            while True:
                check_source()
                check_state()
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Owned lock timed out") from None
                    time.sleep(0.05)
            check_source()
            check_state()
            persistence.validate_lua(proposed_text)
            check_source()
            check_state()
            if baseline.text == proposed_text:
                fresh = observe_current()
                check_state()
                if fresh != baseline:
                    raise ValueError("Owned output changed before no-op completion")
                return OwnedSaveResult("no-op", fresh, None, False, None)
            if baseline.status != "absent":
                persistence._private_directory(backups, create=True)
                backup_directory = route_approval._resolve(backups)
                backup = backups / (baseline.sha256 + ".lua")
                if not backup.exists() and not backup.is_symlink():
                    persistence._atomic_write(
                        backup,
                        baseline.text.encode("utf-8"),
                        exclusive=True,
                        before_replace=check_state,
                    )
                backup_fact = route_approval._fact(backup)

                def verify_backup():
                    check_state()
                    for fact in (*backup_directory.facts, backup_fact):
                        if route_approval._fact(Path(fact.path)) != fact:
                            raise ValueError("Owned backup route or identity changed")
                    persistence._private_directory(backups, create=False)
                    _private_file(backup)
                    if persistence.read_stable(backup) != baseline.text.encode("utf-8"):
                        raise ValueError("Owned backup differs from reviewed prior")

                verify_backup()
                backup_fd = os.open(backup, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    if route_approval._stat_identity(os.fstat(backup_fd)) != backup_fact.identity:
                        raise ValueError("Owned backup changed before sync")
                    os.fsync(backup_fd)
                finally:
                    os.close(backup_fd)
                for directory in (backups, state, state_root, state_root.parent):
                    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                verify_backup()
                backup_verified = True

            def before_replace():
                nonlocal attempted
                check_state()
                if backup is not None:
                    verify_backup()
                check_source()
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("Owned Save cancelled before publication")
                # Exclusive link/rename can succeed before directory fsync fails.
                attempted = True

            persistence._atomic_write(
                target,
                proposed_text.encode("utf-8"),
                exclusive=baseline.status == "absent",
                before_replace=before_replace,
            )
            fresh = observe_current()
            check_state()
            old_dependencies = tuple(f for f in baseline.proof.facts if f.path != str(target))
            new_dependencies = tuple(f for f in fresh.proof.facts if f.path != str(target))
            if (
                fresh.status != "owned"
                or fresh.text != proposed_text
                or fresh.resolved_path != str(target)
                or fresh.config_root != baseline.config_root
                or fresh.state_root != baseline.state_root
                or fresh.lexical_path != baseline.lexical_path
                or old_dependencies != new_dependencies
                or fresh.protected != baseline.protected
            ):
                raise ValueError("Post-save owned output verification failed")
            read_text(fresh.text)
            return OwnedSaveResult("saved", fresh, str(backup) if backup else None, True, None)
    except (OSError, ValueError, RuntimeError) as exc:
        return OwnedSaveResult(
            "failed",
            None,
            str(backup) if backup_verified else None,
            attempted,
            str(exc) or type(exc).__name__,
        )
