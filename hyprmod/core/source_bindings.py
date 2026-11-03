"""Reviewed TSV source data only. Saves can trigger external filesystem watchers.

No callbacks, main Lua reads, compilation, reload or IPC. Mutators must run directly
on non-daemon workers; only the read-only observe/review modes are supervised.
"""

import argparse
import difflib
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import sys
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from hyprmod.core import health, persistence, route_approval
from hyprmod.core.bindings import _private_file, _safe_parent
from hyprmod.core.scopes import SCOPE_BASENAMES

BASENAME = "keybindings.tsv"
BRIDGE_BASENAME = "keybindings-bridge.lua"
BRIDGE_CAPABILITY = "-- Attune source bindings capabilities: disabled-v1"
UNASSIGNED_CAPABILITY = "-- Attune source bindings capabilities: unassigned-v1"
CATALOG = "jdawson.hyprland"
HEADER = f"# Attune source bindings v1\n# catalog: {CATALOG}\n"
COLUMNS = "id\tcontext\tsubmap\tflags\tkey\tdescription\n"
MAX_BINDS = 1000
MAX_INPUT_BYTES = 256 * 1024
MAX_KEY_CHARS = 256
MAX_DESCRIPTION_CHARS = 512
MAX_TRANSPORT_BYTES = 16 * 1024 * 1024
MAX_DIFF_BYTES = 2 * MAX_INPUT_BYTES + 65536
LOCK_TIMEOUT = 5.0
_FLAGS = {"auto_consuming", "locked", "repeating", "mouse", "disabled"}
_MODS = {
    "SHIFT": "SHIFT",
    "CAPS": "CAPS",
    "CTRL": "CTRL",
    "CONTROL": "CTRL",
    "ALT": "ALT",
    "MOD1": "ALT",
    "MOD2": "MOD2",
    "MOD3": "MOD3",
    "SUPER": "SUPER",
    "WIN": "SUPER",
    "LOGO": "SUPER",
    "MOD4": "SUPER",
    "MOD5": "MOD5",
}


def _text(value: object, limit: int) -> str:
    if (
        type(value) is not str
        or len(value) > limit
        or not value
        or any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in value)
    ):
        raise ValueError("Expected bounded text without controls")
    return value


def validate_key(key: str) -> str:
    _text(key, MAX_KEY_CHARS)
    parts = [part.strip(" ") for part in key.split("+")]
    if any(not part or any(c.isspace() for c in part) for part in parts):
        raise ValueError("Invalid shortcut")
    try:
        mods = [_MODS[part.upper()] for part in parts[:-1]]
    except KeyError as exc:
        raise ValueError("Unknown modifier") from exc
    if len(set(mods)) != len(mods):
        raise ValueError("Duplicate modifier")
    return key


def key_identity(key: str) -> tuple[tuple[str, ...], str]:
    parts = [part.strip(" ") for part in validate_key(key).split("+")]
    return tuple(sorted(_MODS[part.upper()] for part in parts[:-1])), parts[-1].lower()


@dataclass(frozen=True, slots=True)
class SourceBinding:
    id: str
    context: str
    submap: str
    flags: tuple[str, ...]
    key: str
    description: str

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_.-]*", _text(self.id, 256)):
            raise ValueError("Invalid source binding ID")
        if type(self.context) is not str or self.context not in {"global", "manager", "wisp"}:
            raise ValueError("Unknown descriptive context")
        if type(self.submap) is not str or self.submap not in {"", "wisp"}:
            raise ValueError("Unknown native submap")
        if (
            type(self.flags) is not tuple
            or any(type(flag) is not str or flag not in _FLAGS for flag in self.flags)
            or tuple(sorted(set(self.flags))) != self.flags
        ):
            raise ValueError("Expected sorted unique known flags")
        if type(self.key) is str and self.key == "":
            if "disabled" in self.flags:
                raise ValueError("Unassigned shortcuts cannot be disabled")
        else:
            validate_key(self.key)
        _text(self.description, MAX_DESCRIPTION_CHARS)

    @property
    def assigned(self) -> bool:
        return self.key != ""

    @property
    def enabled(self) -> bool:
        return self.assigned and "disabled" not in self.flags


