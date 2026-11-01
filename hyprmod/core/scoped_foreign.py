"""Bounded read-only foreign CURRENT observations, never write or Lua authority.

Transaction status is UNASSESSED: no journal is scanned or read. Invoke direct
filesystem operations off GTK, or use the isolated observe-only worker.
"""

import argparse
import base64
import binascii
import hashlib
import json
import math
import re
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hyprmod.core import health, installation, persistence, route_approval, scoped_config
from hyprmod.core.route_approval import (
    ApprovalError,
    FileEvidence,
    PathFact,
    PathProof,
    RouteEvidence,
)
from hyprmod.core.scopes import Scope

MAX_INPUT_BYTES = scoped_config.MAX_INPUT_BYTES
MAX_INPUT_LINES = 10000
MAX_METADATA_BYTES = route_approval.MAX_EVIDENCE_BYTES
MAX_OBSERVATION_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 24


def _decode(text: str) -> object:
    if type(text) is not str or len(text.encode("utf-8")) > MAX_OBSERVATION_BYTES:
        raise ApprovalError("Observation exceeds 8 MiB transport limit")
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
                raise ApprovalError("Observation nesting exceeds limit")
        elif char in "]}":
            depth -= 1

    def invalid_constant(value: str) -> object:
        raise ApprovalError(f"Invalid JSON constant: {value}")

    result = json.loads(
        text, object_pairs_hook=route_approval._unique, parse_constant=invalid_constant
    )
    if len(route_approval._json(result)) > MAX_OBSERVATION_BYTES:
        raise ApprovalError("Observation exceeds 8 MiB ASCII transport limit")
    return result


def _text(text: str, *, selected: bool) -> bytes:
    if type(text) is not str:
        raise ApprovalError("Expected text")
    raw = text.encode("utf-8", "strict")
    if not 0 < len(raw) <= MAX_INPUT_BYTES:
        raise ApprovalError("Expected nonempty text of at most 1 MiB")
    if selected and len(text.splitlines()) > MAX_INPUT_LINES:
        raise ApprovalError("Selected text exceeds 10000 lines")
    if any((ord(c) < 32 and c not in "\t\r\n") or 127 <= ord(c) <= 159 for c in text):
        raise ApprovalError("Binary/control characters are not observable UTF-8 text")
    return raw


def _classify(text: str, scope: Scope) -> str:
    # Dispatch without expected_scope so canonical cross-scope/v1 is never foreign.
    try:
        parsed = scoped_config.read_document(text)
    except ValueError:
        for line in text.splitlines():
            # Only header detection permits a leading run of BOM/space/tab characters.
            # Ownership classification below still uses the exact original marker.
            record = re.match(r"[\ufeff \t]*-- Attune data v([^: \t]+)(?=:|[ \t]|$)", line)
            if record is None:
                continue
            if record[1] not in ("1", "2"):
                raise ApprovalError("Unsupported Attune record version")
            if ":" not in line:
                continue
            try:
                data = json.loads(
                    base64.b64decode(line.split(":", 1)[1].strip(), validate=True),
                    object_pairs_hook=route_approval._unique,
                )
            except (ValueError, binascii.Error, UnicodeError, RecursionError):
                continue
            if (
                type(data) is dict
                and type(data.get("version")) is int
                and data["version"] not in (1, 2)
            ):
                raise ApprovalError("Unsupported Attune record version")
        if text.startswith(persistence.MARKER):
            return "invalid-scoped"
        return "foreign"
    if isinstance(parsed, scoped_config.LegacyBundle):
        raise ApprovalError("Legacy full bundle requires explicit conversion")
    if parsed.scope != scope:
        raise ApprovalError("Canonical selected file belongs to another scope")
    raise ApprovalError("Canonical selected file requires canonical restore")


