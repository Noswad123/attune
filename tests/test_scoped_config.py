"""Inactive codec boundaries, with no compositor or Lua execution."""

import base64
import hashlib
import json
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from hyprmod.core import persistence
from hyprmod.core.focused_ui import ReviewSnapshot
from hyprmod.core.scoped_config import (
    MAX_INPUT_BYTES,
    RECORD,
    ScopedConfig,
    build_text,
    byte_hash,
    read_document,
)
from hyprmod.core.scopes import Scope


def appearance(**changes):
    return {"values": {}, "beziers": [], "animations": [], **changes}


def envelope(raw, body=""):
    return persistence.MARKER + RECORD + base64.b64encode(raw).decode() + "\n" + body


def record(config):
    return json.loads(base64.b64decode(build_text(config).splitlines()[1][len(RECORD) :]))


class TestScopedModel:
    @pytest.mark.parametrize(
        "scope,payload", [(Scope.APPEARANCE, appearance()), (Scope.DISPLAYS, {"monitors": []})]
    )
    def test_empty_scope_roundtrip(self, scope, payload):
        config = ScopedConfig(scope, payload)
        text = build_text(config)
        assert read_document(text, expected_scope=scope) == config
        assert config.content_id != byte_hash(text)
        assert len(config.content_id) == 64
        data = record(config)
        del data["content_id"]
        canonical = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        assert config.content_id == hashlib.sha256(canonical.encode()).hexdigest()
        assert byte_hash(text) == hashlib.sha256(text.encode()).hexdigest()

    @pytest.mark.parametrize(
        "scope,payload",
        [
            (Scope.APPEARANCE, appearance(monitors=[])),
            (Scope.APPEARANCE, appearance(monitors=None)),
            (Scope.DISPLAYS, {"monitors": [], "values": {}}),
            (Scope.DISPLAYS, {"monitors": [], "beziers": []}),
            (Scope.DISPLAYS, {"monitors": [], "animations": []}),
            (Scope.APPEARANCE, {"values": {}}),
            (Scope.DISPLAYS, {}),
            (Scope.APPEARANCE, appearance(values={"general:layout": "dwindle"})),
            (Scope.APPEARANCE, appearance(values={"exec": "evil()"})),
            (Scope.APPEARANCE, appearance(values={"general:gaps_in": 1})),
            (Scope.APPEARANCE, appearance(values={1: "1"})),
            (Scope.APPEARANCE, appearance(values=[])),
            (Scope.APPEARANCE, appearance(animations=None)),
            (Scope.APPEARANCE, appearance(beziers="bezier = a, 0, 0, 1, 1")),
            (Scope.DISPLAYS, {"monitors": [1]}),
            (Scope.DISPLAYS, {"monitors": ["monitor = DP-1, disable"] * 2}),
            (
                Scope.DISPLAYS,
                {"monitors": ["monitor = DP-1, disable", "monitor=DP-1, preferred, auto, 1"]},
            ),
            (
                Scope.APPEARANCE,
                appearance(beziers=["bezier = ease, 0, 0, 1, 1", "bezier= ease, 1, 1, 0, 0"]),
            ),
            (
                Scope.APPEARANCE,
                appearance(
                    animations=["animation = windows, 0", "animation=windows, 1, 5, default"]
                ),
            ),
            (Scope.APPEARANCE, appearance(values={"general:gaps_in": "1e999"})),
            (Scope.APPEARANCE, appearance(values={"general:gaps_in": "$evil"})),
            (Scope.APPEARANCE, appearance(values={"general:gaps_in": "1\nevil()"})),
            (Scope.APPEARANCE, appearance(values={"decoration:rounding": "\ud800"})),
            ("unknown", {}),
            (True, {}),
        ],
    )
    def test_closed_shape_and_strict_types(self, scope, payload):
        with pytest.raises(ValueError):
            ScopedConfig(scope, payload)

    def test_deep_immutability_and_order(self):
        values = {"general:gaps_in": "7", "decoration:rounding": "12"}
        curves = ["bezier = z, 0, 0, 1, 1", "bezier = a, 0, 0, 1, 1"]
        animations = ["animation = windows, 1, 5, z", "animation = fade, 0"]
        config = ScopedConfig(
            "appearance", appearance(values=values, beziers=curves, animations=animations)
        )
        text = build_text(config)
        assert config.values == tuple(sorted(values.items()))
        assert config.beziers == tuple(curves)
        assert config.animations == tuple(animations)
        assert text.index('hl.curve("z"') < text.index('hl.curve("a"') < text.index("hl.animation")
        same = ScopedConfig(
            "appearance",
            appearance(
                values=dict(reversed(list(values.items()))), beziers=curves, animations=animations
            ),
        )
        assert build_text(same) == text
        values.clear()
        curves.clear()
        animations.clear()
        config.payload().clear()
        assert build_text(config) == text
        with pytest.raises(FrozenInstanceError):
            setattr(config, "scope", Scope.DISPLAYS)

    def test_disconnected_and_disabled_order(self):
        lines = ["monitor = DP-9, preferred, auto, 1", "monitor = HDMI-A-9, disable"]
        config = ScopedConfig("displays", {"monitors": lines})
        assert read_document(build_text(config)) == config
        assert config.monitors == tuple(lines)
        assert config.content_id != ScopedConfig("displays", {"monitors": lines[::-1]}).content_id

    def test_independent_identity_and_cross_routing(self):
        displays = ScopedConfig("displays", {"monitors": []})
        before = displays.content_id
        first = ScopedConfig("appearance", appearance())
        second = ScopedConfig("appearance", appearance(values={"general:gaps_in": "5"}))
        assert first.content_id != second.content_id
        assert before == displays.content_id != first.content_id
        for config, wrong in [(first, Scope.DISPLAYS), (displays, Scope.APPEARANCE)]:
            with pytest.raises(ValueError, match="Scope mismatch"):
                read_document(build_text(config), expected_scope=wrong)

    def test_scalar_code_is_only_a_string(self):
        value = '"); os.execute("evil"); --'
        config = ScopedConfig("appearance", appearance(values={"decoration:shadow:color": value}))
        text = build_text(config)
        assert '\\"' in text
        assert read_document(text) == config