@dataclass(frozen=True, slots=True)
class SourceConfig:
    catalog: str
    bindings: tuple[SourceBinding, ...]

    def __post_init__(self):
        if type(self.catalog) is not str or self.catalog != CATALOG:
            raise ValueError("Unknown source catalog")
        if type(self.bindings) is not tuple or not 1 <= len(self.bindings) <= MAX_BINDS:
            raise ValueError("Expected 1 to 1000 immutable source bindings")
        ids, combos = set(), set()
        size = len((HEADER + COLUMNS).encode("utf-8"))
        for row in self.bindings:
            if type(row) is not SourceBinding or SourceBinding(**asdict(row)) != row:
                raise ValueError("Expected exact immutable SourceBinding")
            if row.id in ids:
                raise ValueError("Duplicate ID or shortcut in native submap")
            ids.add(row.id)
            if row.enabled:
                identity = (row.submap, key_identity(row.key))
                if identity in combos:
                    raise ValueError("Duplicate ID or shortcut in native submap")
                combos.add(identity)
            size += len(_row_text(row).encode("utf-8"))
        if size > MAX_INPUT_BYTES:
            raise ValueError("Source bindings exceed 256 KiB")


def _row_text(row: SourceBinding) -> str:
    return (
        "\t".join((row.id, row.context, row.submap, ",".join(row.flags), row.key, row.description))
        + "\n"
    )


def _config(value: SourceConfig) -> SourceConfig:
    if type(value) is not SourceConfig or SourceConfig(value.catalog, value.bindings) != value:
        raise ValueError("Expected exact SourceConfig")
    return value


def build_text(config: SourceConfig) -> str:
    checked = _config(config)
    return HEADER + COLUMNS + "".join(_row_text(row) for row in checked.bindings)


def fixed_metadata(config: SourceConfig) -> tuple:
    return _config(config).catalog, tuple(
        (r.id, r.context, r.submap, tuple(f for f in r.flags if f != "disabled"))
        for r in config.bindings
    )


def read_text(text: str) -> SourceConfig:
    if type(text) is not str or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Source text exceeds 256 KiB")
    prefix = HEADER + COLUMNS
    if not text.startswith(prefix) or not text.endswith("\n"):
        raise ValueError("Unknown source header/schema or missing final LF")
    lines = text[len(prefix) : -1].split("\n")
    if len(lines) > MAX_BINDS:
        raise ValueError("Too many source bindings")
    rows = []
    for line in lines:
        fields = line.split("\t")
        if len(fields) != 6:
            raise ValueError("Expected six TSV columns")
        id, context, submap, flags, key, description = fields
        rows.append(
            SourceBinding(
                id, context, submap, tuple(flags.split(",")) if flags else (), key, description
            )
        )
    return SourceConfig(CATALOG, tuple(rows))


def _load(text: str) -> object:
    if type(text) is not str or len(text.encode("utf-8")) > MAX_TRANSPORT_BYTES:
        raise ValueError("Source transport exceeds limit")
    depth = tokens = 0
    quoted = escaped = False
    for char in text:
        if not quoted and char in '{}[],:"':
            tokens += 1
            if tokens > 524288:
                raise ValueError("Source transport exceeds token limit")
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
            if depth > 24:
                raise ValueError("Source transport exceeds nesting limit")
        elif char in "]}":
            depth -= 1
    return json.loads(text, object_pairs_hook=route_approval._unique)


def _config_from(value: object) -> SourceConfig:
    data = route_approval._fields(value, {"catalog", "bindings"})
    if type(data["bindings"]) is not list or len(data["bindings"]) > MAX_BINDS:
        raise ValueError("Invalid source bindings transport")
    rows = []
    for value in data["bindings"]:
        row = route_approval._fields(value, set(SourceBinding.__dataclass_fields__))
        if type(row["flags"]) is not list:
            raise ValueError("Invalid flags transport")
        rows.append(SourceBinding(**{**row, "flags": tuple(row["flags"])}))
    return SourceConfig(data["catalog"], tuple(rows))


def _config_root(config_root: Path | None) -> Path:
    return route_approval._path(
        config_root
        if config_root is not None
        else os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    )


def _protected_paths(lexical: Path, config_root: Path) -> tuple[Path, ...]:
    names = (
        "hyprland.lua",
        "hyprland.conf",
        "attune.lua",
        "attune-bindings.lua",
        BRIDGE_BASENAME,
        *SCOPE_BASENAMES.values(),
    )
    return tuple(
        dict.fromkeys(
            (
                *(config_root / "hypr" / name for name in names),
                config_root / "attune/installation.json",
                *(lexical.parent / name for name in names),
                lexical.parent.parent / "attune/installation.json",
            )
        )
    )


