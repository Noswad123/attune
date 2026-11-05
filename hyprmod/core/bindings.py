"""Reviewed, dedicated keyboard bindings. Input Lua is data, never executed."""

import argparse
import base64
import binascii
import difflib
import hashlib
import json
import math
import os
import re
import stat
import sys
import threading
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from hyprland_config import BindData, dispatch_to_lua, keyword_to_lua, parse_bind_line

from hyprmod.core import health, owned_output, persistence, route_approval
from hyprmod.core.owned_output import fcntl as fcntl

BASENAME = "attune-bindings.lua"
RECORD = "-- Attune bindings data v1: "
MAX_BINDS = 1000
MAX_INPUT_BYTES = owned_output.MAX_INPUT_BYTES
MAX_LINE_BYTES = MAX_INPUT_BYTES
MAX_DIFF_BYTES = 2 * MAX_INPUT_BYTES + 65536
MAX_TRANSPORT_BYTES = 32 * MAX_INPUT_BYTES
MAX_JSON_DEPTH = 24
MAX_JSON_TOKENS = 262144
LOCK_TIMEOUT = owned_output.LOCK_TIMEOUT
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


def validate_line(line: str) -> BindData:
    if type(line) is not str or len(line.encode("utf-8")) > MAX_LINE_BYTES:
        raise ValueError("Expected bounded binding directive")
    if any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in line):
        raise ValueError("Binding controls are not supported")
    parsed = parse_bind_line(line)
    if parsed is None or parsed.to_line() != line:
        raise ValueError("Binding must round-trip exactly")
    if parsed.bind_type not in {"bind", "binde", "bindl", "bindr", "bindn"}:
        raise ValueError("Only global keyboard bind/binde/bindl/bindr/bindn are supported")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*|[0-9]|0x[0-9a-fA-F]+", parsed.key):
        raise ValueError("Expected keyboard keysym, not mouse, keycode or catchall")
    if (
        parsed.key.lower() in {"catchall", "any"}
        or parsed.key.lower().startswith("mouse")
        or parsed.dispatcher == "submap"
    ):
        raise ValueError("Catchall and submap bindings are unsupported")
    try:
        mods = [_MODS[mod.upper()] for mod in parsed.mods]
    except KeyError as exc:
        raise ValueError("Unsupported modifier") from exc
    if len(set(mods)) != len(mods):
        raise ValueError("Duplicate modifier")
    parsed.mods = sorted(mods)
    canonical = parsed.to_line()
    reparsed = parse_bind_line(canonical)
    if reparsed is None or reparsed.to_line() != canonical:
        raise ValueError("Canonical binding cannot round-trip")
    key, _, value = canonical.partition(" = ")
    dispatch = dispatch_to_lua(parsed.dispatcher, parsed.arg)
    if parsed.dispatcher in {"exec", "execr"}:
        method = "exec_cmd" if parsed.dispatcher == "exec" else "exec_raw"
        literal = re.fullmatch(
            r"hl\.dispatch\(hl\.dsp\." + method + r'\(("(?:[^"\\]|\\.)*")\)\)', dispatch
        )
        message = (
            f"The library cannot prove literal emission of this {parsed.dispatcher} command. "
            "Use an explicit direct action, or Raw command only if intended."
        )
        try:
            command = json.loads(literal[1]) if literal is not None else None
        except ValueError as exc:
            raise ValueError(message) from exc
        if command != parsed.arg:
            raise ValueError(message)
    keyword_to_lua(key, value)
    return parsed


def combo(line: str) -> tuple[tuple[str, ...], str]:
    return validate_line(line).combo


