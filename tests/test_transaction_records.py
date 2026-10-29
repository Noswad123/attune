"""Pure journal transport and historical semantics, never live user state."""

import builtins
import json
import os
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from hyprmod.core import scoped_review
from hyprmod.core.scopes import Scope
from hyprmod.core.transaction_records import (
    MAX_RECORD_BYTES,
    GroupSnapshot,
    Phase,
    PriorKind,
    TransactionIntent,
    canonical_json,
    decode_json,
)
from tests.test_scoped_review import appearance
from tests.test_scoped_review import evidence as evidence


@pytest.fixture
def snapshot(evidence):
    return GroupSnapshot(scoped_review.build_review(evidence, {Scope.APPEARANCE: appearance("7")}))


def intent_for(snapshot):
    return TransactionIntent(
        "a" * 32,
        snapshot.snapshot_id,
        snapshot.plan.review_hash,
        snapshot.plan.evidence.registry,
        snapshot.plan.changed_scopes,
    )


class TestRecords:
    def test_roundtrip_frozen_and_content_binding(self, snapshot):
        intent = intent_for(snapshot)
        assert GroupSnapshot.from_json(snapshot.to_json()) == snapshot
        assert TransactionIntent.from_json(intent.to_json(), snapshot=snapshot) == intent
        assert snapshot.to_json() == canonical_json(json.loads(snapshot.to_json()))
        assert replace(intent, phase=Phase.PUBLISHING).snapshot_id == snapshot.snapshot_id
        with pytest.raises(FrozenInstanceError):
            setattr(snapshot, "plan", None)
        assert not hasattr(intent, "__dict__")

    @pytest.mark.parametrize(
        "text",
        [
            '{"x":1,"x":2}',
            '{"x":{"a":0,"a":1}}',
            '{"x":[{"a":0,"a":1}]}',
            "[" * 25 + "0" + "]" * 25,
            '{"x":NaN}',
            '{"x":Infinity}',
            " " * (MAX_RECORD_BYTES + 1),
        ],
    )
    def test_strict_bounded_json(self, text):
        with pytest.raises(ValueError):
            decode_json(text)

    @pytest.mark.parametrize("kind", ["unknown", "schema", "absent", "empty", "future"])
    def test_snapshot_schema_and_prior_kinds(self, snapshot, kind):
        data = json.loads(snapshot.to_json())
        if kind == "unknown":
            data["injected"] = {}
        elif kind == "schema":
            data["schema"] = True
        else:
            data["prior_kinds"][0] = {
                "absent": "absent",
                "empty": "present-empty",
                "future": "future-prior",
            }[kind]
        with pytest.raises(ValueError):
            GroupSnapshot.from_json(canonical_json(data))
        with pytest.raises(ValueError):
            replace(snapshot, prior_kinds=(PriorKind.ABSENT, PriorKind.PRESENT_OWNED))

    @pytest.mark.parametrize("where", ["plan", "scope", "evidence", "fact"])
    def test_unknown_nested_fields(self, snapshot, where):
        data = json.loads(snapshot.to_json())
        plan = data["plan"]
        target = {
            "plan": plan,
            "scope": plan["scopes"][0],
            "evidence": plan["evidence"]["evidence"],
            "fact": plan["evidence"]["evidence"]["registry"]["path"]["facts"][0],
        }[where]
        target["extra"] = "no"
        with pytest.raises(ValueError):
            GroupSnapshot.from_json(canonical_json(data))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("previous_sha256", "0" * 64),
            ("proposed_sha256", "0" * 64),
            ("diff", "forged"),
            ("added_lines", True),
            ("removed_lines", 99),
            ("previous_content_id", "0" * 64),
            ("proposed_content_id", "0" * 64),
            ("lexical_path", "/elsewhere"),
            ("resolved_path", "/elsewhere"),
            ("proposed_text", ""),
            ("previous_text", ""),
        ],
    )
    def test_recorded_semantics_reject_tampering(self, snapshot, field, value):
        data = json.loads(snapshot.to_json())
        data["plan"]["scopes"][0][field] = value
        with pytest.raises(ValueError):
            GroupSnapshot.from_json(canonical_json(data))

    @pytest.mark.parametrize(
        "progress,phase,valid",
        [
            ((), Phase.PREPARED, True),
            ((Scope.APPEARANCE,), Phase.PREPARED, False),
            ((), Phase.COMMITTED, False),
            ((Scope.APPEARANCE,), Phase.COMMITTED, True),
            ((Scope.DISPLAYS,), Phase.PUBLISHING, False),
            ((Scope.APPEARANCE, Scope.APPEARANCE), Phase.PUBLISHING, False),
            ((Scope.APPEARANCE,), Phase.ABORTED, True),
            ((), Phase.PUBLISHING, True),
        ],
    )
    def test_advisory_progress_prefix(self, snapshot, progress, phase, valid):
        if valid:
            intent = replace(intent_for(snapshot), progress=progress, phase=phase)
            assert TransactionIntent.from_json(intent.to_json(), snapshot=snapshot) == intent
        else:
            with pytest.raises(ValueError):
                replace(intent_for(snapshot), progress=progress, phase=phase)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("transaction_id", "../escape"),
            ("transaction_id", "A" * 32),
            ("snapshot_id", "0" * 64),
            ("review_hash", "0" * 64),
            ("phase", "future"),
            ("changed_scopes", ["displays"]),
            ("registry", {}),
        ],
    )
    def test_intent_binding(self, snapshot, field, value):
        data = json.loads(intent_for(snapshot).to_json())
        data[field] = value
        with pytest.raises(ValueError):
            TransactionIntent.from_json(canonical_json(data), snapshot=snapshot)

    def test_historical_validation_has_no_io_or_stdout(self, snapshot, monkeypatch, capsys):
        plan = snapshot.plan
        Path(plan.scopes[0].resolved_path).write_text(plan.scopes[0].proposed_text)
        with pytest.raises(ValueError):
            scoped_review.revalidate_review(plan)

        def forbidden(*args, **kwargs):
            pytest.fail("Pure record model performed IO")

        for obj, names in (
            (os, ("open", "stat", "lstat", "write")),
            (builtins, ("open", "print")),
            (Path, ("open", "stat", "lstat", "read_bytes", "write_text")),
        ):
            for name in names:
                monkeypatch.setattr(obj, name, forbidden)
        assert scoped_review.validate_recorded_review(plan) is plan
        assert GroupSnapshot.from_json(snapshot.to_json()) == snapshot
        intent = intent_for(snapshot)
        assert TransactionIntent.from_json(intent.to_json(), snapshot=snapshot) == intent
        assert capsys.readouterr() == ("", "")
