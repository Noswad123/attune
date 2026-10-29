"""Inactive read-only route inspection. Evidence is not write or runtime authority.

Direct inspection is bounded in size/depth, not filesystem latency. Clients should
use the supervised worker. Rechecks narrow races but do not make a snapshot atomic
or provide hostile-filesystem security guarantees.
"""

import argparse
import hashlib
import json
import math
import os
import stat
import sys
import threading
import unicodedata
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hyprmod.core import health, installation, scoped_config
from hyprmod.core.scopes import SCOPE_BASENAMES, Scope

MAX_EVIDENCE_BYTES = 1024 * 1024
MAX_DEPTH = 128
MAX_FACTS = 4096


class ApprovalError(ValueError):
    """Unsafe, changed, or uninspectable installation; request a fresh review."""


@dataclass(frozen=True, slots=True)
class PathFact:
    path: str
    # Directories exclude timestamps/size: unrelated sibling activity is harmless.
    # dev, ino, mode, uid, gid; other objects append nlink, size, mtime_ns, ctime_ns.
    identity: tuple[int, ...]
    link_target: str | None = None


@dataclass(frozen=True, slots=True)
class PathProof:
    lexical_path: str
    resolved_path: str
    facts: tuple[PathFact, ...]


@dataclass(frozen=True, slots=True)
class FileEvidence:
    path: PathProof
    source_sha256: str
    git_context: tuple[PathFact, ...]


@dataclass(frozen=True, slots=True)
class RouteEvidence:
    scope: Scope
    file: FileEvidence
    content_id: str
    # values, beziers, animations, monitors, in that order.
    counts: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class InstallationEvidence:
    config_root: str
    state_root: str
    registry: FileEvidence
    routes: tuple[RouteEvidence, ...]
    protected: tuple[PathProof, ...]
    observed_at: str

    @property
    def evidence_hash(self) -> str:
        data = asdict(self)
        del data["observed_at"]
        return hashlib.sha256(_json(data).encode("ascii")).hexdigest()

    def to_json(self) -> str:
        text = _json({"evidence": asdict(self), "evidence_hash": self.evidence_hash})
        if len(text) > MAX_EVIDENCE_BYTES:
            raise ApprovalError("Evidence exceeds 1 MiB limit")
        return text

    @classmethod
    def from_json(cls, text: str) -> "InstallationEvidence":
        """Decode transport data, not a serialized approval or authentication token."""
        try:
            if len(text) > MAX_EVIDENCE_BYTES or len(text.encode("utf-8")) > MAX_EVIDENCE_BYTES:
                raise ApprovalError("Evidence exceeds 1 MiB limit")
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
                    if depth > 16:
                        raise ApprovalError("Evidence nesting exceeds limit")
                elif char in "]}":
                    depth -= 1
            root = _fields(
                json.loads(text, object_pairs_hook=_unique), {"evidence", "evidence_hash"}
            )
            data = _fields(root["evidence"], set(cls.__dataclass_fields__))
            config = _path(data["config_root"])
            state = _path(data["state_root"])
            registry = _file_from(data["registry"])
            if registry.path.lexical_path != str(config / "attune/installation.json"):
                raise ApprovalError("Registry does not match explicit context")
            routes = []
            records = data["routes"]
            if not isinstance(records, list) or len(records) != 2:
                raise ApprovalError("Expected both routes")
            for scope, record in zip(Scope, records, strict=True):
                item = _fields(record, {"scope", "file", "content_id", "counts"})
                if item["scope"] != scope.value:
                    raise ApprovalError("Wrong route scope or order")
                file = _file_from(item["file"])
                installation.ScopeRoute(scope, file.path.lexical_path, file.path.resolved_path)
                counts = item["counts"]
                if (
                    not isinstance(counts, list)
                    or len(counts) != 4
                    or any(type(n) is not int or not 0 <= n <= 1048576 for n in counts)
                    or (scope == Scope.DISPLAYS and any(counts[:3]))
                    or (scope == Scope.APPEARANCE and counts[3] != 0)
                ):
                    raise ApprovalError("Invalid canonical counts")
                routes.append(
                    RouteEvidence(scope, file, _digest(item["content_id"]), tuple(counts))
                )
            protected = data["protected"]
            if not isinstance(protected, list) or len(protected) != 4:
                raise ApprovalError("Invalid protected context")
            proofs = tuple(_proof_from(p) for p in protected)
            if tuple(p.lexical_path for p in proofs) != _protected_paths(config, state):
                raise ApprovalError("Protected paths do not match explicit context")
            stamp = data["observed_at"]
            if not isinstance(stamp, str) or len(stamp) > 64 or "T" not in stamp:
                raise ApprovalError("Invalid observation timestamp")
            if datetime.fromisoformat(stamp).utcoffset() != timedelta(0):
                raise ApprovalError("Observation timestamp must be UTC")
            result = cls(str(config), str(state), registry, tuple(routes), proofs, stamp)
            if result.evidence_hash != _digest(root["evidence_hash"]):
                raise ApprovalError("Evidence fingerprint mismatch")
            return result
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
            raise ApprovalError(f"Invalid inspection evidence: {exc}") from exc