@dataclass(frozen=True, slots=True)
class SourceBaseline:
    lexical_path: str
    resolved_path: str
    state_root: str
    text: str
    config: SourceConfig
    proof: route_approval.PathProof
    config_root: str
    protected: tuple[route_approval.PathProof, ...]
    installed_route: route_approval.PathProof

    def __post_init__(self):
        for value in (self.lexical_path, self.resolved_path, self.state_root, self.config_root):
            if type(value) is not str:
                raise ValueError("Expected string source paths")
            route_approval._path(value)
        if any(Path(p).name != BASENAME for p in (self.lexical_path, self.resolved_path)):
            raise ValueError("Source requires lexical and resolved keybindings.tsv basename")
        if read_text(self.text) != _config(self.config):
            raise ValueError("Source baseline text/config mismatch")
        if type(self.proof) is not route_approval.PathProof:
            raise ValueError("Expected exact path proof")
        checked = route_approval._proof_from(_load(route_approval._json(asdict(self.proof))))
        if checked != self.proof or (checked.lexical_path, checked.resolved_path) != (
            self.lexical_path,
            self.resolved_path,
        ):
            raise ValueError("Invalid source path proof")
        leaves = [f for f in checked.facts if f.path == self.resolved_path]
        if not leaves:
            raise ValueError("Missing source leaf proof")
        identity = leaves[-1].identity
        if (
            len(identity) != 9
            or not stat.S_ISREG(identity[2])
            or identity[3] != os.getuid()
            or identity[5] != 1
            or identity[2] & 0o7133
            or identity[2] & 0o600 != 0o600
            or identity[6] != len(self.text.encode("utf-8"))
        ):
            raise ValueError("Source proof requires an existing safe file of exact size")
        if type(self.installed_route) is not route_approval.PathProof:
            raise ValueError("Expected exact installed source route proof")
        installed = route_approval._proof_from(
            _load(route_approval._json(asdict(self.installed_route)))
        )
        if installed != self.installed_route or installed.lexical_path != str(
            Path(self.config_root) / "hypr" / BASENAME
        ):
            raise ValueError("Installed source route differs from config context")
        paths = _protected_paths(Path(self.lexical_path), Path(self.config_root))
        if type(self.protected) is not tuple or len(self.protected) != len(paths):
            raise ValueError("Expected immutable protected path proofs for exact config context")
        for proof, path in zip(self.protected, paths, strict=True):
            if type(proof) is not route_approval.PathProof:
                raise ValueError("Expected exact protected path proof")
            checked = route_approval._proof_from(_load(route_approval._json(asdict(proof))))
            if checked != proof or proof.lexical_path != str(path):
                raise ValueError("Protected paths differ from source/config context")
            if any(
                route_approval._overlap(a, b)
                for a in (self.lexical_path, self.resolved_path)
                for b in (proof.lexical_path, proof.resolved_path)
            ) or any(
                fact.path == proof.resolved_path
                and fact.identity
                and fact.identity[:2] == identity[:2]
                for fact in proof.facts
            ):
                raise ValueError("Source and protected paths collide or alias")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        text = route_approval._json(asdict(self))
        if len(text) > MAX_TRANSPORT_BYTES:
            raise ValueError("Source baseline transport exceeds limit")
        return text

    @classmethod
    def from_json(cls, text: str) -> "SourceBaseline":
        data = route_approval._fields(_load(text), set(cls.__dataclass_fields__))
        paths = _protected_paths(
            route_approval._path(data["lexical_path"]), route_approval._path(data["config_root"])
        )
        if type(data["protected"]) is not list or len(data["protected"]) != len(paths):
            raise ValueError("Invalid protected path proofs transport")
        return cls(
            **{
                **data,
                "config": _config_from(data["config"]),
                "proof": route_approval._proof_from(data["proof"]),
                "installed_route": route_approval._proof_from(data["installed_route"]),
                "protected": tuple(route_approval._proof_from(p) for p in data["protected"]),
            }
        )