@dataclass(frozen=True, slots=True)
class BindingsConfig:
    lines: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.lines) is not tuple or len(self.lines) > MAX_BINDS:
            raise ValueError("Expected at most 1000 immutable binding lines")
        if any(type(line) is not str for line in self.lines):
            raise ValueError("Expected string binding lines")
        if sum(len(line.encode("utf-8")) + 1 for line in self.lines) > MAX_INPUT_BYTES:
            raise ValueError("Bindings exceed 1 MiB")
        parsed = tuple(validate_line(line) for line in self.lines)
        if len({bind.combo for bind in parsed}) != len(parsed):
            raise ValueError("Duplicate keyboard combination")
        lines = tuple(bind.to_line() for bind in parsed)
        object.__setattr__(self, "lines", lines)


def _config(value: object) -> BindingsConfig:
    if type(value) is not BindingsConfig or BindingsConfig(value.lines) != value:
        raise ValueError("Expected exact canonical BindingsConfig")
    return value


def _config_from(value: object) -> BindingsConfig:
    lines = route_approval._fields(value, {"lines"})["lines"]
    if type(lines) is not list:
        raise ValueError("Invalid binding lines transport")
    config = BindingsConfig(tuple(lines))
    if tuple(lines) != config.lines:
        raise ValueError("Noncanonical binding lines transport")
    return config


def build_text(config: BindingsConfig) -> str:
    checked = _config(config)
    record = base64.b64encode(
        route_approval._json({"version": 1, "binds": list(checked.lines)}).encode("ascii")
    ).decode("ascii")
    snippets = []
    for line in checked.lines:
        key, _, value = line.partition(" = ")
        snippets.append(keyword_to_lua(key, value).rstrip("\n") + "\n")
    text = persistence.MARKER + RECORD + record + "\n" + "".join(snippets)
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Generated bindings exceed 1 MiB")
    return text


def _load(text: str, limit: int = MAX_TRANSPORT_BYTES) -> object:
    if type(text) is not str or len(text.encode("utf-8")) > limit:
        raise ValueError("Bindings JSON exceeds limit")
    depth = 0
    tokens = 0
    quoted = escaped = False
    for char in text:
        if not quoted and char in '{}[],:"':
            tokens += 1
            if tokens > MAX_JSON_TOKENS:
                raise ValueError("Bindings JSON exceeds token limit")
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
                raise ValueError("Bindings JSON exceeds nesting limit")
        elif char in "]}":
            depth -= 1
    return json.loads(text, object_pairs_hook=route_approval._unique)


def read_text(text: str) -> BindingsConfig:
    if type(text) is not str or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Bindings text exceeds 1 MiB")
    if not text.startswith(persistence.MARKER + RECORD):
        raise ValueError("Foreign or unknown bindings format")
    try:
        token = text.split("\n", 2)[1][len(RECORD) :]
        data = route_approval._fields(
            _load(base64.b64decode(token, validate=True).decode("ascii"), MAX_INPUT_BYTES),
            {"version", "binds"},
        )
        if type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("Unknown bindings version")
        if type(data["binds"]) is not list:
            raise ValueError("Expected bindings list")
        config = BindingsConfig(tuple(data["binds"]))
        if build_text(config) != text:
            raise ValueError("Bindings were edited outside Attune")
        return config
    except (binascii.Error, UnicodeError, IndexError, TypeError) as exc:
        raise ValueError("Invalid bindings record") from exc


