"""Saved/runtime observations use canonical fixtures and mocked read-only IPC."""

import json
import os
import subprocess

import pytest

from hyprmod.core import config, health, persistence


@pytest.fixture
def drift(tmp_path, monkeypatch):
    path = tmp_path / "attune.lua"
    replies = {}
    calls = []
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "mock-session")
    monkeypatch.setattr(health.shutil, "which", lambda name: f"/fake/{name}")

    def run(command, **kwargs):
        assert command[:2] == ["/fake/hyprctl", "-j"]
        assert kwargs["max_bytes"] == 128 * 1024
        assert 0 < kwargs["timeout"] <= 2
        if command[2] != "getoption":
            assert len(command) == 3
            data = {"version": {"version": "0.55"}, "configerrors": [], "monitors": []}[command[2]]
        else:
            assert len(command) == 4
            calls.append(command[3])
            data = replies[command[3]]
            if isinstance(data, Exception):
                raise data
            if isinstance(data, subprocess.CompletedProcess):
                return data
        return subprocess.CompletedProcess(command, 0, json.dumps(data), "")

    monkeypatch.setattr(health, "run_bounded", run)

    def collect(values, sections=None):
        path.write_text(persistence.build_text(values, sections or config.ConfigSections()))
        before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        snapshot = health.collect_snapshot(path)
        assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        assert len(snapshot.checks) == 7
        assert health.HealthSnapshot.from_json(snapshot.to_json()) == snapshot
        return snapshot.checks[-1]

    return path, replies, calls, collect