class TestStrictCodec:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("version", True),
            ("version", 1),
            ("version", 3),
            ("version", 2.0),
            ("scope", "other"),
            ("scope", 1),
            ("scope", None),
            ("payload", []),
            ("payload", None),
            ("payload", {"monitors": []}),
            ("content_id", "A" * 64),
            ("content_id", "0" * 64),
            ("content_id", 1),
            ("extra", {}),
        ],
    )
    def test_invalid_record(self, field, value):
        data = record(ScopedConfig("appearance", appearance()))
        data[field] = value
        with pytest.raises(ValueError):
            read_document(envelope(json.dumps(data).encode()))

    @pytest.mark.parametrize(
        "raw",
        [
            b'{"version":2,"version":2}',
            b'{"payload":{"values":{"x":"1","x":"2"}}}',
            b'{"payload":{"monitors":[],"monitors":[]}}',
            b"[]",
            b"null",
            b"NaN",
            b"Infinity",
            b'"\xff"',
            b"[" * 2000 + b"]" * 2000,
        ],
    )
    def test_bad_json(self, raw):
        with pytest.raises(ValueError):
            read_document(envelope(raw))

    @pytest.mark.parametrize("nested", [False, True])
    def test_duplicate_keys_in_otherwise_valid_document(self, nested):
        config = ScopedConfig("appearance", appearance(values={"general:gaps_in": "1"}))
        text = build_text(config)
        raw = base64.b64decode(text.splitlines()[1][len(RECORD) :])
        if nested:
            raw = raw.replace(
                b'"general:gaps_in":"1"', b'"general:gaps_in":"1","general:gaps_in":"1"'
            )
        else:
            raw = raw.replace(b'"version":2', b'"version":2,"version":2')
        with pytest.raises(ValueError, match="Duplicate JSON key"):
            read_document(envelope(raw, text.split("\n", 2)[2]))

    @pytest.mark.parametrize("field", ["version", "scope", "payload", "content_id"])
    def test_missing_record_fields(self, field):
        data = record(ScopedConfig("displays", {"monitors": []}))
        del data[field]
        with pytest.raises(ValueError, match="record fields"):
            read_document(envelope(json.dumps(data).encode()))

    def test_output_size_limit(self):
        config = ScopedConfig(
            "appearance", appearance(values={"decoration:shadow:color": "x" * MAX_INPUT_BYTES})
        )
        with pytest.raises(ValueError, match="limit"):
            build_text(config)

    def test_exact_regeneration(self):
        config = ScopedConfig("appearance", appearance(values={"general:gaps_in": "1"}))
        text = build_text(config)
        data = record(config)
        variants = [
            text + "-- added comment\n",
            text + "os.execute('evil')\n",
            text.replace("gaps_in = 1", "gaps_in = 2"),
            text.replace("Attune data", "Other data"),
            text.replace("\n", "\r\n"),
            text.rstrip("\n"),
            envelope(json.dumps(data).encode()),
            envelope(
                json.dumps(dict(reversed(list(data.items()))), separators=(",", ":")).encode()
            ),
            text.replace("\n", " \n", 2),
            persistence.MARKER + RECORD + "!!!\n",
            "",
            "-- Generated by Attune\n",
            "x" * (MAX_INPUT_BYTES + 1),
            "\ud800",
        ]
        for variant in variants:
            with pytest.raises(ValueError):
                read_document(variant)

    def test_noncanonical_base64(self):
        text = build_text(ScopedConfig("displays", {"monitors": []}))
        prefix, encoded, body = text.split("\n", 2)
        encoded = encoded[len(RECORD) :]
        with pytest.raises(ValueError):
            read_document(prefix + "\n" + RECORD + encoded + "=\n" + body)

    def test_pure_and_active_v1_apis_refuse_v2(self, monkeypatch, tmp_path):
        def forbidden(*args, **kwargs):
            pytest.fail("Unexpected IO, subprocess, or Lua validation")

        monkeypatch.setattr(subprocess, "run", forbidden)
        monkeypatch.setattr(subprocess, "Popen", forbidden)
        monkeypatch.setattr(persistence, "validate_lua", forbidden)
        monkeypatch.setattr(Path, "write_text", forbidden)
        monkeypatch.setattr(Path, "write_bytes", forbidden)
        monkeypatch.setattr(persistence.os, "open", forbidden)
        config = ScopedConfig("displays", {"monitors": []})
        text = build_text(config)
        assert read_document(text) == config
        with pytest.raises(ValueError):
            persistence.read_document(text)
        path = tmp_path / "attune.lua"
        snapshot = ReviewSnapshot(path, "", text, path)
        with pytest.raises(ValueError):
            persistence.persist_snapshot(snapshot)