@dataclass(frozen=True, slots=True)
class BindingsBaseline:
    config_root: str
    state_root: str
    lexical_path: str
    resolved_path: str
    status: str
    text: str
    config: BindingsConfig
    proof: route_approval.PathProof
    protected: tuple[route_approval.PathProof, ...]

    def __post_init__(self):
        if any(
            type(value) is not str
            for value in (
                self.config_root,
                self.state_root,
                self.lexical_path,
                self.resolved_path,
                self.status,
            )
        ):
            raise ValueError("Expected string bindings context")
        config = route_approval._path(self.config_root)
        route_approval._path(self.state_root)
        lexical = route_approval._path(self.lexical_path)
        resolved = route_approval._path(self.resolved_path)
        if lexical != config / "hypr" / BASENAME or resolved.name != BASENAME:
            raise ValueError("Bindings require the fixed lexical and resolved basename")
        _config(self.config)
        if type(self.proof) is not route_approval.PathProof:
            raise ValueError("Expected exact path proof")
        checked = route_approval._proof_from(_load(route_approval._json(asdict(self.proof))))
        if checked != self.proof or (checked.lexical_path, checked.resolved_path) != (
            self.lexical_path,
            self.resolved_path,
        ):
            raise ValueError("Invalid bindings path proof")
        owned_output.validate_protected(
            self.protected, owned_output._protected_paths("bindings", config), self.proof
        )
        if self.status not in {"absent", "empty", "owned"} or type(self.text) is not str:
            raise ValueError("Invalid bindings baseline")
        if self.status == "owned":
            if read_text(self.text) != self.config:
                raise ValueError("Baseline configuration differs from text")
        elif self.text != "" or self.config != BindingsConfig():
            raise ValueError("Absent/empty baseline must have no text or bindings")
        leaf = [fact for fact in checked.facts if fact.path == self.resolved_path]
        if not leaf or (bool(leaf[-1].identity) != (self.status != "absent")):
            raise ValueError("Baseline existence differs from proof")
        if self.status != "absent":
            identity = leaf[-1].identity
            if (
                len(identity) != 9
                or not stat.S_ISREG(identity[2])
                or identity[3] != os.getuid()
                or identity[5] != 1
                or identity[2] & 0o7133
                or identity[2] & 0o600 != 0o600
                or identity[6] != len(self.text.encode("utf-8"))
            ):
                raise ValueError("Baseline proof must describe exact safe file bytes")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        text = route_approval._json(asdict(self))
        if len(text) > MAX_TRANSPORT_BYTES:
            raise ValueError("Baseline transport exceeds limit")
        return text

    @classmethod
    def from_json(cls, text: str) -> "BindingsBaseline":
        data = route_approval._fields(_load(text), set(cls.__dataclass_fields__))
        return cls(
            **{
                **data,
                "config": _config_from(data["config"]),
                "proof": route_approval._proof_from(data["proof"]),
                "protected": owned_output._protected_from(data["protected"]),
            }
        )


def _review_fields(baseline: BindingsBaseline, proposed: BindingsConfig) -> tuple:
    text = build_text(proposed)
    changes = tuple(
        difflib.unified_diff(
            baseline.text.splitlines(keepends=True),
            text.splitlines(keepends=True),
            fromfile=baseline.lexical_path + " (" + baseline.status + ")",
            tofile=baseline.resolved_path + " (proposed)",
            n=3,
        )
    )
    diff = "".join(changes)
    if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise ValueError("Bindings diff exceeds limit")
    added = sum(line.startswith("+") and not line.startswith("+++") for line in changes)
    removed = sum(line.startswith("-") and not line.startswith("---") for line in changes)
    fingerprint = hashlib.sha256(
        route_approval._json(
            {
                "baseline": asdict(baseline),
                "source_sha256": baseline.sha256,
                "proposed_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "proposed": asdict(proposed),
                "diff": diff,
                "added": added,
                "removed": removed,
            }
        ).encode("ascii")
    ).hexdigest()
    return text, diff, added, removed, fingerprint