def _review_fields(baseline: SourceBaseline, proposal: SourceConfig) -> tuple:
    _config(proposal)

    if fixed_metadata(baseline.config) != fixed_metadata(proposal):
        raise ValueError(
            "Source metadata, IDs, base flags and order are read-only; "
            "keep every catalog row and clear its key to unassign a shortcut"
        )
    text = build_text(proposal)
    changes = tuple(
        difflib.unified_diff(
            baseline.text.splitlines(keepends=True),
            text.splitlines(keepends=True),
            fromfile=baseline.lexical_path + " (source)",
            tofile=baseline.resolved_path + " (proposed)",
            n=3,
        )
    )
    diff = "".join(changes)
    if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise ValueError("Source diff exceeds limit")
    added = sum(line.startswith("+") and not line.startswith("+++") for line in changes)
    removed = sum(line.startswith("-") and not line.startswith("---") for line in changes)
    digest = hashlib.sha256(
        route_approval._json(
            {
                "baseline": asdict(baseline),
                "source_sha256": baseline.sha256,
                "proposed": asdict(proposal),
                "text": text,
                "diff": diff,
                "added": added,
                "removed": removed,
            }
        ).encode("ascii")
    ).hexdigest()
    return text, diff, added, removed, digest


@dataclass(frozen=True, slots=True)
class SourceReview:
    baseline: SourceBaseline
    proposed: SourceConfig
    proposed_text: str
    diff: str
    added_lines: int
    removed_lines: int
    review_hash: str

    def __post_init__(self):
        if type(self.baseline) is not SourceBaseline:
            raise ValueError("Expected exact source baseline")
        if SourceBaseline.from_json(self.baseline.to_json()) != self.baseline:
            raise ValueError("Invalid source baseline")
        if type(self.added_lines) is not int or type(self.removed_lines) is not int:
            raise ValueError("Expected integer diff counts")
        if any(type(v) is not str for v in (self.proposed_text, self.diff, self.review_hash)):
            raise ValueError("Expected review strings")
        if _review_fields(self.baseline, self.proposed) != (
            self.proposed_text,
            self.diff,
            self.added_lines,
            self.removed_lines,
            self.review_hash,
        ):
            raise ValueError("Source review does not match exact request")

    def to_json(self) -> str:
        text = route_approval._json(asdict(self))
        if len(text) > MAX_TRANSPORT_BYTES:
            raise ValueError("Source review transport exceeds limit")
        return text

    @classmethod
    def from_json(cls, text: str) -> "SourceReview":
        data = route_approval._fields(_load(text), set(cls.__dataclass_fields__))
        return cls(
            **{
                **data,
                "baseline": SourceBaseline.from_json(route_approval._json(data["baseline"])),
                "proposed": _config_from(data["proposed"]),
            }
        )


@dataclass(frozen=True, slots=True)
class SourceSaveResult:
    outcome: Literal["saved", "no-op", "failed"]
    baseline: SourceBaseline | None
    backup_path: str | None
    may_have_written: bool
    error: str | None

    def __post_init__(self):
        if type(self.outcome) is not str or self.outcome not in {"saved", "no-op", "failed"}:
            raise ValueError("Invalid source save outcome")
        if type(self.may_have_written) is not bool:
            raise ValueError("Invalid publication uncertainty flag")
        if self.backup_path is not None:
            if type(self.backup_path) is not str:
                raise ValueError("Expected backup path string")
            route_approval._path(self.backup_path)
        if self.outcome == "failed":
            if self.baseline is not None or type(self.error) is not str or not self.error:
                raise ValueError("Failed save cannot have an adoptable baseline")
        else:
            if type(self.baseline) is not SourceBaseline or self.error is not None:
                raise ValueError("Success requires a verified source baseline")
            if SourceBaseline.from_json(self.baseline.to_json()) != self.baseline:
                raise ValueError("Invalid success baseline")
            if self.may_have_written != (self.outcome == "saved"):
                raise ValueError("Publication flag differs from outcome")
            if (self.backup_path is None) != (self.outcome == "no-op"):
                raise ValueError("Saved source requires backup; no-op must not have one")


