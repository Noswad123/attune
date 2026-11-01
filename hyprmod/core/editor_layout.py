"""Read-only canonical editor sessions. Run filesystem calls off GTK; never write authority."""

import argparse
import math
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass, is_dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path

from hyprmod.core import (
    health,
    layout_guard,
    persistence,
    route_approval,
    scoped_config,
    scoped_review,
    transaction_store,
)
from hyprmod.core.route_approval import InstallationEvidence
from hyprmod.core.scoped_config import ScopedConfig
from hyprmod.core.scoped_review import GroupReviewPlan
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import (
    MAX_RECORD_BYTES,
    canonical_json,
    decode_json,
    fields,
    plan_from_json,
    plan_to_json,
)

MAX_MESSAGE_BYTES = 4096


def _original(value: object, checked: object) -> None:
    # Equality alone hides lists normalized by codecs, str enums and bool integers.
    if type(value) is not type(checked):
        raise ValueError("Expected exact original immutable field types")
    if is_dataclass(checked) and not isinstance(checked, type):
        for field in dataclass_fields(checked):
            _original(getattr(value, field.name), getattr(checked, field.name))
    elif isinstance(checked, tuple):
        if not isinstance(value, tuple) or len(value) != len(checked):
            raise ValueError("Expected exact immutable tuple")
        for left, right in zip(value, checked, strict=True):
            _original(left, right)
    elif value != checked:
        raise ValueError("Original differs from canonical model")


def _model_text(scope: Scope, model: ScopedConfig) -> str:
    if type(scope) is not Scope or type(model) is not ScopedConfig or model.scope is not scope:
        raise ValueError("Expected Scope and matching canonical ScopedConfig")
    # Validate before payload() or rendering can normalize mutable original fields.
    for name in ("values", "beziers", "animations", "monitors"):
        records = getattr(model, name)
        if type(records) is not tuple or len(records) > scoped_review.MAX_INPUT_LINES:
            raise ValueError("Expected bounded immutable canonical records")
        size = 0
        for record in records:
            parts = record if name == "values" else (record,)
            if type(parts) is not tuple or (name == "values" and len(parts) != 2):
                raise ValueError("Expected immutable scalar pairs")
            for part in parts:
                if type(part) is not str:
                    raise ValueError("Expected exact canonical strings")
                size += len(part.encode("utf-8"))
            if size > scoped_config.MAX_INPUT_BYTES:
                raise ValueError("Canonical model exceeds input limit")
    checked = ScopedConfig(scope, model.payload())
    _original(model, checked)
    return scoped_config.build_text(checked)


def _envelope(text: str, kind: str, names: set[str]) -> dict:
    data = fields(decode_json(text), {"schema", "kind", *names}).copy()
    decode_json(canonical_json(data))
    schema = data.pop("schema")
    if type(schema) is not int or schema != 1 or data.pop("kind") != kind:
        raise ValueError("Unknown editor transport format")
    return data


@dataclass(frozen=True, slots=True)
class CanonicalPairLayout:
    evidence: InstallationEvidence
    appearance: ScopedConfig
    displays: ScopedConfig

    def __post_init__(self) -> None:
        if type(self.evidence) is not InstallationEvidence:
            raise ValueError("Expected exact installation evidence")
        checked = InstallationEvidence.from_json(self.evidence.to_json())
        _original(self.evidence, checked)
        for scope, route in zip(Scope, checked.routes, strict=True):
            model = getattr(self, scope.value)
            text = _model_text(scope, model)
            if (
                scoped_config.byte_hash(text) != route.file.source_sha256
                or model.content_id != route.content_id
                or route.counts
                != tuple(
                    len(getattr(model, n)) for n in ("values", "beziers", "animations", "monitors")
                )
            ):
                raise ValueError(f"Canonical {scope.value} model differs from route evidence")

    def to_json(self) -> str:
        self.__post_init__()
        text = canonical_json(
            {
                "schema": 1,
                "kind": "canonical-pair-layout",
                "evidence": decode_json(self.evidence.to_json()),
                **{s.value: _model_text(s, getattr(self, s.value)) for s in Scope},
            }
        )
        decode_json(text)
        return text

    @classmethod
    def from_json(cls, text: str) -> "CanonicalPairLayout":
        data = _envelope(text, "canonical-pair-layout", set(cls.__dataclass_fields__))
        data["evidence"] = InstallationEvidence.from_json(canonical_json(data["evidence"]))
        for scope in Scope:
            if type(data[scope.value]) is not str:
                raise ValueError("Expected canonical scope text")
            data[scope.value] = scoped_config.read_document(data[scope.value], expected_scope=scope)
        return cls(**data)


