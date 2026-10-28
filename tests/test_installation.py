import builtins
import hashlib
import json
import os
import pathlib
import subprocess
import sys
from dataclasses import FrozenInstanceError
from types import ModuleType
from typing import Any, cast

import pytest

from hyprmod.core import installation
from hyprmod.core.installation import (
    MAX_PATH_BYTES,
    MAX_REGISTRY_BYTES,
    InstallationRegistry,
    RegistryDocument,
    RegistryValidationError,
    ScopeRoute,
    parse_registry,
)
from hyprmod.core.scopes import SCOPE_BASENAMES, Scope


def registry_value() -> dict:
    return {
        "schema": 1,
        "layout": "split-v2",
        "routes": {
            scope.value: {
                "lexical_path": f"/config/{SCOPE_BASENAMES[scope]}",
                "approved_resolved_path": f"/targets/{SCOPE_BASENAMES[scope]}",
            }
            for scope in Scope
        },
    }


class TestRegistry:
    def test_roundtrip_and_exact_source_identity(self):
        text = json.dumps(registry_value(), indent=2)
        document = parse_registry(text)
        canonical = document.data.to_json()
        assert document.source_sha256 == hashlib.sha256(text.encode()).hexdigest()
        assert parse_registry(canonical).data == document.data
        assert parse_registry(canonical).data.to_json() == canonical
        assert parse_registry(text + "\n").source_sha256 != document.source_sha256
        assert parse_registry(text + "\n").data == document.data
        assert json.loads(canonical) == registry_value()
        assert "source_sha256" not in canonical
        assert canonical.isascii()
        assert canonical == json.dumps(registry_value(), sort_keys=True, separators=(",", ":"))

    def test_unicode_canonical_is_ascii(self):
        value = registry_value()
        value["routes"]["appearance"]["lexical_path"] = "/caf\u00e9/attune-appearance.lua"
        document = parse_registry(json.dumps(value, ensure_ascii=False))
        assert document.data.to_json().isascii()
        assert parse_registry(document.data.to_json()).data == document.data

    @pytest.mark.parametrize(
        "text",
        [
            None,
            b"{}",
            1,
            True,
            "",
            " ",
            "{",
            "{}{}",
            "null",
            "[]",
            "1",
            '"registry"',
            "NaN",
            "Infinity",
            "-Infinity",
        ],
    )
    def test_invalid_text(self, text):
        with pytest.raises(RegistryValidationError):
            parse_registry(text)

    @pytest.mark.parametrize("field", ["schema", "layout", "routes"])
    @pytest.mark.parametrize("replacement", [None, True, False, 0, 2, 1.0, "1", [], {}])
    def test_wrong_root_values(self, field, replacement):
        value = registry_value()
        value[field] = replacement
        with pytest.raises(RegistryValidationError):
            parse_registry(json.dumps(value))

    @pytest.mark.parametrize("layout", ["v1", "legacy", "split-v1", "SPLIT-V2", "split-v2 "])
    def test_no_legacy_or_layout_aliases(self, layout):
        value = registry_value()
        value["layout"] = layout
        with pytest.raises(RegistryValidationError):
            parse_registry(json.dumps(value))

    @pytest.mark.parametrize(
        "location", [(), ("routes",), ("routes", "appearance"), ("routes", "displays")]
    )
    @pytest.mark.parametrize("mutation", ["extra", "missing", "duplicate"])
    def test_closed_fields_at_every_level(self, location, mutation):
        value = registry_value()
        node = value
        for part in location:
            node = node[part]
        key = next(iter(node))
        if mutation == "extra":
            node["unknown"] = None
        elif mutation == "missing":
            del node[key]
        text = json.dumps(value)
        if mutation == "duplicate":
            needle = json.dumps(key) + ":"
            text = text.replace(needle, needle + "null," + needle, 1)
        with pytest.raises(RegistryValidationError):
            parse_registry(text)

    @pytest.mark.parametrize("scope", list(Scope))
    @pytest.mark.parametrize("value", [None, [], "route", True, 1])
    def test_route_containers(self, scope, value):
        root = registry_value()
        root["routes"][scope] = value
        with pytest.raises(RegistryValidationError):
            parse_registry(json.dumps(root))

    @pytest.mark.parametrize(
        "location,key",
        [
            ((), "schema"),
            ((), "layout"),
            ((), "routes"),
            (("routes",), "appearance"),
            (("routes",), "displays"),
            (("routes", "appearance"), "lexical_path"),
            (("routes", "appearance"), "approved_resolved_path"),
            (("routes", "displays"), "lexical_path"),
            (("routes", "displays"), "approved_resolved_path"),
        ],
    )
    def test_every_required_field(self, location, key):
        value = registry_value()
        node = value
        for part in location:
            node = node[part]
        del node[key]
        with pytest.raises(RegistryValidationError):
            parse_registry(json.dumps(value))

    @pytest.mark.parametrize("alias", ["Appearance", "display", "DISPLAYS", "unknown"])
    def test_scope_names_are_exact(self, alias):
        value = registry_value()
        value["routes"][alias] = value["routes"].pop("displays")
        with pytest.raises(RegistryValidationError):
            parse_registry(json.dumps(value))

    @pytest.mark.parametrize("scope", list(Scope))
    @pytest.mark.parametrize("field", ["lexical_path", "approved_resolved_path"])
    @pytest.mark.parametrize(
        "path",
        [
            None,
            True,
            1,
            [],
            {},
            "",
            "relative/{name}",
            "//config/{name}",
            "/config//{name}",
            "/config/./{name}",
            "/config/../{name}",
            "/config/{name}/",
            "/config/{name}/.",
            "/config/other.lua",
            "/config/ATTUNE-APPEARANCE.LUA",
            "/~user/{name}",
            "/$HOME/{name}",
            "/${{HOME}}/{name}",
            "/$(pwd)/{name}",
            "/`pwd`/{name}",
            "/a\x00/{name}",
            "/a\n/{name}",
            "/a\t/{name}",
            "/a\x7f/{name}",
            "/a\u0085/{name}",
            "/a\u202e/{name}",
            "/a\ud800/{name}",
            "/a\udfff/{name}",
        ],
    )
    def test_invalid_paths(self, scope, field, path):
        value = registry_value()
        if isinstance(path, str):
            path = path.format(name=SCOPE_BASENAMES[scope])
        value["routes"][scope][field] = path
        with pytest.raises(RegistryValidationError):
            parse_registry(json.dumps(value))

    def test_bounds_and_deep_json(self):
        text = json.dumps(registry_value())
        assert parse_registry(text + " " * (MAX_REGISTRY_BYTES - len(text)))
        for bad in (
            text + " " * MAX_REGISTRY_BYTES,
            '"' + "\u00e9" * (MAX_REGISTRY_BYTES // 2) + '"',
            "\ud800",
            "[" * 1000 + "]" * 1000,
            '{"unknown":' + "[" * 1000 + "]" * 1000 + "}",
            "1" * 5000,
        ):
            with pytest.raises(RegistryValidationError):
                parse_registry(bad)
        value = registry_value()
        suffix = "/" + SCOPE_BASENAMES[Scope.APPEARANCE]
        path = "/" + "a" * (MAX_PATH_BYTES - len(suffix) - 1) + suffix
        value["routes"]["appearance"]["lexical_path"] = path
        assert parse_registry(json.dumps(value))
        for oversized in (
            path + "a",
            path.replace("a", "\u00e9", 1),
            "/" + "\u00e9" * 3000 + suffix,
        ):
            value["routes"]["appearance"]["lexical_path"] = oversized
            with pytest.raises(RegistryValidationError):
                parse_registry(json.dumps(value))

    @pytest.mark.parametrize("left_field", ["lexical_path", "approved_resolved_path"])
    @pytest.mark.parametrize("right_field", ["lexical_path", "approved_resolved_path"])
    @pytest.mark.parametrize("reverse", [False, True])
    def test_declared_ancestor_collisions(self, left_field, right_field, reverse):
        value = registry_value()
        first, second = list(Scope)[:: -1 if reverse else 1]
        parent = value["routes"][first][left_field]
        value["routes"][second][right_field] = parent + "/" + SCOPE_BASENAMES[second]
        with pytest.raises(RegistryValidationError, match="overlap"):
            parse_registry(json.dumps(value))

    def test_same_and_cross_alias_paths_rejected_by_scope_basename(self):
        for left_field in ("lexical_path", "approved_resolved_path"):
            for right_field in ("lexical_path", "approved_resolved_path"):
                value = registry_value()
                value["routes"]["displays"][right_field] = value["routes"]["appearance"][left_field]
                with pytest.raises(RegistryValidationError):
                    parse_registry(json.dumps(value))

    def test_same_binding_within_scope_is_allowed_and_prefix_is_not_ancestor(self):
        value = registry_value()
        route = value["routes"]["appearance"]
        route["approved_resolved_path"] = route["lexical_path"]
        value["routes"]["displays"]["lexical_path"] = (
            route["lexical_path"] + "-directory/" + SCOPE_BASENAMES[Scope.DISPLAYS]
        )
        assert parse_registry(json.dumps(value))

    @pytest.mark.parametrize("scope", list(Scope))
    @pytest.mark.parametrize("reverse", [False, True])
    def test_within_scope_file_cannot_be_declared_parent(self, scope, reverse):
        value = registry_value()
        route = value["routes"][scope]
        first, second = ("lexical_path", "approved_resolved_path")[:: -1 if reverse else 1]
        route[second] = route[first] + "/" + SCOPE_BASENAMES[scope]
        with pytest.raises(RegistryValidationError, match="overlap"):
            parse_registry(json.dumps(value))

    def test_escaped_keys_and_strings(self):
        text = json.dumps(registry_value()).replace('"schema":', '"sch\\u0065ma":')
        assert parse_registry(text)
        with pytest.raises(RegistryValidationError, match="Duplicate"):
            parse_registry(text.replace("{", '{"schema":1,', 1))
        value = registry_value()
        value["routes"]["appearance"]["lexical_path"] = '/brackets[{}]/quote"/attune-appearance.lua'
        assert parse_registry(json.dumps(value))

    def test_deep_immutability(self):
        document = parse_registry(json.dumps(registry_value()))
        for obj, field, replacement in (
            (document, "data", None),
            (document, "source_sha256", "0" * 64),
            (document.data, "appearance", None),
            (document.data.appearance, "lexical_path", "/other"),
            (document.data.displays, "scope", Scope.APPEARANCE),
        ):
            with pytest.raises((FrozenInstanceError, AttributeError)):
                setattr(obj, field, replacement)
            assert not hasattr(obj, "__dict__")
        assert hash(document)

    def test_constructor_misuse(self):
        data = parse_registry(json.dumps(registry_value())).data
        with pytest.raises(RegistryValidationError):
            ScopeRoute(
                cast(Any, "appearance"), data.appearance.lexical_path, data.appearance.lexical_path
            )
        for path in (None, [], "relative", "/wrong.lua"):
            with pytest.raises(RegistryValidationError):
                ScopeRoute(Scope.APPEARANCE, cast(Any, path), data.appearance.lexical_path)
        for appearance, displays in (({}, data.displays), (data.displays, data.appearance)):
            with pytest.raises(RegistryValidationError):
                InstallationRegistry(cast(Any, appearance), displays)
        for digest in (None, [], "", "A" * 64, "g" * 64, "0" * 63):
            with pytest.raises(RegistryValidationError):
                RegistryDocument(data, cast(Any, digest))
        with pytest.raises(RegistryValidationError):
            RegistryDocument(cast(Any, {}), "0" * 64)

    def test_no_external_actions(self, monkeypatch):
        text = json.dumps(registry_value())
        code = compile(
            pathlib.Path(installation.__file__).read_text(), installation.__file__, "exec"
        )
        probe = ModuleType("installation_purity_probe")
        original_import = builtins.__import__

        def forbidden(*args, **kwargs):
            pytest.fail("Pure registry validation attempted an external action")

        class NoEnvironment:
            __getitem__ = get = __iter__ = __contains__ = forbidden

        def guarded_import(name, *args, **kwargs):
            if name.startswith(
                ("gi", "hyprland", "hyprmod.core.config", "hyprmod.core.persistence", "hyprmod.app")
            ):
                pytest.fail(f"Pure registry validation imported integration code: {name}")
            return original_import(name, *args, **kwargs)

        with monkeypatch.context() as guard:
            guard.setitem(sys.modules, probe.__name__, probe)
            guard.setattr(builtins, "__import__", guarded_import)
            for obj, names in (
                (builtins, ("open",)),
                (
                    pathlib.Path,
                    (
                        "open",
                        "exists",
                        "resolve",
                        "stat",
                        "lstat",
                        "read_text",
                        "write_text",
                        "mkdir",
                        "home",
                    ),
                ),
                (
                    os,
                    (
                        "open",
                        "stat",
                        "lstat",
                        "readlink",
                        "listdir",
                        "scandir",
                        "getenv",
                        "getcwd",
                        "system",
                    ),
                ),
                (subprocess, ("Popen", "run", "call", "check_call", "check_output")),
            ):
                for name in names:
                    guard.setattr(obj, name, forbidden)
            guard.setattr(os, "environ", NoEnvironment())
            exec(code, probe.__dict__)
            document = probe.parse_registry(text)
            assert probe.parse_registry(document.data.to_json()).data == document.data
