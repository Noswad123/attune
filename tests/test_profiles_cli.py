"""Tests for the headless ``hyprmod profile`` CLI."""

from pathlib import Path

import pytest
from hyprland_state import HyprlandState

from hyprmod import cli
from hyprmod.core import profiles


@pytest.fixture
def profiles_env(tmp_path, monkeypatch, gui_conf_tmp):
    """Isolate profile storage and stub the IPC/GSettings the CLI touches.

    Returns the managed ``.conf`` path (from ``gui_conf_tmp``) so tests can
    seed snapshot content. ``HyprlandState`` is forced offline so activation
    exercises the file-writing path without talking to a live compositor.
    """
    monkeypatch.setattr(profiles, "_PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(profiles, "_ACTIVE_FILE", tmp_path / "active_profile")
    monkeypatch.setattr(cli, "open_settings", lambda: None)
    monkeypatch.setattr(cli, "HyprlandState", lambda: HyprlandState(offline=True))
    # HyprlandState loads the user's top-level config on construction; in a
    # real session it always exists, so give the sandbox an empty one.
    (tmp_path / "hyprland.conf").touch()
    return gui_conf_tmp


def _seed_profile(managed: Path, content: str, name: str) -> str:
    managed.write_text(content)
    return profiles.save_current_as(name)


def test_find_by_name_is_case_insensitive():
    work = {"id": "x", "name": "Work"}
    assert profiles.find_by_name([work], "work") == work
    assert profiles.find_by_name([work], "  WORK  ") == work


def test_find_by_name_missing_returns_none():
    assert profiles.find_by_name([{"id": "x", "name": "Work"}], "nope") is None


def test_apply_switches_managed_file_and_active(profiles_env):
    managed = profiles_env
    work_id = _seed_profile(managed, "general:gaps_in = 5\n", "Work")
    _seed_profile(managed, "general:gaps_in = 20\n", "Gaming")

    # Gaming is active and on disk after the second save.
    assert profiles.get_active_id() != work_id

    assert cli.run(["profile", "apply", "work"]) == 0

    assert managed.read_text() == "general:gaps_in = 5\n"
    assert profiles.get_active_id() == work_id


def test_apply_unknown_name_errors(profiles_env, capsys):
    _seed_profile(profiles_env, "general:gaps_in = 5\n", "Work")
    assert cli.run(["profile", "apply", "ghost"]) == 1
    assert "no profile named" in capsys.readouterr().err


def test_apply_reports_canonical_name(profiles_env, capsys):
    _seed_profile(profiles_env, "general:gaps_in = 5\n", "Work")
    assert cli.run(["profile", "apply", "work"]) == 0  # lowercase input
    assert "Switched to 'Work'" in capsys.readouterr().out  # stored casing echoed


def test_list_marks_active_profile(profiles_env, capsys):
    _seed_profile(profiles_env, "general:gaps_in = 5\n", "Work")
    _seed_profile(profiles_env, "general:gaps_in = 20\n", "Gaming")  # now active

    assert cli.run(["profile", "list"]) == 0
    out = capsys.readouterr().out
    assert "* Gaming" in out
    assert "  Work" in out


def test_list_empty(profiles_env, capsys):
    assert cli.run(["profile", "list"]) == 0
    assert "No profiles saved." in capsys.readouterr().out


def test_list_is_alphabetical(profiles_env, capsys):
    _seed_profile(profiles_env, "g = 1\n", "Work")
    _seed_profile(profiles_env, "g = 2\n", "Alpha")
    cli.run(["profile", "list"])
    lines = [line.lstrip("* ").strip() for line in capsys.readouterr().out.splitlines()]
    assert lines == ["Alpha", "Work"]


# ── adjacent_id (pure ordering logic) ──

_THREE = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}, {"id": "c", "name": "C"}]


def test_adjacent_id_moves_and_wraps():
    assert profiles.adjacent_id(_THREE, "a", forward=True) == "b"
    assert profiles.adjacent_id(_THREE, "c", forward=True) == "a"  # wrap forward
    assert profiles.adjacent_id(_THREE, "a", forward=False) == "c"  # wrap backward
    assert profiles.adjacent_id(_THREE, "b", forward=False) == "a"


def test_adjacent_id_without_active_starts_at_an_end():
    assert profiles.adjacent_id(_THREE, None, forward=True) == "a"
    assert profiles.adjacent_id(_THREE, None, forward=False) == "c"
    assert profiles.adjacent_id(_THREE, "stale", forward=True) == "a"


def test_adjacent_id_single_returns_itself():
    assert profiles.adjacent_id([{"id": "a", "name": "A"}], "a", forward=True) == "a"


def test_adjacent_id_empty_returns_none():
    assert profiles.adjacent_id([], None, forward=True) is None


# ── cycle commands ──


def test_next_and_previous_move_in_order(profiles_env):
    managed = profiles_env
    _seed_profile(managed, "g = 1\n", "Alpha")
    _seed_profile(managed, "g = 2\n", "Beta")
    _seed_profile(managed, "g = 3\n", "Gamma")

    cli.run(["profile", "apply", "Beta"])  # active = Beta (middle)
    assert cli.run(["profile", "next"]) == 0
    assert managed.read_text() == "g = 3\n"  # Gamma

    cli.run(["profile", "apply", "Beta"])
    assert cli.run(["profile", "prev"]) == 0  # alias resolves to previous
    assert managed.read_text() == "g = 1\n"  # Alpha


def test_next_wraps_around(profiles_env):
    managed = profiles_env
    _seed_profile(managed, "g = 1\n", "Alpha")
    _seed_profile(managed, "g = 2\n", "Beta")  # active = Beta (last)
    assert cli.run(["profile", "next"]) == 0
    assert managed.read_text() == "g = 1\n"  # wrapped to Alpha


def test_cycle_with_no_profiles_errors(profiles_env, capsys):
    assert cli.run(["profile", "next"]) == 1
    assert "no profiles" in capsys.readouterr().err


def test_cycle_single_profile_is_noop(profiles_env, capsys):
    _seed_profile(profiles_env, "g = 1\n", "Solo")  # active = Solo
    assert cli.run(["profile", "next"]) == 0
    assert "only profile" in capsys.readouterr().out


# ── unknown commands ──


@pytest.mark.parametrize("argv", [["profilee", "prev"], ["profile", "bogus"], ["nonsense"]])
def test_unknown_command_exits_with_error(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(argv)
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_main_rejects_dormant_profile_cli(monkeypatch, capsys):
    """Attune never exposes the retained upstream profile write path."""
    from hyprmod import main as main_module

    monkeypatch.setattr("sys.argv", ["attune", "profile", "prev"])
    assert main_module.main() == 2
    assert "no profile CLI" in capsys.readouterr().err
