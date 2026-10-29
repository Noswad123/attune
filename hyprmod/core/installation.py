"""Pure split-v2 declarations, not filesystem approval or write authority.

The separate route_approval layer observes actual resolution, protected aliases,
file types, permissions, and Git policy. Even approved_resolved_path is only an
unverified declaration here. Neither layer performs discovery or activation.
"""

import hashlib
import json
import unicodedata
from dataclasses import dataclass

from hyprmod.core.scopes import SCOPE_BASENAMES, Scope

MAX_REGISTRY_BYTES = 64 * 1024
MAX_PATH_BYTES = 4096
MAX_JSON_DEPTH = 16


class RegistryValidationError(ValueError):
    """A present registry declaration is invalid; never implies v1 fallback."""


def _path(value: str, scope: Scope) -> None:
    if type(value) is not str or not value or len(value) > MAX_PATH_BYTES:
        raise RegistryValidationError("Paths must be nonempty bounded strings")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise RegistryValidationError("Paths must be valid UTF-8") from error
    if size > MAX_PATH_BYTES or any(unicodedata.category(c) in {"Cc", "Cf"} for c in value):
        raise RegistryValidationError("Path exceeds byte limit or contains controls")
    parts = value.split("/")
    if (
        not value.startswith("/")
        or any(part in ("", ".", "..") for part in parts[1:])
        or "~" in value
        or "$" in value
        or "`" in value
        or parts[-1] != SCOPE_BASENAMES[scope]
    ):
        raise RegistryValidationError(f"Expected normalized absolute {scope} path")


@dataclass(frozen=True, slots=True)
class ScopeRoute:
    scope: Scope
    lexical_path: str
    approved_resolved_path: str

    def __post_init__(self) -> None:
        if type(self.scope) is not Scope:
            raise RegistryValidationError("Route scope must be a Scope")
        _path(self.lexical_path, self.scope)
        _path(self.approved_resolved_path, self.scope)


@dataclass(frozen=True, slots=True)
class InstallationRegistry:
    """Structurally valid, deeply immutable, filesystem-unverified routes."""

    appearance: ScopeRoute
    displays: ScopeRoute

    def __post_init__(self) -> None:
        for scope in Scope:
            route = getattr(self, scope.value)
            if type(route) is not ScopeRoute or route.scope is not scope:
                raise RegistryValidationError(f"Expected {scope} route")
        paths = tuple(
            (route.scope, path)
            for route in (self.appearance, self.displays)
            for path in (route.lexical_path, route.approved_resolved_path)
        )
        for index, (left_scope, left) in enumerate(paths):
            for right_scope, right in paths[index + 1 :]:
                if (
                    (left_scope != right_scope and left == right)
                    or left.startswith(right + "/")
                    or right.startswith(left + "/")
                ):
                    raise RegistryValidationError("Declared scope routes collide or overlap")

    def to_json(self) -> str:
        """Canonical schema only; this output does not carry source_sha256."""
        return json.dumps(
            {
                "schema": 1,
                "layout": "split-v2",
                "routes": {
                    scope.value: {
                        "lexical_path": getattr(self, scope.value).lexical_path,
                        "approved_resolved_path": getattr(self, scope.value).approved_resolved_path,
                    }
                    for scope in Scope
                },
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class RegistryDocument:
    """Parsed data and SHA-256 of exact input UTF-8 bytes, not canonical output."""

    data: InstallationRegistry
    source_sha256: str

    def __post_init__(self) -> None:
        if type(self.data) is not InstallationRegistry:
            raise RegistryValidationError("Expected InstallationRegistry data")
        if (
            type(self.source_sha256) is not str
            or len(self.source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.source_sha256)
        ):
            raise RegistryValidationError("Expected lowercase SHA-256 hex digest")


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RegistryValidationError(f"Duplicate field: {key!r}")
        result[key] = value
    return result


def _fields(value: object, expected: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise RegistryValidationError(f"Expected exactly these fields: {sorted(expected)}")
    return value


def _constant(value: str) -> object:
    raise RegistryValidationError(f"Non-JSON constant: {value}")


def parse_registry(text: str) -> RegistryDocument:
    """Validate a present JSON descriptor without consulting any external state."""
    if type(text) is not str or not text or len(text) > MAX_REGISTRY_BYTES:
        raise RegistryValidationError("Registry must be nonempty bounded JSON text")
    try:
        source = text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise RegistryValidationError("Registry must be valid UTF-8") from error
    if len(source) > MAX_REGISTRY_BYTES:
        raise RegistryValidationError("Registry exceeds byte limit")

    # Bound nesting before the JSON decoder allocates nested containers.
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
                raise RegistryValidationError("Registry JSON is too deeply nested")
        elif char in "]}":
            depth -= 1
    try:
        value = json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, RecursionError) as error:
        raise RegistryValidationError(f"Invalid registry JSON: {error}") from error
    root = _fields(value, {"schema", "layout", "routes"})
    if type(root["schema"]) is not int or root["schema"] != 1:
        raise RegistryValidationError("Expected schema integer 1")
    if type(root["layout"]) is not str or root["layout"] != "split-v2":
        raise RegistryValidationError("Expected split-v2 layout")
    routes = _fields(root["routes"], {scope.value for scope in Scope})
    parsed: dict[Scope, ScopeRoute] = {}
    for scope in Scope:
        fields = _fields(routes[scope.value], {"lexical_path", "approved_resolved_path"})
        lexical = fields["lexical_path"]
        resolved = fields["approved_resolved_path"]
        if type(lexical) is not str or type(resolved) is not str:
            raise RegistryValidationError("Route paths must be strings")
        parsed[scope] = ScopeRoute(scope, lexical, resolved)
    return RegistryDocument(
        InstallationRegistry(parsed[Scope.APPEARANCE], parsed[Scope.DISPLAYS]),
        hashlib.sha256(source).hexdigest(),
    )