def _immutable(value: object, expected: type) -> None:
    """Check original nested DTO types before asdict/JSON can hide mutable inputs."""
    if type(value) is not expected:
        raise ApprovalError(f"Expected exact {expected.__name__}")
    if isinstance(value, FileEvidence):
        _immutable(value.path, PathProof)
        facts = value.git_context
    elif isinstance(value, PathProof):
        if type(value.lexical_path) is not str or type(value.resolved_path) is not str:
            raise ApprovalError("Expected path strings")
        facts = value.facts
    elif isinstance(value, PathFact):
        if (
            type(value.path) is not str
            or type(value.identity) is not tuple
            or len(value.identity) not in (0, 5, 9)
            or any(type(n) is not int for n in value.identity)
            or (value.link_target is not None and type(value.link_target) is not str)
        ):
            raise ApprovalError("Expected immutable path fact")
        return
    elif isinstance(value, RouteEvidence):
        if (
            type(value.scope) is not Scope
            or type(value.content_id) is not str
            or type(value.counts) is not tuple
            or len(value.counts) != 4
            or any(type(n) is not int for n in value.counts)
        ):
            raise ApprovalError("Expected immutable canonical route")
        _immutable(value.file, FileEvidence)
        return
    else:
        raise ApprovalError("Unknown evidence type")
    if isinstance(value, FileEvidence) and type(value.source_sha256) is not str:
        raise ApprovalError("Expected source digest")
    if type(facts) is not tuple or not 1 <= len(facts) <= route_approval.MAX_FACTS:
        raise ApprovalError("Expected bounded immutable facts")
    for fact in facts:
        _immutable(fact, PathFact)


def _validate_file(file: FileEvidence, text: str) -> None:
    raw = _text(text, selected=False)
    if file.source_sha256 != hashlib.sha256(raw).hexdigest():
        raise ApprovalError("Text byte hash mismatch")
    leaf = next(f for f in reversed(file.path.facts) if f.path == file.path.resolved_path)
    if leaf.identity[6] != len(raw):
        raise ApprovalError("Text does not match leaf size")


@dataclass(frozen=True, slots=True)
class ForeignCurrentEvidence:
    scope: Scope
    file: FileEvidence
    status: str
    text: str

    def __post_init__(self) -> None:
        if (
            type(self.scope) is not Scope
            or type(self.status) is not str
            or type(self.text) is not str
        ):
            raise ApprovalError("Expected selected scope and classification")
        _immutable(self.file, FileEvidence)
        route_approval._file_from(json.loads(route_approval._json(asdict(self.file))))
        _text(self.text, selected=True)
        _validate_file(self.file, self.text)
        if self.status != _classify(self.text, self.scope):
            raise ApprovalError("Selected classification mismatch")


@dataclass(frozen=True, slots=True)
class CanonicalSiblingEvidence:
    route: RouteEvidence
    text: str

    def __post_init__(self) -> None:
        if type(self.text) is not str:
            raise ApprovalError("Expected sibling text")
        _immutable(self.route, RouteEvidence)
        route_approval._file_from(json.loads(route_approval._json(asdict(self.route.file))))
        _validate_file(self.route.file, self.text)
        parsed = scoped_config.read_document(self.text, expected_scope=self.route.scope)
        if not isinstance(parsed, scoped_config.ScopedConfig):
            raise ApprovalError("Sibling must be canonical v2")
        if self.route.content_id != parsed.content_id or self.route.counts != tuple(
            len(getattr(parsed, name)) for name in ("values", "beziers", "animations", "monitors")
        ):
            raise ApprovalError("Sibling canonical ID/counts mismatch")