@dataclass(frozen=True, slots=True)
class BindingsReview:
    baseline: BindingsBaseline
    proposed: BindingsConfig
    proposed_text: str
    diff: str
    added_lines: int
    removed_lines: int
    review_hash: str

    def __post_init__(self):
        if type(self.baseline) is not BindingsBaseline:
            raise ValueError("Expected exact bindings baseline")
        if BindingsBaseline.from_json(self.baseline.to_json()) != self.baseline:
            raise ValueError("Invalid baseline")
        if type(self.added_lines) is not int or type(self.removed_lines) is not int:
            raise ValueError("Expected integer diff counts")
        if any(
            type(value) is not str for value in (self.proposed_text, self.diff, self.review_hash)
        ):
            raise ValueError("Expected exact review strings")
        if _review_fields(self.baseline, _config(self.proposed)) != (
            self.proposed_text,
            self.diff,
            self.added_lines,
            self.removed_lines,
            self.review_hash,
        ):
            raise ValueError("Bindings review does not match exact request")

    def to_json(self) -> str:
        text = route_approval._json(asdict(self))
        if len(text) > MAX_TRANSPORT_BYTES:
            raise ValueError("Review transport exceeds limit")
        return text

    @classmethod
    def from_json(cls, text: str) -> "BindingsReview":
        data = route_approval._fields(_load(text), set(cls.__dataclass_fields__))
        return cls(
            **{
                **data,
                "baseline": BindingsBaseline.from_json(route_approval._json(data["baseline"])),
                "proposed": _config_from(data["proposed"]),
            }
        )


@dataclass(frozen=True, slots=True)
class BindingsSaveResult:
    outcome: str
    baseline: BindingsBaseline | None
    backup_path: str | None
    may_have_written: bool
    error: str | None

    def __post_init__(self):
        if self.outcome not in {"saved", "no-op", "failed"}:
            raise ValueError("Invalid bindings save outcome")
        if type(self.may_have_written) is not bool:
            raise ValueError("Invalid uncertainty flag")
        if self.backup_path is not None:
            route_approval._path(self.backup_path)
        if self.outcome == "failed":
            if self.baseline is not None or type(self.error) is not str or not self.error:
                raise ValueError("Failed save must retain no adoptable baseline")
        elif type(self.baseline) is not BindingsBaseline or self.error is not None:
            raise ValueError("Success requires fresh baseline and no error")
        elif self.may_have_written != (self.outcome == "saved"):
            raise ValueError("Success publication flag differs from outcome")
        elif self.outcome == "no-op" and self.backup_path is not None:
            raise ValueError("No-op must not create backups")


def observe(config_root: Path, state_root: Path) -> BindingsBaseline:
    baseline = owned_output.observe("bindings", config_root, state_root, read_text=read_text)
    return BindingsBaseline(
        **{
            name: getattr(baseline, name)
            for name in owned_output.OwnedBaseline.__dataclass_fields__
        },
        config=read_text(baseline.text) if baseline.status == "owned" else BindingsConfig(),
    )


def same_source(original: BindingsBaseline, current: BindingsBaseline) -> bool:
    """Match own source exactly, allowing freshly observed safe sibling leaf changes only."""
    return (
        type(original) is BindingsBaseline
        and type(current) is BindingsBaseline
        and all(
            getattr(original, name) == getattr(current, name)
            for name in BindingsBaseline.__dataclass_fields__
            if name != "protected"
        )
        and owned_output.same_protection(original.protected, current.protected)
    )


def prepare_review(baseline: BindingsBaseline, proposed: BindingsConfig) -> BindingsReview:
    if type(baseline) is not BindingsBaseline:
        raise ValueError("Expected exact bindings baseline")
    checked = BindingsBaseline.from_json(baseline.to_json())
    current = observe(Path(checked.config_root), Path(checked.state_root))
    if checked != baseline or not same_source(checked, current):
        raise ValueError("Bindings changed since observation; review again")
    return BindingsReview(current, _config(proposed), *_review_fields(current, proposed))