def observe(path: Path, state_root: Path, *, config_root: Path | None = None) -> SourceBaseline:
    lexical, state = route_approval._path(path), route_approval._path(state_root)
    actual_config = _config_root(config_root)
    if lexical.name != BASENAME:
        raise ValueError("Select an existing keybindings.tsv")
    proof = route_approval._resolve(lexical)
    target = Path(proof.resolved_path)
    if target.name != BASENAME:
        raise ValueError("Resolved source basename must be keybindings.tsv")
    _safe_parent(target)
    _private_file(target, private=False)
    # The selected source may be outside the active config tree, including in Stow.
    # Only stat protected paths and aliases; never open authored configuration.
    protected = tuple(
        route_approval._resolve(p, absent=True) for p in _protected_paths(lexical, actual_config)
    )
    installed_route = route_approval._resolve(actual_config / "hypr" / BASENAME, absent=True)
    # Do not freeze absent state paths: this writer creates its own private storage.
    route_approval._collisions(
        (proof,), (*protected, route_approval._resolve(state / "attune", absent=True))
    )
    raw = persistence.read_stable(target, limit=MAX_INPUT_BYTES)
    text = raw.decode("utf-8")
    config = read_text(text)
    git = route_approval._git_context(proof, outside=False)
    dependencies = (*proof.facts, *git)
    if any(
        route_approval._fact(Path(f.path)) != f
        for f in (*dependencies, *installed_route.facts, *(f for p in protected for f in p.facts))
    ):
        raise ValueError("Source dependencies changed during observation")
    if route_approval._resolve(lexical) != proof:
        raise ValueError("Source route changed during observation")
    if route_approval._resolve(actual_config / "hypr" / BASENAME, absent=True) != installed_route:
        raise ValueError("Installed source route changed during observation")
    return SourceBaseline(
        str(lexical),
        str(target),
        str(state),
        text,
        config,
        route_approval.PathProof(str(lexical), str(target), dependencies),
        str(actual_config),
        protected,
        installed_route,
    )


def _check_bridge(baseline: SourceBaseline, proposal: SourceConfig) -> None:
    unassigned = any(not row.assigned for row in proposal.bindings)
    disabled = any("disabled" in row.flags for row in proposal.bindings)
    if not unassigned and not disabled:
        return
    bridges = [Path(baseline.lexical_path).parent / BRIDGE_BASENAME]
    installed = baseline.installed_route
    selected_identity = next(
        f.identity[:2] for f in reversed(baseline.proof.facts) if f.path == baseline.resolved_path
    )
    if installed.resolved_path == baseline.resolved_path or any(
        f.path == installed.resolved_path
        and len(f.identity) == 9
        and stat.S_ISREG(f.identity[2])
        and f.identity[:2] == selected_identity
        for f in installed.facts
    ):
        bridges.append(Path(installed.lexical_path).parent / BRIDGE_BASENAME)
    message = (
        "Update the source keybindings bridge before saving disabled or unassigned shortcuts "
        f"(requires disabled-v1{' and unassigned-v1' if unassigned else ''}); "
        "older bridges would restore defaults."
    )
    try:
        for bridge in dict.fromkeys(bridges):
            proof = route_approval._resolve(bridge)
            if proof not in baseline.protected:
                raise ValueError(message)
            route_approval._collisions(
                (proof,),
                tuple(
                    p for p in baseline.protected if Path(p.lexical_path).name != BRIDGE_BASENAME
                ),
            )
            target = Path(proof.resolved_path)
            _safe_parent(target)
            _private_file(target, private=False)
            # Only the versioned capability header is read, never authored main Lua.
            fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb", buffering=0) as stream:
                identity = route_approval._stat_identity(os.fstat(stream.fileno()))
                if identity != next(
                    f.identity for f in reversed(proof.facts) if f.path == str(target)
                ):
                    raise ValueError(message)
                header = (BRIDGE_CAPABILITY + "\n").encode()
                if unassigned:
                    header += (UNASSIGNED_CAPABILITY + "\n").encode()
                if stream.read(len(header)) != header:
                    raise ValueError(message)
                if identity != route_approval._stat_identity(os.fstat(stream.fileno())):
                    raise ValueError(message)
            if route_approval._resolve(bridge) != proof:
                raise ValueError(message)
    except (OSError, ValueError) as exc:
        raise ValueError(message) from exc


def prepare_review(baseline: SourceBaseline, proposal: SourceConfig) -> SourceReview:
    if type(baseline) is not SourceBaseline:
        raise ValueError("Expected exact source baseline")
    checked = SourceBaseline.from_json(baseline.to_json())
    if (
        checked != baseline
        or observe(
            Path(checked.lexical_path),
            Path(checked.state_root),
            config_root=Path(checked.config_root),
        )
        != checked
    ):
        raise ValueError("Source changed since observation; review again")
    fields = _review_fields(checked, proposal)
    _check_bridge(checked, proposal)
    return SourceReview(checked, proposal, *fields)