class TestScalarDrift:
    @pytest.mark.parametrize(
        ("key", "saved", "field", "runtime"),
        [
            ("decoration:rounding", "12", "int", 12),
            ("decoration:rounding", "12.0", "int", 12),
            ("decoration:active_opacity", "1", "float", 1.0),
            ("decoration:active_opacity", "0.5", "float", 0.5000001),
            ("decoration:blur:enabled", "true", "bool", True),
            ("decoration:blur:enabled", "1", "bool", 1),
            ("decoration:blur:enabled", "false", "bool", False),
            ("animations:enabled", "0", "bool", 0),
            ("general:gaps_in", "5", "css", "5 5 5 5"),
            ("general:gaps_out", "5 10", "css", "5 10 5 10"),
            ("general:gaps_out", "5 10 15", "css", "5 10 15 10"),
            ("decoration:shadow:offset", "-1 2.5", "vec2", [-1, 2.5]),
            (
                "general:col.active_border",
                "rgba(c6a0f6ff) rgba(b7bdf8ff) 405deg",
                "gradient",
                "ffc6a0f6 ffb7bdf8 45deg",
            ),
            ("general:col.inactive_border", "rgb(c6a0f6)", "gradient", "ffc6a0f6 0deg"),
            ("decoration:shadow:color", "0xaa181926", "gradient", "aa181926 360deg"),
            ("decoration:shadow:color", "rgba(181926aa)", "gradient", "aa181926 0deg"),
        ],
    )
    def test_equivalent_native_shapes(self, drift, key, saved, field, runtime):
        _, replies, calls, collect = drift
        replies[key] = {"option": key, "set": True, field: runtime}
        check = collect({key: saved})
        assert check.status == "available"
        assert check.summary == "1 matching, 0 differing, 0 unknown saved scalar options"
        assert calls == [key]
        assert f"saved={saved!r}" in check.details[1]
        assert f"runtime={runtime!r}" in check.details[1]
        assert "does not establish" in check.details[0]

    @pytest.mark.parametrize(
        ("key", "saved", "field", "runtime"),
        [
            ("decoration:rounding", "12", "int", 13),
            ("decoration:active_opacity", "0.5", "float", 0.50001),
            ("decoration:blur:enabled", "true", "bool", False),
            ("general:gaps_in", "5", "css", "5 5 5 6"),
            ("decoration:shadow:offset", "1 2", "vec2", [2, 1]),
            ("general:col.active_border", "rgba(c6a0f6ff) 45deg", "gradient", "ffc6a0f6 46deg"),
            ("decoration:shadow:color", "rgba(181926aa)", "gradient", "ab181926 0deg"),
        ],
    )
    def test_differences_are_not_configuration_failures(self, drift, key, saved, field, runtime):
        _, replies, _, collect = drift
        replies[key] = {"option": key, "set": True, field: runtime}
        check = collect({key: saved})
        assert check.status == "unknown"
        assert "0 matching, 1 differing, 0 unknown" in check.summary

    @pytest.mark.parametrize(
        ("key", "saved", "reply"),
        [
            ("decoration:rounding", "12", {"int": True}),
            ("decoration:rounding", "12", {"int": 12.0}),
            ("decoration:rounding", "12", {"float": 12}),
            ("decoration:rounding", "12", {}),
            ("decoration:rounding", "12", {"int": "12"}),
            ("decoration:active_opacity", "1", {"float": True}),
            ("decoration:active_opacity", "1", {"float": float("nan")}),
            ("decoration:active_opacity", "1", {"float": float("inf")}),
            ("decoration:blur:enabled", "true", {"int": 1}),
            ("decoration:blur:enabled", "true", {"bool": 2}),
            ("decoration:blur:enabled", "true", {"bool": 1.0}),
            ("decoration:blur:enabled", "true", {"bool": "true"}),
            ("general:gaps_in", "5", {"css": "5 nope"}),
            ("general:gaps_in", "5", {"css": "nan"}),
            ("general:gaps_in", "5", {"css": "1 2 3 4 5"}),
            ("decoration:shadow:offset", "1 2", {"vec2": [True, 2]}),
            ("decoration:shadow:offset", "1 2", {"vec2": [1, float("inf")]}),
            ("decoration:shadow:offset", "1 2", {"vec2": "1 2"}),
            ("decoration:shadow:color", "rgb(123456)", {"gradient": "garbage"}),
            ("decoration:shadow:color", "rgb(123456)", {"gradient": "ff123456 nandeg"}),
        ],
    )
    def test_malformed_typed_data_is_unknown(self, drift, key, saved, reply):
        _, replies, _, collect = drift
        replies[key] = {"option": key, "set": True, **reply}
        check = collect({key: saved})
        assert check.status == "unknown"
        assert "0 matching, 0 differing, 1 unknown" in check.summary

    @pytest.mark.parametrize(
        "reply",
        [
            {"option": "decoration:other", "set": True, "int": 12},
            {"set": True, "int": 12},
            {"option": "decoration:rounding", "int": 12},
            {"option": "decoration:rounding", "set": False, "int": 12},
            {"option": "decoration:rounding", "set": 1, "int": 12},
            [],
            subprocess.CompletedProcess([], 1, "", ""),
            subprocess.CompletedProcess([], 0, "not json", ""),
            OSError("unreachable"),
            ValueError("Health command response exceeds capture limit"),
            subprocess.TimeoutExpired("hyprctl", 2),
        ],
    )
    def test_unknown_reply_preserves_matching(self, drift, reply):
        _, replies, calls, collect = drift
        replies["decoration:rounding"] = reply
        replies["animations:enabled"] = {"option": "animations:enabled", "set": True, "bool": True}
        check = collect({"decoration:rounding": "12", "animations:enabled": "true"})
        assert check.status == "unknown"
        assert "1 matching, 0 differing, 1 unknown" in check.summary
        assert len(calls) == 2


