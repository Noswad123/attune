"""Reviewed keyboard, mouse and touchpad overrides. No runtime IPC or Lua evaluation."""

import argparse
import base64
import binascii
import difflib
import hashlib
import json
import math
import re
import sys
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType

from hyprland_config import Assignment, Document, keyword_to_lua, serialize_lua

from hyprmod.core import health, owned_output, persistence, route_approval

Scalar = str | bool | int | float
BASENAME = "attune-input.lua"
RECORD = "-- Attune input data v1: "
MAX_INPUT_BYTES = owned_output.MAX_INPUT_BYTES
MAX_DIFF_BYTES = 2 * MAX_INPUT_BYTES + 65536
MAX_TRANSPORT_BYTES = 32 * MAX_INPUT_BYTES


@dataclass(frozen=True, slots=True)
class OptionSpec:
    value_type: type[str] | type[bool] | type[int] | type[float]
    default: Scalar
    minimum: int | float | None = None
    maximum: int | float | None = None
    step: float | None = None
    choices: tuple[str, ...] = ()


OPTION_SPECS = MappingProxyType(
    {
        "input:kb_layout": OptionSpec(str, "us"),
        "input:kb_variant": OptionSpec(str, ""),
        "input:kb_options": OptionSpec(str, ""),
        "input:accel_profile": OptionSpec(str, "", choices=("", "flat", "adaptive")),
        "input:numlock_by_default": OptionSpec(bool, False),
        "input:left_handed": OptionSpec(bool, False),
        "input:natural_scroll": OptionSpec(bool, False),
        "input:touchpad:natural_scroll": OptionSpec(bool, False),
        "input:touchpad:tap-to-click": OptionSpec(bool, True),
        "input:touchpad:disable_while_typing": OptionSpec(bool, True),
        "input:repeat_rate": OptionSpec(int, 25, 0, 200),
        "input:repeat_delay": OptionSpec(int, 600, 0, 2000),
        "input:sensitivity": OptionSpec(float, 0.0, -1, 1),
        "input:scroll_factor": OptionSpec(float, 1.0, 0.1, 2.0, 0.1),
        "input:touchpad:scroll_factor": OptionSpec(float, 1.0, 0.1, 2.0, 0.1),
    }
)
INPUT_KEYS = frozenset(OPTION_SPECS)
DEFAULTS = MappingProxyType({key: spec.default for key, spec in OPTION_SPECS.items()})
_XKB_NAME = r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}"
_OPTION_TAG = r"[A-Za-z0-9_][A-Za-z0-9_:+.-]{0,127}"


def normalize_value(key: str, value: Scalar) -> Scalar:
    if type(key) is not str or key not in INPUT_KEYS:
        raise ValueError("Unknown input option")
    spec = OPTION_SPECS[key]
    if spec.value_type is float:
        if type(value) not in (int, float):
            raise ValueError("Expected finite input number, not boolean")
        try:
            value = float(value)
        except OverflowError as exc:
            raise ValueError("Input number exceeds range") from exc
        if not math.isfinite(value):
            raise ValueError("Expected finite input number")
        if value == 0:
            value = 0.0
    elif type(value) is not spec.value_type:
        raise ValueError("Incorrect input option type")
    if type(value) is int or type(value) is float:
        if spec.minimum is not None and value < spec.minimum:
            raise ValueError("Input number below minimum")
        if spec.maximum is not None and value > spec.maximum:
            raise ValueError("Input number above maximum")
        if spec.step is not None and not math.isclose(
            value / spec.step, round(value / spec.step), abs_tol=1e-9, rel_tol=0
        ):
            raise ValueError("Input number does not match step")
    if type(value) is str:
        if len(value) > 1024:
            raise ValueError("Input string exceeds limit")
        if spec.choices and value not in spec.choices:
            raise ValueError("Unknown input choice")
        if key in {"input:kb_layout", "input:kb_variant", "input:kb_options"}:
            pattern = _OPTION_TAG if key == "input:kb_options" else _XKB_NAME
            tokens = value.split(",")
            if len(tokens) > 32 or any(
                token and re.fullmatch(pattern, token, flags=re.ASCII) is None for token in tokens
            ):
                raise ValueError("Invalid XKB tokens")
            if key != "input:kb_variant" and value and any(not token for token in tokens):
                raise ValueError("Empty XKB token")
            if key == "input:kb_layout" and not value:
                raise ValueError("Managed keyboard layout must not be empty")
    return value