@dataclass(frozen=True, slots=True)
class EditorEntry:
    config_root: str
    state_root: str
    mode: str
    pair: CanonicalPairLayout | None
    message: str | None

    def __post_init__(self) -> None:
        for root in (self.config_root, self.state_root):
            if type(root) is not str:
                raise ValueError("Expected explicit root strings")
            layout_guard.validate_context(Path(root))
            if str(Path(root)) != root:
                raise ValueError("Expected exact normalized root strings")
        if type(self.mode) is not str or self.mode not in ("legacy-clear", "pair-ready", "blocked"):
            raise ValueError("Unknown editor entry mode")
        if self.mode == "pair-ready":
            if type(self.pair) is not CanonicalPairLayout:
                raise ValueError("Pair-ready requires a canonical pair")
            self.pair.__post_init__()
            if (self.pair.evidence.config_root, self.pair.evidence.state_root) != (
                self.config_root,
                self.state_root,
            ):
                raise ValueError("Pair differs from entry roots")
        elif self.pair is not None:
            raise ValueError("Only pair-ready may contain a pair")
        if self.mode == "blocked":
            if (
                type(self.message) is not str
                or not 1 <= len(self.message.encode("utf-8")) <= MAX_MESSAGE_BYTES
            ):
                raise ValueError("Blocked entry requires a bounded reason")
        elif self.message is not None:
            raise ValueError("Only blocked entry may contain a reason")

    def to_json(self) -> str:
        self.__post_init__()
        text = canonical_json(
            {
                "schema": 1,
                "kind": "editor-entry",
                "config_root": self.config_root,
                "state_root": self.state_root,
                "mode": self.mode,
                "message": self.message,
                "pair": decode_json(self.pair.to_json()) if self.pair is not None else None,
            }
        )
        decode_json(text)
        return text

    @classmethod
    def from_json(cls, text: str) -> "EditorEntry":
        data = _envelope(text, "editor-entry", set(cls.__dataclass_fields__))
        if data["pair"] is not None:
            data["pair"] = CanonicalPairLayout.from_json(canonical_json(data["pair"]))
        return cls(**data)


def inspect_entry(config_root: Path, state_root: Path) -> EditorEntry:
    layout_guard.validate_context(config_root)
    layout_guard.validate_context(state_root)
    roots = (str(config_root), str(state_root))
    route_labels = "appearance/displays routes"
    try:
        if layout_guard.block_reason(config_root, state_root) is None:
            return EditorEntry(*roots, "legacy-clear", None, None)
        binding = transaction_store.inspect_store(state_root)
        ids = transaction_store.refuse_pending_readonly(state_root)
        registry_path = config_root / "attune/installation.json"
        collection = route_approval._collect_filesystem(
            registry_path, config_root=config_root, state_root=state_root
        )
        route_labels = "; ".join(
            f"{scope.value}: {file.path.lexical_path}" for scope, file, _ in collection.routes
        )
        evidence = route_approval.inspect_installation(
            registry_path, config_root=config_root, state_root=state_root
        )
        models = {}
        for route in evidence.routes:
            path = route.file.path.resolved_path
            try:
                raw = persistence.read_stable(Path(path), limit=scoped_config.MAX_INPUT_BYTES)
                if scoped_config.byte_hash(raw.decode("utf-8")) != route.file.source_sha256:
                    raise ValueError("Current bytes differ from route evidence")
                models[route.scope.value] = scoped_config.read_document(
                    raw.decode("utf-8"), expected_scope=route.scope
                )
            except (OSError, ValueError, RuntimeError) as exc:
                raise ValueError(f"{route.scope.value} at {path}: {exc}") from exc
        pair = CanonicalPairLayout(evidence, **models)
        if transaction_store.refuse_pending_readonly(state_root) != ids:
            raise ValueError("Transaction IDs changed during entry inspection")
        transaction_store.revalidate_store(binding)
        route_approval.revalidate(evidence)
        return EditorEntry(*roots, "pair-ready", pair, None)
    except (OSError, ValueError, RuntimeError) as exc:
        reason = (
            "Canonical-pair editor blocked. Use explicit transaction recovery for pending work. "
            "Foreign/missing/wrong-scope output or unsafe/missing store requires manual "
            "remediation: restore the registered canonical scopes and safe initialized store. "
            "No automatic repair. "
            f"Registry: {config_root / 'attune/installation.json'}; "
            f"{route_labels}; private store: {state_root / 'attune'}. {exc}"
        )
        message = reason.encode("utf-8", "replace")[:MAX_MESSAGE_BYTES].decode("utf-8", "ignore")
        return EditorEntry(*roots, "blocked", None, message)


def _proposals(
    pair: CanonicalPairLayout, proposals: Mapping[Scope, ScopedConfig]
) -> dict[Scope, str]:
    if type(pair) is not CanonicalPairLayout:
        raise ValueError("Expected exact canonical pair")
    pair.__post_init__()
    if not isinstance(proposals, Mapping):
        raise ValueError("Expected scoped proposal mapping")
    return {scope: _model_text(scope, model) for scope, model in proposals.items()}


