"""Pure metadata boundaries; historical fixtures are never regenerated."""

import base64
import builtins
import hashlib
import io
import json
import os
import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from hyprmod.core import persistence, scoped_config
from hyprmod.core.scoped_backups import describe_backup
from hyprmod.core.scopes import Scope

FIXTURES = Path(__file__).parent / "fixtures/canonical_v1"


def name_for(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest() + ".lua"


class TestBackupDescriptors:
    def test_all_appearance_section_counts(self):
        config = scoped_config.ScopedConfig(
            Scope.APPEARANCE,
            {
                "values": {"general:gaps_in": "7"},
                "beziers": ["bezier = ease, 0, 0, 1, 1"],
                "animations": ["animation = windows, 1, 5, ease"],
            },
        )
        text = scoped_config.build_text(config)
        assert describe_backup(name_for(text), text).counts == (1, 1, 1, 0)

    @pytest.mark.parametrize(
        "fixture,digest,counts",
        [
            (
                "combined",
                "b9cf20426011f4af74e77ff041a9bbba16cee93046f9924aface55e277fc1bba",
                (3, 1, 1, 3),
            ),
            (
                "empty",
                "bc75ca71ad89fac9c87dc2c05e4c178638bdc66c8699d694a61ae8d0ea66e4f5",
                (0, 0, 0, 0),
            ),
        ],
    )
    def test_literal_v1_stays_whole(self, fixture, digest, counts):
        text = (FIXTURES / f"{fixture}.lua").read_text()
        descriptor = describe_backup(digest + ".lua", text)
        assert descriptor.kind == "legacy-full-bundle"
        assert descriptor.version == 1
        assert descriptor.scope is descriptor.content_id is None
        assert descriptor.counts == counts
        assert descriptor.sha256 == digest
        assert descriptor.size_bytes == len(text.encode())
        for scope in Scope:
            with pytest.raises(ValueError, match="explicit conversion"):
                describe_backup(digest + ".lua", text, expected_scope=scope)
        with pytest.raises(ValueError):
            replace(descriptor, kind="scoped-v2", version=2, scope=Scope.APPEARANCE)

    @pytest.mark.parametrize("scope", list(Scope))
    @pytest.mark.parametrize("empty", [False, True])
    def test_scoped_identity(self, scope, empty):
        payload = (
            {"values": {} if empty else {"general:gaps_in": "7"}, "beziers": [], "animations": []}
            if scope == Scope.APPEARANCE
            else {"monitors": [] if empty else ["monitor = DP-9, disable"]}
        )
        config = scoped_config.ScopedConfig(scope, payload)
        text = scoped_config.build_text(config)
        descriptor = describe_backup(name_for(text), text, expected_scope=scope)
        assert descriptor.scope is scope
        assert descriptor.kind == "scoped-v2"
        assert descriptor.content_id == config.content_id != descriptor.sha256
        assert descriptor.sha256 == name_for(text)[:-4]
        assert descriptor.counts == (
            (0, 0, 0, 0) if empty else (1, 0, 0, 0) if scope == Scope.APPEARANCE else (0, 0, 0, 1)
        )
        with pytest.raises(FrozenInstanceError):
            setattr(descriptor, "scope", Scope.DISPLAYS)
        for counts in ([0, 0, 0, 0], (True, 0, 0, 0), (-1, 0, 0, 0), (2**30, 0, 0, 0), (0,)):
            with pytest.raises(ValueError):
                replace(descriptor, counts=counts)
        for changes in (
            {"version": True},
            {"size_bytes": True},
            {"sha256": "f" * 64},
            {"scope": "appearance"},
        ):
            with pytest.raises(ValueError):
                replace(descriptor, **changes)
        wrong = Scope.DISPLAYS if scope == Scope.APPEARANCE else Scope.APPEARANCE
        with pytest.raises(ValueError, match="Scope mismatch"):
            describe_backup(name_for(text), text, expected_scope=wrong)

    @pytest.mark.parametrize(
        "name",
        [None, 1, "a.lua", "A" * 64 + ".lua", "../" + "a" * 64 + ".lua", "a" * 64 + ".lua\n"],
    )
    def test_bad_names(self, name):
        with pytest.raises(ValueError):
            describe_backup(name, "irrelevant")

    def test_hash_before_classification(self, monkeypatch):
        def forbidden(*args, **kwargs):
            pytest.fail("Classification before hash verification")

        monkeypatch.setattr(scoped_config, "read_document", forbidden)
        with pytest.raises(ValueError, match="byte hash"):
            describe_backup("a" * 64 + ".lua", "tampered")

    @pytest.mark.parametrize(
        "text",
        [
            None,
            b"\x00",
            1,
            "\ud800",
            "x" * (scoped_config.MAX_INPUT_BYTES + 1),
            "\u00e9" * scoped_config.MAX_INPUT_BYTES,
        ],
    )
    def test_invalid_text_types_and_sizes(self, text):
        with pytest.raises(ValueError):
            describe_backup("a" * 64 + ".lua", text)

    def test_canonical_refusals(self):
        config = scoped_config.ScopedConfig(Scope.DISPLAYS, {"monitors": []})
        text = scoped_config.build_text(config)
        prefix, encoded, body = text.split("\n", 2)
        raw = base64.b64decode(encoded[len(scoped_config.RECORD) :])
        data = json.loads(raw)
        variants = [
            text + "-- edit\n",
            text + "\x00",
            "",
            "os.execute('false')\n",
            text.replace("v2:", "v9:"),
        ]
        for field, value in (
            ("version", 9),
            ("payload", {"monitors": [], "values": {}}),
            ("scope", "appearance"),
        ):
            variants.append(
                prefix
                + "\n"
                + scoped_config.RECORD
                + base64.b64encode(json.dumps({**data, field: value}).encode()).decode()
                + "\n"
                + body
            )
        duplicate = raw.replace(b'"version":2', b'"version":2,"version":2')
        variants.append(
            prefix
            + "\n"
            + scoped_config.RECORD
            + base64.b64encode(duplicate).decode()
            + "\n"
            + body
        )
        for variant in variants:
            with pytest.raises(ValueError):
                describe_backup(name_for(variant), variant)

    def test_no_io_execution_or_partition(self, monkeypatch):
        texts = [
            (FIXTURES / "combined.lua").read_text(),
            scoped_config.build_text(scoped_config.ScopedConfig(Scope.DISPLAYS, {"monitors": []})),
        ]

        def forbidden(*args, **kwargs):
            pytest.fail("Unexpected IO, execution, or implicit partition")

        for module, attr in (
            (builtins, "open"),
            (io, "open"),
            (os, "open"),
            (subprocess, "run"),
            (subprocess, "Popen"),
            (persistence, "validate_lua"),
            (scoped_config, "partition_legacy"),
        ):
            monkeypatch.setattr(module, attr, forbidden)
        for text in texts:
            describe_backup(name_for(text), text)