def _proof_binding(proof: route_approval.PathProof, replaced: str) -> tuple:
    # Atomic publication may change only the regular file leaf at our selected target.
    return (
        proof.lexical_path,
        proof.resolved_path,
        tuple(
            (
                f.path,
                ()
                if f.path == proof.resolved_path == replaced
                and len(f.identity) == 9
                and stat.S_ISREG(f.identity[2])
                else f.identity,
                f.link_target,
            )
            for f in proof.facts
        ),
    )


def persist_reviewed(
    review: SourceReview,
    proposal: SourceConfig,
    *,
    cancel_event: threading.Event | None = None,
) -> SourceSaveResult:
    attempted = backup_verified = False
    backup = None
    try:
        if threading.current_thread().daemon:
            raise ValueError("Source Save requires a direct non-daemon worker")
        if type(review) is not SourceReview:
            raise ValueError("Expected exact source review")
        checked = SourceReview.from_json(review.to_json())
        if checked != review or _config(proposal) != checked.proposed:
            raise ValueError("Source draft changed since review")
        baseline = checked.baseline
        lexical, target = Path(baseline.lexical_path), Path(baseline.resolved_path)
        state_root = Path(baseline.state_root)
        state = state_root / "attune"
        backups = state / "source-bindings-backups"
        lock_path = state / "source-bindings.lock"

        def check_source():
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Source Save cancelled before publication")
            if observe(lexical, state_root, config_root=Path(baseline.config_root)) != baseline:
                raise ValueError("Source bytes or route changed; review again")
            _check_bridge(baseline, proposal)

        def check_storage():
            proof = route_approval._resolve(backups, absent=True)
            if any(f.link_target is not None for f in proof.facts):
                raise ValueError("Source state ancestors must not be symlinks")
            # _git_context checks parents, so include the backup root itself explicitly.
            if route_approval._fact(backups / ".git").identity:
                raise ValueError("Source backups must be outside Git")
            route_approval._git_context(proof, outside=True)
            for directory in (state_root, state, backups):
                if directory.exists() or directory.is_symlink():
                    if directory == state_root:
                        _safe_parent(directory / "placeholder")
                    else:
                        persistence._private_directory(directory, create=False)
            if lock_path.exists() or lock_path.is_symlink():
                _private_file(lock_path)

        check_source()
        check_storage()
        state_proof = route_approval._resolve(state_root, absent=True)
        if not state_root.exists():
            _safe_parent(state_root)
        candidate = backups / (baseline.sha256 + ".tsv")
        if candidate.exists() or candidate.is_symlink():
            _private_file(candidate)
            if persistence.read_stable(candidate, limit=MAX_INPUT_BYTES) != baseline.text.encode():
                raise ValueError("Source backup collision")
        route_approval._collisions(
            (route_approval._resolve(target),), (route_approval._resolve(state, absent=True),)
        )
        for fact in state_proof.facts:
            if route_approval._fact(Path(fact.path)) != fact:
                raise ValueError("Source state route changed before creation")
        if not state_root.exists():
            state_root.mkdir(mode=0o700)
        persistence._private_directory(state, create=True)
        if any(
            fact.identity and route_approval._fact(Path(fact.path)) != fact
            for fact in state_proof.facts
        ):
            raise ValueError("Source state ancestors changed during creation")
        state_facts = route_approval._resolve(state).facts
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        with os.fdopen(fd, "r+b") as lock:
            _private_file(lock_path)
            lock_fact = route_approval._fact(lock_path)
            if route_approval._stat_identity(os.fstat(lock.fileno())) != lock_fact.identity:
                raise ValueError("Source lock changed before acquisition")

            def check_state():
                check_storage()
                if any(route_approval._fact(Path(f.path)) != f for f in (*state_facts, lock_fact)):
                    raise ValueError("Source state or lock changed")

            deadline = time.monotonic() + LOCK_TIMEOUT
            while True:
                check_source()
                check_state()
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Source lock timed out") from None
                    time.sleep(0.05)
            check_source()
            check_state()
            if baseline.text == checked.proposed_text:
                fresh = observe(lexical, state_root, config_root=Path(baseline.config_root))
                check_state()
                if fresh != baseline:
                    raise ValueError("Source changed before no-op completion")
                return SourceSaveResult("no-op", fresh, None, False, None)
            persistence._private_directory(backups, create=True)
            backup_directory = route_approval._resolve(backups)
            backup = candidate
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
                        raise ValueError("Source backup route or identity changed")
                _private_file(backup)
                if persistence.read_stable(backup, limit=MAX_INPUT_BYTES) != baseline.text.encode():
                    raise ValueError("Source backup differs from reviewed prior")

            verify_backup()
            backup_fd = os.open(backup, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                if route_approval._stat_identity(os.fstat(backup_fd)) != backup_fact.identity:
                    raise ValueError("Source backup changed before sync")
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
                verify_backup()
                check_source()
                # Rename may succeed before directory sync raises. Never report that as clean.
                attempted = True

            persistence._atomic_write(
                target, checked.proposed_text.encode("utf-8"), before_replace=before_replace
            )
            fresh = observe(lexical, state_root, config_root=Path(baseline.config_root))
            check_state()
            if (
                fresh.text != checked.proposed_text
                or fresh.config != proposal
                or fresh.resolved_path != str(target)
                or fresh.config_root != baseline.config_root
                or fresh.protected != baseline.protected
                or _proof_binding(baseline.proof, str(target))
                != _proof_binding(fresh.proof, str(target))
                or _proof_binding(baseline.installed_route, str(target))
                != _proof_binding(fresh.installed_route, str(target))
            ):
                raise ValueError("Source post-save verification failed")
            return SourceSaveResult("saved", fresh, str(backup), True, None)
    except (OSError, ValueError, RuntimeError) as exc:
        return SourceSaveResult(
            "failed",
            None,
            str(backup) if backup_verified else None,
            attempted,
            str(exc) or type(exc).__name__,
        )


def _run_worker(
    mode: str,
    paths: tuple[str, str, str],
    request: str | None,
    cancel_event: threading.Event | None,
    timeout: float,
) -> str:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Source worker timeout must be finite and positive")
    result = health.run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.source_bindings",
            mode,
            "--path",
            paths[0],
            "--state-root",
            paths[1],
            "--config-root",
            paths[2],
        ],
        timeout=timeout,
        max_bytes=MAX_TRANSPORT_BYTES,
        process_group=True,
        cwd=Path(__file__).absolute().parents[2],
        cancel_event=cancel_event,
        input_text=request,
    )
    if result.returncode:
        raise ValueError(f"Source worker refused: {result.stderr[:4096].strip()}")
    return result.stdout