def _json(data: object) -> str:
    return json.dumps(
        data, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ApprovalError(f"Duplicate evidence field: {key}")
        result[key] = value
    return result


def _fields(value: object, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ApprovalError("Unexpected evidence fields")
    return value


def _digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ApprovalError("Invalid SHA-256")
    return value


def _path(value: object) -> Path:
    if isinstance(value, Path):
        value = str(value)
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or len(value.encode("utf-8")) > installation.MAX_PATH_BYTES
        or len(value.split("/")) > MAX_DEPTH
        or (value != "/" and any(p in ("", ".", "..") for p in value.split("/")[1:]))
        or any(unicodedata.category(c) in {"Cc", "Cf"} or c in "~$`" for c in value)
    ):
        raise ApprovalError("Expected explicit bounded normalized absolute path")
    return Path(value)


def _fact(path: Path) -> PathFact:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return PathFact(str(path), ())
    identity = _stat_identity(info)
    if stat.S_ISDIR(info.st_mode):
        identity = identity[:5]
    return PathFact(str(path), identity, os.readlink(path) if stat.S_ISLNK(info.st_mode) else None)


def _facts_from(value: object) -> tuple[PathFact, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_FACTS:
        raise ApprovalError("Invalid fact list")
    result = []
    for record in value:
        data = _fields(record, {"path", "identity", "link_target"})
        path = str(_path(data["path"]))
        numbers = data["identity"]
        if not isinstance(numbers, list) or len(numbers) not in (0, 5, 9):
            raise ApprovalError("Invalid metadata identity")
        if any(type(n) is not int for n in numbers):
            raise ApprovalError("Metadata must contain integers")
        if any(n < 0 for n in numbers[:7]):
            raise ApprovalError("Invalid negative identity or size")
        target = data["link_target"]
        if target is not None and (
            not isinstance(target, str) or not target or len(target.encode("utf-8")) > 4096
        ):
            raise ApprovalError("Invalid link target")
        if numbers:
            mode = numbers[2]
            if (len(numbers) == 5) != stat.S_ISDIR(mode):
                raise ApprovalError("Invalid directory identity")
            if stat.S_ISLNK(mode) != (target is not None):
                raise ApprovalError("Invalid symlink identity")
        elif target is not None:
            raise ApprovalError("Missing object cannot have link target")
        result.append(PathFact(path, tuple(numbers), target))
    return tuple(result)


def _proof_from(value: object) -> PathProof:
    data = _fields(value, {"lexical_path", "resolved_path", "facts"})
    return PathProof(
        str(_path(data["lexical_path"])),
        str(_path(data["resolved_path"])),
        _facts_from(data["facts"]),
    )


def _file_from(value: object) -> FileEvidence:
    data = _fields(value, {"path", "source_sha256", "git_context"})
    proof = _proof_from(data["path"])
    context = _facts_from(data["git_context"])
    if tuple(f.path for f in context) != tuple(
        str(p / ".git") for p in Path(proof.resolved_path).parents
    ):
        raise ApprovalError("Git context does not match resolved ancestors")
    leaf = next((f for f in reversed(proof.facts) if f.path == proof.resolved_path), None)
    if leaf is None or len(leaf.identity) != 9 or not stat.S_ISREG(leaf.identity[2]):
        raise ApprovalError("File evidence must include a regular resolved file")
    return FileEvidence(proof, _digest(data["source_sha256"]), context)


def _resolve(path: Path, *, absent: bool = False) -> PathProof:
    pending = deque((part, False) for part in path.parts[1:])
    current = Path("/")
    facts = [_fact(current)]
    hops = 0
    while pending:
        part, required = pending.popleft()
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        current /= part
        _path(str(current))
        fact = _fact(current)
        facts.append(fact)
        if len(facts) > MAX_FACTS:
            raise ApprovalError("Resolution exceeds fact limit")
        if not fact.identity:
            if not absent or required:
                raise ApprovalError(f"Missing target or dangling link: {current}")
            # Bind the first absent component; no children can exist beneath it.
            current = current.joinpath(*(part for part, _ in pending))
            _path(str(current))
            break
        mode = fact.identity[2]
        if fact.link_target is not None:
            hops += 1
            if hops > 40:
                raise ApprovalError("Symlink cycle or more than 40 hops")
            if fact.identity[3] not in (0, os.getuid()):
                raise ApprovalError(f"Unowned dependent link: {current}")
            target = Path(fact.link_target)
            current = Path("/") if target.is_absolute() else current.parent
            parts = target.parts[1:] if target.is_absolute() else target.parts
            pending.extendleft((part, True) for part in reversed(parts))
            if len(pending) > MAX_DEPTH:
                raise ApprovalError("Symlink path exceeds depth limit")
        elif pending and not stat.S_ISDIR(mode):
            raise ApprovalError(f"Non-directory parent: {current}")
        elif stat.S_ISDIR(mode):
            # Root-owned sticky temporary ancestors are acceptable for local fixtures.
            sticky_root = fact.identity[3] == 0 and bool(mode & stat.S_ISVTX)
            if fact.identity[3] not in (0, os.getuid()) or (mode & 0o022 and not sticky_root):
                raise ApprovalError(f"Unsafe dependent directory: {current}")
    # Lexical collapsing of '..' is not proof that the kernel can traverse it.
    # Search permissions/ACLs still apply to directories canceled by '..'.
    try:
        followed = path.stat()
    except FileNotFoundError:
        if not absent or all(fact.identity for fact in facts):
            raise
    else:
        resolved = current.stat()
        if (followed.st_dev, followed.st_ino) != (resolved.st_dev, resolved.st_ino):
            raise ApprovalError(f"Kernel resolution differs from observed route: {path}")
    return PathProof(str(path), str(current), tuple(facts))


def _git_context(proof: PathProof, *, outside: bool) -> tuple[PathFact, ...]:
    facts = []
    for directory in Path(proof.resolved_path).parents:
        marker = _fact(directory / ".git")
        if marker.identity:
            mode = marker.identity[2]
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ApprovalError(f"Uncertain Git marker: {marker.path}")
            if outside:
                raise ApprovalError(f"Must resolve outside Git working trees: {marker.path}")
        facts.append(marker)
    return tuple(facts)


def _read_file(path: Path, *, registry: bool, outside: bool) -> tuple[FileEvidence, bytes]:
    proof = _resolve(path)
    target = Path(proof.resolved_path)
    before = _fact(target)
    identity = before.identity
    if not identity:
        raise ApprovalError(f"File disappeared before read: {target}")
    mode = identity[2]
    if (
        not stat.S_ISREG(mode)
        or identity[3] != os.getuid()
        or identity[5] != 1
        or mode & 0o7111
        or mode & 0o022
        or mode & 0o600 != 0o600
        or (registry and stat.S_IMODE(mode) != 0o600)
    ):
        expected = "0600 registry" if registry else "non-executable read/write file"
        raise ApprovalError(f"Expected owned single-link {expected}: {target}")
    parent = target.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
        or parent.st_mode & 0o300 != 0o300
        or parent.st_mode & 0o7022
    ):
        raise ApprovalError(
            f"Expected owned writable/searchable safe immediate parent: {target.parent}"
        )
    limit = installation.MAX_REGISTRY_BYTES if registry else scoped_config.MAX_INPUT_BYTES
    if not 0 < identity[6] <= limit:
        raise ApprovalError(f"Expected nonempty file of at most {limit} bytes: {target}")
    fd = os.open(target, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _stat_identity(opened) != identity:
            raise ApprovalError(f"File changed before read: {target}")
        raw = stream.read(limit + 1)
        if _stat_identity(os.fstat(stream.fileno())) != identity or len(raw) != identity[6]:
            raise ApprovalError(f"File changed during read: {target}")
    if _fact(target) != before or _resolve(path) != proof:
        raise ApprovalError(f"Resolution or file changed during read: {path}")
    return FileEvidence(
        proof, hashlib.sha256(raw).hexdigest(), _git_context(proof, outside=outside)
    ), raw


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _protected_paths(config: Path, state: Path) -> tuple[str, ...]:
    return tuple(
        str(config / "hypr" / name) for name in ("hyprland.lua", "hyprland.conf", "attune.lua")
    ) + (str(state / "attune"),)


def _overlap(left: str, right: str) -> bool:
    return (
        left == right
        or left.startswith(right.rstrip("/") + "/")
        or right.startswith(left.rstrip("/") + "/")
    )


def _collisions(outputs: tuple[PathProof, ...], protected: tuple[PathProof, ...]) -> None:
    for index, output in enumerate(outputs):
        for other in (*outputs[index + 1 :], *protected):
            if any(
                _overlap(a, b)
                for a in (output.lexical_path, output.resolved_path)
                for b in (other.lexical_path, other.resolved_path)
            ):
                raise ApprovalError("Registry, scope, or protected paths collide")
            leaf = _fact(Path(output.resolved_path))
            other_leaf = _fact(Path(other.resolved_path))
            if (
                leaf.identity
                and other_leaf.identity
                and leaf.identity[:2] == other_leaf.identity[:2]
            ):
                raise ApprovalError("Registry, scope, or protected inode alias")


def inspect_installation(
    registry_path: Path, *, config_root: Path, state_root: Path
) -> InstallationEvidence:
    """Observe an existing canonical pair; no activation, repair, or provisioning."""
    try:
        config = _path(config_root)
        state = _path(state_root)
        path = _path(registry_path)
        if path != config / "attune/installation.json":
            raise ApprovalError("Registry must be config_root/attune/installation.json")
        protected = tuple(_resolve(Path(p), absent=True) for p in _protected_paths(config, state))
        registry_proof = _resolve(path)
        _collisions((registry_proof,), protected)
        registry, raw = _read_file(path, registry=True, outside=True)
        if registry.path != registry_proof:
            raise ApprovalError("Registry resolution changed during inspection")
        document = installation.parse_registry(raw.decode("utf-8"))
        declared_proofs = tuple(
            _resolve(_path(getattr(document.data, scope.value).lexical_path)) for scope in Scope
        )
        _collisions((registry.path, *declared_proofs), protected)
        routes = []
        for scope, declared_proof in zip(Scope, declared_proofs, strict=True):
            declaration = getattr(document.data, scope.value)
            if declared_proof.resolved_path != declaration.approved_resolved_path:
                raise ApprovalError(
                    f"Actual {scope} resolution differs from declared approved path"
                )
            file, raw = _read_file(
                _path(declaration.lexical_path), registry=False, outside=scope == Scope.DISPLAYS
            )
            if file.path != declared_proof:
                raise ApprovalError(f"Actual {scope} resolution changed during inspection")
            if Path(file.path.resolved_path).name != SCOPE_BASENAMES[scope]:
                raise ApprovalError(f"Wrong resolved basename for {scope}")
            parsed = scoped_config.read_document(raw.decode("utf-8"), expected_scope=scope)
            if not isinstance(parsed, scoped_config.ScopedConfig):
                raise ApprovalError("Explicit conversion required for legacy full bundle")
            routes.append(
                RouteEvidence(
                    scope,
                    file,
                    parsed.content_id,
                    tuple(
                        len(getattr(parsed, name))
                        for name in ("values", "beziers", "animations", "monitors")
                    ),
                )
            )
        result = InstallationEvidence(
            str(config),
            str(state),
            registry,
            tuple(routes),
            protected,
            datetime.now(UTC).isoformat(),
        )
        _collisions((registry.path, *(r.file.path for r in result.routes)), protected)
        # Recheck every dependency after both reads and protected alias checks.
        for proof in (registry.path, *(r.file.path for r in result.routes), *protected):
            for fact in proof.facts:
                if _fact(Path(fact.path)) != fact:
                    raise ApprovalError(f"Filesystem changed during inspection: {fact.path}")
        for file in (registry, *(r.file for r in result.routes)):
            for fact in file.git_context:
                if _fact(Path(fact.path)) != fact:
                    raise ApprovalError(f"Git context changed during inspection: {fact.path}")
        result.to_json()
        return result
    except (OSError, ValueError, RuntimeError) as exc:
        raise ApprovalError(f"Installation inspection refused: {exc}") from exc


def revalidate(evidence: InstallationEvidence) -> InstallationEvidence:
    """Recapture under a future caller's lock; unchanged evidence is not a permit."""
    checked = InstallationEvidence.from_json(evidence.to_json())
    current = inspect_installation(
        Path(checked.registry.path.lexical_path),
        config_root=Path(checked.config_root),
        state_root=Path(checked.state_root),
    )
    if current.evidence_hash != checked.evidence_hash:
        raise ApprovalError("Installation changed since review; inspect and review again")
    return current


def run_inspect(
    registry_path: Path,
    *,
    config_root: Path,
    state_root: Path,
    cancel_event: threading.Event | None = None,
    timeout: float = 10,
) -> InstallationEvidence:
    """Supervise isolated read-only inspection using only explicit path arguments."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ApprovalError("Inspection timeout must be finite and positive")
    paths = tuple(str(_path(p)) for p in (registry_path, config_root, state_root))
    result = health.run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.route_approval",
            "--registry",
            paths[0],
            "--config-root",
            paths[1],
            "--state-root",
            paths[2],
        ],
        timeout=timeout,
        max_bytes=MAX_EVIDENCE_BYTES,
        process_group=True,
        cwd=Path(__file__).absolute().parents[2],
        cancel_event=cancel_event,
    )
    if result.returncode:
        raise ApprovalError(f"Inspection worker refused: {result.stderr[:4096].strip()}")
    evidence = InstallationEvidence.from_json(result.stdout)
    if (evidence.registry.path.lexical_path, evidence.config_root, evidence.state_root) != paths:
        raise ApprovalError("Worker returned mismatching explicit context")
    return evidence


def run_revalidate(
    evidence: InstallationEvidence,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 10,
) -> InstallationEvidence:
    checked = InstallationEvidence.from_json(evidence.to_json())
    current = run_inspect(
        Path(checked.registry.path.lexical_path),
        config_root=Path(checked.config_root),
        state_root=Path(checked.state_root),
        cancel_event=cancel_event,
        timeout=timeout,
    )
    if current.evidence_hash != checked.evidence_hash:
        raise ApprovalError("Installation changed since review; inspect and review again")
    return current


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only installation inspector")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(
            inspect_installation(
                args.registry, config_root=args.config_root, state_root=args.state_root
            ).to_json()
        )
    except ApprovalError as error:
        parser.exit(1, f"{error}\n")