@dataclass(frozen=True, slots=True)
class InputConfig:
    values: tuple[tuple[str, Scalar], ...] = ()

    def __post_init__(self):
        if type(self.values) is not tuple or len(self.values) > len(INPUT_KEYS):
            raise ValueError("Expected immutable input values")
        values: dict[str, Scalar] = {}
        for pair in self.values:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("Expected immutable key/value pairs")
            key, value = pair
            normalized = normalize_value(key, value)
            if key in values:
                raise ValueError("Duplicate input option")
            values[key] = normalized
        if "input:kb_variant" in values:
            layout = values.get("input:kb_layout")
            variant = values["input:kb_variant"]
            if type(layout) is not str or type(variant) is not str:
                raise ValueError("Managed variant requires managed layout")
            if variant and len(variant.split(",")) != len(layout.split(",")):
                raise ValueError("Variant slots must align with layout slots")
        object.__setattr__(self, "values", tuple(sorted(values.items())))

    @classmethod
    def from_mapping(cls, values: Mapping[str, Scalar]) -> "InputConfig":
        return cls(tuple(values.items()))


def _config(value: InputConfig) -> InputConfig:
    if type(value) is not InputConfig or route_approval._json(
        asdict(InputConfig(value.values))
    ) != route_approval._json(asdict(value)):
        raise ValueError("Expected exact canonical InputConfig")
    return value


def _load(text: str, limit: int = MAX_TRANSPORT_BYTES) -> object:
    if type(text) is not str or len(text.encode("utf-8")) > limit:
        raise ValueError("Input JSON exceeds limit")
    depth = tokens = 0
    quoted = escaped = False
    for char in text:
        if not quoted and char in '{}[],:"':
            tokens += 1
            if tokens > 262144:
                raise ValueError("Input JSON exceeds token limit")
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
                raise ValueError("Input JSON exceeds nesting limit")
        elif char in "]}":
            depth -= 1
    return json.loads(text, object_pairs_hook=route_approval._unique)


def _config_from(value: object) -> InputConfig:
    values = route_approval._fields(value, {"values"})["values"]
    if type(values) is not list or any(type(pair) is not list or len(pair) != 2 for pair in values):
        raise ValueError("Invalid input values transport")
    config = InputConfig(tuple(tuple(pair) for pair in values))
    if route_approval._json(asdict(config)["values"]) != route_approval._json(values):
        raise ValueError("Noncanonical input values transport")
    return config


def build_text(config: InputConfig) -> str:
    checked = _config(config)
    record = base64.b64encode(
        route_approval._json({"version": 1, "values": dict(checked.values)}).encode("ascii")
    ).decode("ascii")
    document = Document()
    for key, value in checked.values:
        raw = str(value).lower() if type(value) is bool else str(value)
        snippet = keyword_to_lua(key, raw)
        leaf = key.rsplit(":", 1)[-1]
        field = re.escape(leaf) if "-" not in leaf else re.escape('["' + leaf + '"]')
        literal = re.search(r"^\s*" + field + r" = (.*),$", snippet, re.MULTILINE)
        emitted = json.loads(literal[1]) if literal is not None else None
        if type(emitted) is not type(value) or emitted != value:
            raise ValueError("Library cannot prove typed input emission")
        document.lines.append(Assignment(raw="", key=key, full_key=key, value=raw))
    text = persistence.MARKER + RECORD + record + "\n" + serialize_lua(document)
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Generated input exceeds 1 MiB")
    return text


def read_text(text: str) -> InputConfig:
    if type(text) is not str or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Input text exceeds 1 MiB")
    if not text.startswith(persistence.MARKER + RECORD):
        raise ValueError("Foreign or unknown input format")
    try:
        token = text.split("\n", 2)[1][len(RECORD) :]
        data = route_approval._fields(
            _load(base64.b64decode(token, validate=True).decode("ascii"), MAX_INPUT_BYTES),
            {"version", "values"},
        )
        if type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("Unknown input version")
        if type(data["values"]) is not dict:
            raise ValueError("Expected input values mapping")
        config = InputConfig.from_mapping(data["values"])
        if build_text(config) != text:
            raise ValueError("Input was edited outside Attune")
        return config
    except (binascii.Error, UnicodeError, IndexError, TypeError) as exc:
        raise ValueError("Invalid input record") from exc