def persist_reviewed(
    review: BindingsReview,
    proposed: BindingsConfig,
    *,
    cancel_event: threading.Event | None = None,
) -> BindingsSaveResult:
    try:
        if threading.current_thread().daemon:
            raise ValueError("Bindings Save requires a direct non-daemon worker")
        if type(review) is not BindingsReview:
            raise ValueError("Expected exact bindings review")
        checked = BindingsReview.from_json(review.to_json())
        if checked != review or _config(proposed) != checked.proposed:
            raise ValueError("Draft changed since review")
        baseline = checked.baseline
        config_root, state_root = Path(baseline.config_root), Path(baseline.state_root)
    except (OSError, ValueError, RuntimeError) as exc:
        return BindingsSaveResult("failed", None, None, False, str(exc) or type(exc).__name__)

    def current() -> owned_output.OwnedBaseline:
        observed = observe(config_root, state_root)
        return owned_output.OwnedBaseline(
            **{
                name: getattr(observed, name)
                for name in owned_output.OwnedBaseline.__dataclass_fields__
            }
        )

    result = owned_output.persist_reviewed(
        "bindings",
        owned_output.OwnedBaseline(
            **{
                name: getattr(baseline, name)
                for name in owned_output.OwnedBaseline.__dataclass_fields__
            }
        ),
        checked.proposed_text,
        read_text=read_text,
        observe_current=current,
        cancel_event=cancel_event,
    )
    fresh = result.baseline
    try:
        return BindingsSaveResult(
            result.outcome,
            BindingsBaseline(
                **{
                    name: getattr(fresh, name)
                    for name in owned_output.OwnedBaseline.__dataclass_fields__
                },
                config=read_text(fresh.text),
            )
            if fresh
            else None,
            result.backup_path,
            result.may_have_written,
            result.error,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        return BindingsSaveResult(
            "failed",
            None,
            result.backup_path,
            result.may_have_written,
            str(exc) or type(exc).__name__,
        )


def run_observe(
    config_root: Path,
    state_root: Path,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 15,
) -> BindingsBaseline:
    roots = tuple(str(route_approval._path(p)) for p in (config_root, state_root))
    result = _run_worker("observe", roots, None, cancel_event, timeout)
    baseline = BindingsBaseline.from_json(result)
    if (baseline.config_root, baseline.state_root) != roots:
        raise ValueError("Bindings worker returned different roots")
    return baseline


def run_prepare_review(
    baseline: BindingsBaseline,
    proposed: BindingsConfig,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> BindingsReview:
    if type(baseline) is not BindingsBaseline:
        raise ValueError("Expected exact baseline")
    checked = BindingsBaseline.from_json(baseline.to_json())
    if checked != baseline:
        raise ValueError("Invalid baseline")
    _config(proposed)
    request = route_approval._json({"baseline": asdict(checked), "proposed": asdict(proposed)})
    roots = (baseline.config_root, baseline.state_root)
    review = BindingsReview.from_json(_run_worker("review", roots, request, cancel_event, timeout))
    if not same_source(baseline, review.baseline) or review.proposed != proposed:
        raise ValueError("Bindings worker returned a different review request")
    return review


def _run_worker(
    mode: str,
    roots: tuple[str, ...],
    request: str | None,
    cancel_event: threading.Event | None,
    timeout: float,
) -> str:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Bindings worker timeout must be finite and positive")
    result = health.run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.bindings",
            mode,
            "--config-root",
            roots[0],
            "--state-root",
            roots[1],
        ],
        timeout=timeout,
        max_bytes=MAX_TRANSPORT_BYTES,
        process_group=True,
        cwd=Path(__file__).absolute().parents[2],
        cancel_event=cancel_event,
        input_text=request,
    )
    if result.returncode:
        raise ValueError(f"Bindings worker refused: {result.stderr[:4096].strip()}")
    return result.stdout


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only bindings worker")
    parser.add_argument("mode", choices=("observe", "review"))
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == "observe":
            print(observe(args.config_root, args.state_root).to_json())
        else:
            request = route_approval._fields(
                _load(sys.stdin.read(MAX_TRANSPORT_BYTES + 1)), {"baseline", "proposed"}
            )
            baseline = BindingsBaseline.from_json(route_approval._json(request["baseline"]))
            if (baseline.config_root, baseline.state_root) != (
                str(args.config_root),
                str(args.state_root),
            ):
                raise ValueError("Bindings review roots differ from request")
            print(prepare_review(baseline, _config_from(request["proposed"])).to_json())
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
