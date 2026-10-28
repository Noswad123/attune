"""Inactive, pure scoped model and canonical v2 codec. No Lua is evaluated.

Appearance payload: exactly {values: {option: string}, beziers: [string],
animations: [string]}. Displays payload: exactly {monitors: [string]}.
All fields are required, including empty collections. Directive order is semantic;
scalar keys are sorted. JSON is ASCII, sorted-key, compact (no whitespace).
The content ID hashes {version, scope, payload}; the byte hash hashes the full text.
Legacy full bundles are tagged, never implicitly converted to either scope.
"""

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from hyprland_config import Assignment, Keyword, serialize_lua

from hyprmod.core import persistence
from hyprmod.core.scopes import Scope

RECORD = "-- Attune data v2: "
MAX_INPUT_BYTES = 1024 * 1024


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode(
        "ascii"
    )


@dataclass(frozen=True, init=False)
class ScopedConfig:
    scope: Scope
    values: tuple[tuple[str, str], ...]
    beziers: tuple[str, ...]
    animations: tuple[str, ...]
    monitors: tuple[str, ...]

    def __init__(self, scope: Scope | str, payload: Mapping[str, object]):
        if not isinstance(scope, str):
            raise ValueError("Invalid scope")
        scope = Scope(scope)
        fields = {"values", "beziers", "animations"} if scope == Scope.APPEARANCE else {"monitors"}
        if not isinstance(payload, Mapping) or set(payload) != fields:
            raise ValueError("Payload fields do not match scope")
        values = payload.get("values", {})
        if not isinstance(values, Mapping) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in values.items()
        ):
            raise ValueError("Expected string scalar mapping")
        sections: dict[str, list[str]] = {}
        for field in fields - {"values"}:
            lines = payload[field]
            if not isinstance(lines, (list, tuple)) or not all(isinstance(v, str) for v in lines):
                raise ValueError("Expected directive strings")
            sections[field] = list(lines)
        persistence.build_document(dict(values), sections)
        for lines in sections.values():
            identities = [line.split("=", 1)[1].split(",", 1)[0].strip() for line in lines]
            if len(set(identities)) != len(identities):
                raise ValueError("Duplicate directive record")
        # Reject invalid Unicode even when JSON would hide it behind ASCII escapes.
        try:
            for value in (*values.keys(), *values.values()):
                value.encode("utf-8")
            for lines in sections.values():
                for line in lines:
                    line.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("Invalid UTF-8 payload") from exc
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "values", tuple(sorted(values.items())))
        for field in ("beziers", "animations", "monitors"):
            object.__setattr__(self, field, tuple(sections.get(field, [])))

    def payload(self) -> dict[str, object]:
        if self.scope == Scope.DISPLAYS:
            return {"monitors": list(self.monitors)}
        return {
            "values": dict(self.values),
            "beziers": list(self.beziers),
            "animations": list(self.animations),
        }

    @property
    def content_id(self) -> str:
        return hashlib.sha256(
            _canonical({"version": 2, "scope": self.scope, "payload": self.payload()})
        ).hexdigest()


@dataclass(frozen=True)
class LegacyBundle:
    text: str
    kind: Literal["legacy-full-bundle"] = "legacy-full-bundle"


def partition_legacy(bundle: LegacyBundle) -> tuple[ScopedConfig, ScopedConfig]:
    """Explicitly partition owned v1 data; this grants no conversion or write approval."""
    if not isinstance(bundle, LegacyBundle) or bundle.kind != "legacy-full-bundle":
        raise ValueError("Expected a legacy full bundle")
    validated = read_document(bundle.text)
    if not isinstance(validated, LegacyBundle):
        raise ValueError("Expected canonical v1 full-bundle text")
    document = persistence.read_document(validated.text)
    values = {}
    sections: dict[str, list[str]] = {"bezier": [], "animation": [], "monitor": []}
    for line in document.lines:
        if isinstance(line, Assignment):
            values[line.full_key] = line.value
        elif isinstance(line, Keyword):
            if line.key not in sections:
                raise ValueError("Unsupported legacy directive")
            sections[line.key].append(line.raw.rstrip("\n"))
    return (
        ScopedConfig(
            Scope.APPEARANCE,
            {"values": values, "beziers": sections["bezier"], "animations": sections["animation"]},
        ),
        ScopedConfig(Scope.DISPLAYS, {"monitors": sections["monitor"]}),
    )


def build_text(config: ScopedConfig) -> str:
    payload = config.payload()
    sections = {k: v for k, v in payload.items() if k != "values"}
    lua = serialize_lua(persistence.build_document(dict(config.values), sections))
    if not lua.startswith(persistence.MARKER):
        raise ValueError("Lua emitter did not preserve Attune ownership")
    record = {
        "version": 2,
        "scope": config.scope,
        "payload": payload,
        "content_id": config.content_id,
    }
    text = (
        persistence.MARKER
        + RECORD
        + base64.b64encode(_canonical(record)).decode("ascii")
        + "\n"
        + lua[len(persistence.MARKER) :]
    )
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Attune text exceeds 1 MiB limit")
    return text


def byte_hash(text: str) -> str:
    """Full emitted UTF-8 byte identity, not the scope-local content ID."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def read_document(
    text: str, *, expected_scope: Scope | str | None = None
) -> ScopedConfig | LegacyBundle:
    """Dispatch canonical v1/v2 text without granting write or routing authority."""
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("Expected bounded UTF-8 text")
        if expected_scope is not None:
            if not isinstance(expected_scope, str):
                raise ValueError("Invalid expected scope")
            expected_scope = Scope(expected_scope)
        if text.startswith(persistence.MARKER + persistence.RECORD):
            persistence.read_document(text)
            if expected_scope is not None:
                raise ValueError("Legacy full bundle requires explicit conversion review")
            return LegacyBundle(text)
        if not text.startswith(persistence.MARKER + RECORD):
            raise ValueError("Expected canonical Attune v2 text")
        encoded = text.split("\n", 2)[1][len(RECORD) :]
        raw = base64.b64decode(encoded, validate=True)
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != {"version", "scope", "payload", "content_id"}:
            raise ValueError("Invalid v2 record fields")
        if type(data["version"]) is not int or data["version"] != 2:
            raise ValueError("Unsupported Attune version")
        config = ScopedConfig(data["scope"], data["payload"])
        content_id = data["content_id"]
        if not isinstance(content_id, str) or re.fullmatch(r"[0-9a-f]{64}", content_id) is None:
            raise ValueError("Invalid content ID")
        if config.content_id != content_id:
            raise ValueError("Content ID mismatch")
        if expected_scope is not None and config.scope != expected_scope:
            raise ValueError("Scope mismatch")
        if build_text(config) != text:
            raise ValueError("Noncanonical or edited Attune text")
        return config
    except (UnicodeError, binascii.Error, TypeError, RecursionError, OverflowError) as exc:
        raise ValueError("Invalid Attune data record") from exc