def run_observe(
    path: Path,
    state_root: Path,
    *,
    config_root: Path | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float = 15,
) -> SourceBaseline:
    paths = (
        str(route_approval._path(path)),
        str(route_approval._path(state_root)),
        str(_config_root(config_root)),
    )
    baseline = SourceBaseline.from_json(_run_worker("observe", paths, None, cancel_event, timeout))
    if (baseline.lexical_path, baseline.state_root, baseline.config_root) != paths:
        raise ValueError("Source worker returned different context")
    return baseline


def run_prepare_review(
    baseline: SourceBaseline,
    proposal: SourceConfig,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> SourceReview:
    if type(baseline) is not SourceBaseline:
        raise ValueError("Expected exact source baseline")
    checked = SourceBaseline.from_json(baseline.to_json())
    if checked != baseline:
        raise ValueError("Invalid source baseline")
    _config(proposal)
    request = route_approval._json({"baseline": asdict(checked), "proposal": asdict(proposal)})
    review = SourceReview.from_json(
        _run_worker(
            "review",
            (baseline.lexical_path, baseline.state_root, baseline.config_root),
            request,
            cancel_event,
            timeout,
        )
    )
    if review.baseline != baseline or review.proposed != proposal:
        raise ValueError("Source worker returned a different review request")
    return review


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only source bindings worker")
    parser.add_argument("mode", choices=("observe", "review"))
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--config-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == "observe":
            print(observe(args.path, args.state_root, config_root=args.config_root).to_json())
        else:
            request = route_approval._fields(
                _load(sys.stdin.read(MAX_TRANSPORT_BYTES + 1)), {"baseline", "proposal"}
            )
            baseline = SourceBaseline.from_json(route_approval._json(request["baseline"]))
            if (baseline.lexical_path, baseline.state_root, baseline.config_root) != (
                str(args.path),
                str(args.state_root),
                str(args.config_root),
            ):
                raise ValueError("Source review context differs from request")
            print(prepare_review(baseline, _config_from(request["proposal"])).to_json())
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