class TestDriftBoundaries:
    def test_unsupported_schema_and_types_never_queried(self, drift):
        _, _, calls, collect = drift
        check = collect({"decoration:unknown_option": "1", "decoration:screen_shader": "shader"})
        assert calls == []
        assert check.status == "unknown"
        assert "2 unknown" in check.summary

    @pytest.mark.parametrize("key", ["decoration:x;reload", "decoration:x&&exec", "decoration:x\n"])
    def test_unsafe_keys_rejected_before_queries(self, drift, key):
        path, _, calls, _ = drift
        path.write_text("-- Generated by Attune\n" + key)
        snapshot = health.collect_snapshot(path)
        assert snapshot.checks[-1].status == "unavailable"
        assert calls == []

    def test_empty_options_not_healthy_proof(self, drift):
        _, _, calls, collect = drift
        check = collect({}, config.ConfigSections(beziers=["bezier = test, 0, 0, 1, 1"]))
        assert check.status == "unknown"
        assert "no saved scalar comparisons" in check.summary
        assert calls == []

    def test_empty_options_offline_still_unknown(self, drift, monkeypatch):
        monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE")
        assert drift[3]({}).status == "unknown"

    def test_no_session_no_defaults(self, drift, monkeypatch):
        _, _, calls, collect = drift
        monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE")
        check = collect({"decoration:rounding": "12"})
        assert check.status == "unavailable"
        assert "1 unknown" in check.summary
        assert calls == []

    @pytest.mark.parametrize(
        "kind", ["missing", "foreign", "empty", "dangling", "fifo", "directory"]
    )
    def test_unowned_data_never_queried(self, drift, kind):
        path, _, calls, _ = drift
        if kind == "foreign":
            path.write_text("print('do not execute')")
        elif kind == "empty":
            path.touch()
        elif kind == "dangling":
            path.symlink_to(path.parent / "absent")
        elif kind == "fifo":
            os.mkfifo(path)
        elif kind == "directory":
            path.mkdir()
        snapshot = health.collect_snapshot(path)
        assert snapshot.checks[-1].status == "unavailable"
        assert calls == []

    def test_shared_deadline_preserves_partial_results(self, drift, monkeypatch):
        _, replies, calls, collect = drift
        clock = [100.0]
        monkeypatch.setattr(health.time, "monotonic", lambda: clock[0])
        original = health.run_bounded

        def run(command, **kwargs):
            if command[2] == "getoption":
                if len(calls) == 1:
                    assert kwargs["timeout"] == pytest.approx(0.75)
                    calls.append(command[3])
                    clock[0] += kwargs["timeout"]
                    raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                clock[0] += 1.25
            return original(command, **kwargs)

        monkeypatch.setattr(health, "run_bounded", run)
        replies["animations:enabled"] = {"option": "animations:enabled", "set": True, "bool": True}
        check = collect(
            {"animations:enabled": "true", "decoration:rounding": "12", "general:gaps_in": "5"}
        )
        assert len(calls) == 2
        assert "1 matching, 0 differing, 2 unknown" in check.summary
        assert "budget exhausted; not queried" in check.details[-1]

    def test_query_cap_and_details_omit_but_counts_cover_all(self, drift):
        _, replies, calls, collect = drift
        values = {}
        for key, option in health.OPTIONS_BY_KEY.items():
            if key.startswith("decoration:") and option.type in ("bool", "int", "float"):
                values[key] = "1"
                replies[key] = {
                    "option": key,
                    "set": True,
                    option.type: True if option.type == "bool" else 1,
                }
        assert len(values) > 32
        check = collect(values)
        assert len(calls) == 32
        assert check.status == "unknown"
        assert f"32 matching, 0 differing, {len(values) - 32} unknown" in check.summary
        assert len(check.details) == 16
        assert "omitted" in check.details[-1]

    def test_output_and_drift_share_one_read_even_if_file_changes(self, drift, monkeypatch):
        path, replies, calls, _ = drift
        original = health.read_owned_document
        reads = []

        def read(destination):
            document = original(destination)
            reads.append(destination)
            path.write_text(
                persistence.build_text({"decoration:rounding": "99"}, config.ConfigSections())
            )
            return document

        monkeypatch.setattr(health, "read_owned_document", read)
        replies["decoration:rounding"] = {"option": "decoration:rounding", "set": True, "int": 12}
        # This intentional fixture mutation is outside the no-write assertion in collect.
        path.write_text(
            persistence.build_text({"decoration:rounding": "12"}, config.ConfigSections())
        )
        snapshot = health.collect_snapshot(path)
        assert reads == [path]
        assert calls == ["decoration:rounding"]
        assert snapshot.checks[3].status == snapshot.checks[-1].status == "available"
        assert "saved='12'" in snapshot.checks[-1].details[1]

    def test_change_during_inspection_rejects_both_observations(self, drift, monkeypatch):
        path, _, calls, _ = drift
        path.write_text(
            persistence.build_text({"decoration:rounding": "12"}, config.ConfigSections())
        )
        original = os.fstat
        inspections = []

        def inspect(fd):
            info = original(fd)
            inspections.append(info)
            if len(inspections) == 1:
                path.write_text("changed during bounded inspection")
            return info

        monkeypatch.setattr(health.os, "fstat", inspect)
        snapshot = health.collect_snapshot(path)
        assert snapshot.checks[3].status == "failed"
        assert snapshot.checks[-1].status == "unavailable"
        assert "changed during inspection" in snapshot.checks[3].summary
        assert calls == []