@dataclass(frozen=True, slots=True)
class InputBaseline:
    config_root: str
    state_root: str
    lexical_path: str
    resolved_path: str
    status: str
    text: str
    config: InputConfig
    proof: route_approval.PathProof
    protected: tuple[route_approval.PathProof, ...]

    def __post_init__(self):
        _config(self.config)
        if type(self.proof) is not route_approval.PathProof:
            raise ValueError("Expected exact input path proof")
        if (
            route_approval._proof_from(_load(route_approval._json(asdict(self.proof))))
            != self.proof
        ):
            raise ValueError("Invalid input path proof")
        owned_output.validate_baseline("input", _owned(self), read_text=read_text)
        expected = read_text(self.text) if self.status == "owned" else InputConfig()
        if expected != self.config:
            raise ValueError("Input baseline configuration differs from text")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        text = route_approval._json(asdict(self))
        if len(text) > MAX_TRANSPORT_BYTES:
            raise ValueError("Input baseline transport exceeds limit")
        return text

    @classmethod
    def from_json(cls, text: str) -> "InputBaseline":
        data = route_approval._fields(_load(text), set(cls.__dataclass_fields__))
        return cls(
            **{
                **data,
                "config": _config_from(data["config"]),
                "proof": route_approval._proof_from(data["proof"]),
                "protected": owned_output._protected_from(data["protected"]),
            }
        )


def _owned(baseline: InputBaseline) -> owned_output.OwnedBaseline:
    return owned_output.OwnedBaseline(
        **{
            name: getattr(baseline, name)
            for name in owned_output.OwnedBaseline.__dataclass_fields__
        }
    )


def _baseline(baseline: owned_output.OwnedBaseline) -> InputBaseline:
    return InputBaseline(
        **{
            name: getattr(baseline, name)
            for name in owned_output.OwnedBaseline.__dataclass_fields__
        },
        config=read_text(baseline.text) if baseline.status == "owned" else InputConfig(),
    )


def _review_fields(baseline: InputBaseline, proposed: InputConfig) -> tuple:
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
        raise ValueError("Input diff exceeds limit")
    added = sum(line.startswith("+") and not line.startswith("+++") for line in changes)
    removed = sum(line.startswith("-") and not line.startswith("---") for line in changes)
    digest = hashlib.sha256(
        route_approval._json(
            {
                "baseline": asdict(baseline),
                "source_sha256": baseline.sha256,
                "proposed": asdict(proposed),
                "text": text,
                "diff": diff,
                "added": added,
                "removed": removed,
            }
        ).encode("ascii")
    ).hexdigest()
    return text, diff, added, removed, digest


@dataclass(frozen=True, slots=True)
class InputReview:
    baseline: InputBaseline
    proposed: InputConfig
    proposed_text: str
    diff: str
    added_lines: int
    removed_lines: int
    review_hash: str

    def __post_init__(self):
        if type(self.baseline) is not InputBaseline:
            raise ValueError("Expected exact input baseline")
        if InputBaseline.from_json(self.baseline.to_json()) != self.baseline:
            raise ValueError("Invalid input baseline")
        if type(self.added_lines) is not int or type(self.removed_lines) is not int:
            raise ValueError("Expected integer diff counts")
        if any(type(v) is not str for v in (self.proposed_text, self.diff, self.review_hash)):
            raise ValueError("Expected input review strings")
        if _review_fields(self.baseline, _config(self.proposed)) != (
            self.proposed_text,
            self.diff,
            self.added_lines,
            self.removed_lines,
            self.review_hash,
        ):
            raise ValueError("Input review does not match exact request")

    def to_json(self) -> str:
        text = route_approval._json(asdict(self))
        if len(text) > MAX_TRANSPORT_BYTES:
            raise ValueError("Input review transport exceeds limit")
        return text

    @classmethod
    def from_json(cls, text: str) -> "InputReview":
        data = route_approval._fields(_load(text), set(cls.__dataclass_fields__))
        return cls(
            **{
                **data,
                "baseline": InputBaseline.from_json(route_approval._json(data["baseline"])),
                "proposed": _config_from(data["proposed"]),
            }
        )


@dataclass(frozen=True, slots=True)
class InputSaveResult:
    outcome: str
    baseline: InputBaseline | None
    backup_path: str | None
    may_have_written: bool
    error: str | None

    def __post_init__(self):
        if type(self.outcome) is not str or self.outcome not in {"saved", "no-op", "failed"}:
            raise ValueError("Invalid input save outcome")
        if type(self.may_have_written) is not bool:
            raise ValueError("Invalid input uncertainty flag")
        if self.backup_path is not None:
            if type(self.backup_path) is not str:
                raise ValueError("Expected backup path string")
            route_approval._path(self.backup_path)
        if self.outcome == "failed":
            if self.baseline is not None or type(self.error) is not str or not self.error:
                raise ValueError("Failed save must retain no adoptable baseline")
        elif type(self.baseline) is not InputBaseline or self.error is not None:
            raise ValueError("Success requires fresh input baseline and no error")
        elif InputBaseline.from_json(self.baseline.to_json()) != self.baseline:
            raise ValueError("Invalid saved input baseline")
        elif self.may_have_written != (self.outcome == "saved"):
            raise ValueError("Input publication flag differs from outcome")
        elif self.outcome == "no-op" and self.backup_path is not None:
            raise ValueError("No-op must not create backups")

    def to_json(self) -> str:
        text = route_approval._json(asdict(self))
        if len(text) > MAX_TRANSPORT_BYTES:
            raise ValueError("Input save result transport exceeds limit")
        return text

    @classmethod
    def from_json(cls, text: str) -> "InputSaveResult":
        data = route_approval._fields(_load(text), set(cls.__dataclass_fields__))
        return cls(
            **{
                **data,
                "baseline": InputBaseline.from_json(route_approval._json(data["baseline"]))
                if data["baseline"] is not None
                else None,
            }
        )