def _check_plan(pair: CanonicalPairLayout, goals: dict[Scope, str], plan: GroupReviewPlan) -> None:
    scoped_review.validate_recorded_review(plan)
    if plan.evidence.evidence_hash != pair.evidence.evidence_hash:
        raise ValueError("Worker returned a different original pair")
    for review in plan.scopes:
        previous = _model_text(review.scope, getattr(pair, review.scope.value))
        if review.previous_text != previous or review.proposed_text != goals.get(
            review.scope, previous
        ):
            raise ValueError("Review differs from exact original pair/proposal goals")


def prepare_review(
    pair: CanonicalPairLayout, proposals: Mapping[Scope, ScopedConfig]
) -> GroupReviewPlan:
    goals = _proposals(pair, proposals)
    state_root = Path(pair.evidence.state_root)
    binding = transaction_store.inspect_store(state_root)
    ids = transaction_store.refuse_pending_readonly(state_root)
    route_approval.revalidate(pair.evidence)
    plan = scoped_review.build_review(pair.evidence, proposals)
    _check_plan(pair, goals, plan)
    if transaction_store.refuse_pending_readonly(state_root) != ids:
        raise ValueError("Transaction IDs changed during review preparation")
    transaction_store.revalidate_store(binding)
    route_approval.revalidate(pair.evidence)
    return plan


def _worker(
    arguments: list[str],
    *,
    input_text: str | None,
    cancel_event: threading.Event | None,
    timeout: float,
) -> str:
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Expected finite positive timeout")
    result = health.run_bounded(
        [sys.executable, "-I", "-B", "-m", "hyprmod.core.editor_layout", *arguments],
        input_text=input_text,
        timeout=timeout,
        max_bytes=MAX_RECORD_BYTES,
        process_group=True,
        cancel_event=cancel_event,
        cwd=Path(__file__).absolute().parents[2],
    )
    if result.returncode:
        raise ValueError(f"Read-only editor worker refused: {result.stderr[:4096].strip()}")
    return result.stdout


def run_entry(
    config_root: Path,
    state_root: Path,
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> EditorEntry:
    layout_guard.validate_context(config_root)
    layout_guard.validate_context(state_root)
    entry = EditorEntry.from_json(
        _worker(
            ["entry", "--config-root", str(config_root), "--state-root", str(state_root)],
            input_text=None,
            cancel_event=cancel_event,
            timeout=timeout,
        )
    )
    if (entry.config_root, entry.state_root) != (str(config_root), str(state_root)):
        raise ValueError("Worker returned different editor roots")
    return entry


def run_prepare_review(
    pair: CanonicalPairLayout,
    proposals: Mapping[Scope, ScopedConfig],
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> GroupReviewPlan:
    goals = _proposals(pair, proposals)
    request = canonical_json(
        {
            "schema": 1,
            "kind": "editor-review-request",
            "pair": decode_json(pair.to_json()),
            "proposals": {s.value: text for s, text in goals.items()},
        }
    )
    decode_json(request)
    plan = plan_from_json(
        _worker(
            ["review"],
            input_text=request,
            cancel_event=cancel_event,
            timeout=timeout,
        )
    )
    _check_plan(pair, goals, plan)
    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal read-only canonical editor worker")
    modes = parser.add_subparsers(dest="mode", required=True)
    entry_parser = modes.add_parser("entry")
    entry_parser.add_argument("--config-root", required=True, type=Path)
    entry_parser.add_argument("--state-root", required=True, type=Path)
    modes.add_parser("review")
    args = parser.parse_args()
    try:
        if args.mode == "entry":
            print(inspect_entry(args.config_root, args.state_root).to_json())
        else:
            raw = sys.stdin.buffer.read(MAX_RECORD_BYTES + 1)
            if len(raw) > MAX_RECORD_BYTES:
                raise ValueError("Editor request exceeds 8 MiB transport limit")
            data = _envelope(raw.decode("utf-8"), "editor-review-request", {"pair", "proposals"})
            pair = CanonicalPairLayout.from_json(canonical_json(data["pair"]))
            if type(data["proposals"]) is not dict:
                raise ValueError("Expected scope proposal object")
            proposals = {}
            for key, text in data["proposals"].items():
                scope = Scope(key)
                if type(text) is not str:
                    raise ValueError("Expected canonical proposal text")
                model = scoped_config.read_document(text, expected_scope=scope)
                if type(model) is not ScopedConfig:
                    raise ValueError("Expected scoped canonical proposal")
                proposals[scope] = model
            print(plan_to_json(prepare_review(pair, proposals)))
    except (OSError, ValueError, RuntimeError, TypeError, RecursionError) as error:
        parser.exit(
            1, str(error).encode("utf-8", "replace")[:4096].decode("utf-8", "ignore") + "\n"
        )