@dataclass(frozen=True, slots=True)
class ScopedForeignObservation:
    config_root: str
    state_root: str
    selected_scope: Scope
    registry: FileEvidence
    selected: ForeignCurrentEvidence
    sibling: CanonicalSiblingEvidence
    protected: tuple[PathProof, ...]
    observed_at: str

    def __post_init__(self) -> None:
        if (
            type(self) is not ScopedForeignObservation
            or type(self.config_root) is not str
            or type(self.state_root) is not str
            or type(self.selected_scope) is not Scope
            or type(self.selected) is not ForeignCurrentEvidence
            or type(self.sibling) is not CanonicalSiblingEvidence
            or type(self.protected) is not tuple
            or len(self.protected) != 4
            or type(self.observed_at) is not str
        ):
            raise ApprovalError("Expected exact immutable observation types")
        config = route_approval._path(self.config_root)
        state = route_approval._path(self.state_root)
        _immutable(self.registry, FileEvidence)
        _immutable(self.selected.file, FileEvidence)
        _immutable(self.sibling.route, RouteEvidence)
        if (
            type(self.selected.scope) is not Scope
            or type(self.selected.status) is not str
            or type(self.selected.text) is not str
            or type(self.sibling.text) is not str
        ):
            raise ApprovalError("Expected original immutable scoped evidence")
        for proof in self.protected:
            _immutable(proof, PathProof)
        route_approval._file_from(json.loads(route_approval._json(asdict(self.registry))))
        self.selected.__post_init__()
        self.sibling.__post_init__()
        if self.registry.path.lexical_path != str(config / "attune/installation.json"):
            raise ApprovalError("Registry does not match explicit context")
        if (
            self.selected.scope is not self.selected_scope
            or self.sibling.route.scope is self.selected_scope
        ):
            raise ApprovalError("Expected selected and opposite sibling scopes")
        for scope, file in (
            (self.selected.scope, self.selected.file),
            (self.sibling.route.scope, self.sibling.route.file),
        ):
            installation.ScopeRoute(scope, file.path.lexical_path, file.path.resolved_path)
        for proof in self.protected:
            route_approval._proof_from(json.loads(route_approval._json(asdict(proof))))
        if tuple(p.lexical_path for p in self.protected) != route_approval._protected_paths(
            config, state
        ):
            raise ApprovalError("Protected paths do not match explicit context")
        stamp = self.observed_at
        if (
            type(stamp) is not str
            or len(stamp) > 64
            or "T" not in stamp
            or datetime.fromisoformat(stamp).utcoffset() != timedelta(0)
        ):
            raise ApprovalError("Expected UTC observation timestamp")
        frame = self._frame()
        if len(frame) > MAX_OBSERVATION_BYTES:
            raise ApprovalError("Observation exceeds 8 MiB ASCII transport limit")
        data = json.loads(frame)
        del data["observation"]["selected"]["text"]
        del data["observation"]["sibling"]["text"]
        if len(route_approval._json(data)) > MAX_METADATA_BYTES:
            raise ApprovalError("Observation metadata exceeds 1 MiB")

    @property
    def observation_hash(self) -> str:
        data = asdict(self)
        del data["observed_at"]
        return hashlib.sha256(route_approval._json(data).encode("ascii")).hexdigest()

    def _frame(self) -> str:
        return route_approval._json(
            {
                "schema": 1,
                "kind": "scoped-foreign-observation",
                "observation": asdict(self),
                "observation_hash": self.observation_hash,
            }
        )

    def to_json(self) -> str:
        self.__post_init__()
        return self._frame()

    @classmethod
    def from_json(cls, text: str) -> "ScopedForeignObservation":
        try:
            frame = route_approval._fields(
                _decode(text), {"schema", "kind", "observation", "observation_hash"}
            )
            if (
                type(frame["schema"]) is not int
                or frame["schema"] != 1
                or frame["kind"] != "scoped-foreign-observation"
            ):
                raise ApprovalError("Unknown observation format")
            data = route_approval._fields(frame["observation"], set(cls.__dataclass_fields__))
            selected = route_approval._fields(
                data["selected"], set(ForeignCurrentEvidence.__dataclass_fields__)
            )
            sibling = route_approval._fields(
                data["sibling"], set(CanonicalSiblingEvidence.__dataclass_fields__)
            )
            route = route_approval._fields(
                sibling["route"], set(RouteEvidence.__dataclass_fields__)
            )
            if (
                type(data["selected_scope"]) is not str
                or type(selected["scope"]) is not str
                or type(route["scope"]) is not str
                or type(route["counts"]) is not list
                or type(data["protected"]) is not list
            ):
                raise ApprovalError("Expected scope strings and evidence arrays")
            result = cls(
                data["config_root"],
                data["state_root"],
                Scope(data["selected_scope"]),
                route_approval._file_from(data["registry"]),
                ForeignCurrentEvidence(
                    Scope(selected["scope"]),
                    route_approval._file_from(selected["file"]),
                    selected["status"],
                    selected["text"],
                ),
                CanonicalSiblingEvidence(
                    RouteEvidence(
                        Scope(route["scope"]),
                        route_approval._file_from(route["file"]),
                        route["content_id"],
                        tuple(route["counts"]),
                    ),
                    sibling["text"],
                ),
                tuple(route_approval._proof_from(p) for p in data["protected"]),
                data["observed_at"],
            )
            if result.observation_hash != route_approval._digest(frame["observation_hash"]):
                raise ApprovalError("Observation fingerprint mismatch")
            return result
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
            raise ApprovalError(f"Invalid foreign observation: {exc}") from exc