def observe(config_root: Path, state_root: Path) -> InputBaseline:
    return _baseline(owned_output.observe("input", config_root, state_root, read_text=read_text))


def same_source(original: InputBaseline, current: InputBaseline) -> bool:
    """Match own source exactly, allowing freshly observed safe sibling leaf changes only."""
    return (
        type(original) is InputBaseline
        and type(current) is InputBaseline
        and all(
            getattr(original, name) == getattr(current, name)
            for name in InputBaseline.__dataclass_fields__
            if name != "protected"
        )
        and owned_output.same_protection(original.protected, current.protected)
    )


def prepare_review(baseline: InputBaseline, proposed: InputConfig) -> InputReview:
    if type(baseline) is not InputBaseline:
        raise ValueError("Expected exact input baseline")
    checked = InputBaseline.from_json(baseline.to_json())
    current = observe(Path(checked.config_root), Path(checked.state_root))
    if checked != baseline or not same_source(checked, current):
        raise ValueError("Input changed since observation; review again")
    return InputReview(current, _config(proposed), *_review_fields(current, proposed))


def persist_reviewed(
    review: InputReview, proposed: InputConfig, *, cancel_event: threading.Event | None = None
) -> InputSaveResult:
    try:
        if threading.current_thread().daemon:
            raise ValueError("Input Save requires a direct non-daemon worker")
        if type(review) is not InputReview:
            raise ValueError("Expected exact input review")
        checked = InputReview.from_json(review.to_json())
        if checked != review or _config(proposed) != checked.proposed:
            raise ValueError("Input draft changed since review")
    except (OSError, ValueError, RuntimeError) as exc:
        return InputSaveResult("failed", None, None, False, str(exc) or type(exc).__name__)
    baseline = checked.baseline
    result = owned_output.persist_reviewed(
        "input",
        _owned(baseline),
        checked.proposed_text,
        read_text=read_text,
        observe_current=lambda: _owned(
            observe(Path(baseline.config_root), Path(baseline.state_root))
        ),
        cancel_event=cancel_event,
    )
    try:
        return InputSaveResult(
            result.outcome,
            _baseline(result.baseline) if result.baseline else None,
            result.backup_path,
            result.may_have_written,
            result.error,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        return InputSaveResult(
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
) -> InputBaseline:
    roots = tuple(str(route_approval._path(p)) for p in (config_root, state_root))
    baseline = InputBaseline.from_json(_run_worker("observe", roots, None, cancel_event, timeout))
    if (baseline.config_root, baseline.state_root) != roots:
        raise ValueError("Input worker returned different roots")
    return baseline


def run_prepare_review(
    baseline: InputBaseline,
    proposed: InputConfig,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> InputReview:
    if type(baseline) is not InputBaseline:
        raise ValueError("Expected exact input baseline")
    checked = InputBaseline.from_json(baseline.to_json())
    if checked != baseline:
        raise ValueError("Invalid input baseline")
    _config(proposed)
    request = route_approval._json({"baseline": asdict(checked), "proposed": asdict(proposed)})
    review = InputReview.from_json(
        _run_worker(
            "review", (baseline.config_root, baseline.state_root), request, cancel_event, timeout
        )
    )
    if not same_source(baseline, review.baseline) or review.proposed != proposed:
        raise ValueError("Input worker returned a different review request")
    return review


def _run_worker(
    mode: str,
    roots: tuple[str, ...],
    request: str | None,
    cancel_event: threading.Event | None,
    timeout: float,
) -> str:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Input worker timeout must be finite and positive")
    result = health.run_bounded(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.input",
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
        raise ValueError(f"Input worker refused: {result.stderr[:4096].strip()}")
    return result.stdout


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only input worker")
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
            baseline = InputBaseline.from_json(route_approval._json(request["baseline"]))
            if (baseline.config_root, baseline.state_root) != (
                str(args.config_root),
                str(args.state_root),
            ):
                raise ValueError("Input review roots differ from request")
            print(prepare_review(baseline, _config_from(request["proposed"])).to_json())
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