def observe_current(
    config_root: Path, state_root: Path, selected_scope: Scope
) -> ScopedForeignObservation:
    """Observe foreign CURRENT plus its canonical sibling without transaction assessment."""
    if type(selected_scope) is not Scope:
        raise ApprovalError("Expected exact selected Scope")
    try:
        collection = route_approval._collect_filesystem(
            config_root / "attune/installation.json", config_root=config_root, state_root=state_root
        )
        selected = sibling = None
        for scope, file, raw in collection.routes:
            text = raw.decode("utf-8", "strict")
            if scope is selected_scope:
                _text(text, selected=True)
                selected = ForeignCurrentEvidence(scope, file, _classify(text, scope), text)
            else:
                parsed = scoped_config.read_document(text, expected_scope=scope)
                if not isinstance(parsed, scoped_config.ScopedConfig):
                    raise ApprovalError("Sibling must be canonical v2")
                sibling = CanonicalSiblingEvidence(
                    RouteEvidence(
                        scope,
                        file,
                        parsed.content_id,
                        tuple(
                            len(getattr(parsed, name))
                            for name in ("values", "beziers", "animations", "monitors")
                        ),
                    ),
                    text,
                )
        if selected is None or sibling is None:
            raise ApprovalError("Expected both scoped files")
        result = ScopedForeignObservation(
            collection.config_root,
            collection.state_root,
            selected_scope,
            collection.registry,
            selected,
            sibling,
            collection.protected,
            datetime.now(UTC).isoformat(),
        )
        route_approval._final_check(collection)
        recaptured = route_approval._collect_filesystem(
            config_root / "attune/installation.json", config_root=config_root, state_root=state_root
        )
        if recaptured != collection:
            raise ApprovalError("Filesystem or bytes changed during foreign observation")
        return result
    except (OSError, ValueError, RuntimeError) as exc:
        raise ApprovalError(f"Foreign observation refused: {exc}") from exc


def revalidate_current(observation: ScopedForeignObservation) -> ScopedForeignObservation:
    if type(observation) is not ScopedForeignObservation:
        raise ApprovalError("Expected exact foreign observation")
    observation.__post_init__()
    current = observe_current(
        Path(observation.config_root), Path(observation.state_root), observation.selected_scope
    )
    if current.observation_hash != observation.observation_hash:
        raise ApprovalError("Foreign CURRENT changed; observe again")
    return current


def run_observe(
    config_root: Path,
    state_root: Path,
    selected_scope: Scope,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> ScopedForeignObservation:
    if type(selected_scope) is not Scope:
        raise ApprovalError("Expected exact selected Scope")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ApprovalError("Observation timeout must be finite and positive")
    roots = tuple(str(route_approval._path(p)) for p in (config_root, state_root))
    result = health.run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.scoped_foreign",
            "observe",
            "--config-root",
            roots[0],
            "--state-root",
            roots[1],
            "--scope",
            selected_scope.value,
        ],
        timeout=timeout,
        max_bytes=MAX_OBSERVATION_BYTES,
        process_group=True,
        cwd=Path(__file__).absolute().parents[2],
        cancel_event=cancel_event,
    )
    if result.returncode:
        raise ApprovalError(f"Observation worker refused: {result.stderr[:4096].strip()}")
    observation = ScopedForeignObservation.from_json(result.stdout)
    if (observation.config_root, observation.state_root, observation.selected_scope) != (
        *roots,
        selected_scope,
    ):
        raise ApprovalError("Worker returned mismatching explicit context or selection")
    return observation


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only foreign CURRENT observer")
    parser.add_argument("mode", choices=("observe",))
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--scope", type=Scope, choices=tuple(Scope), required=True)
    args = parser.parse_args()
    try:
        print(observe_current(args.config_root, args.state_root, args.scope).to_json())
    except ApprovalError as error:
        parser.exit(1, f"{error}\n")
