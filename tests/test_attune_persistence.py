"""Dotfiles-safe persistence boundary, without GTK or compositor startup."""

import base64
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hyprmod.core import config, persistence, recovery, restoration, settings
from hyprmod.core.focused_ui import ReviewSnapshot
from hyprmod.window import HyprModWindow


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(
        config, "_DEFAULT_MANAGED_BASE", tmp_path / "config" / "hypr" / "attune.lua"
    )
    monkeypatch.setattr(config, "HYPRMOD_DIR", tmp_path / "config" / "attune")
    monkeypatch.setattr(config, "_path_override", None)


@pytest.fixture
def destination(tmp_path):
    return tmp_path / "attune.lua"


def review(path, value="5", sections=None):
    resolved_path = persistence.resolve_target(path)
    sections = sections or config.ConfigSections()
    values = {"general:gaps_in": value}
    return (
        ReviewSnapshot(
            path,
            path.read_bytes().decode("utf-8") if path.exists() else "",
            persistence.build_text(values, sections),
            resolved_path,
        ),
        values,
        sections,
    )


class TestSafeSave:
    @pytest.mark.parametrize("evidence", ["registry", "journal"])
    @pytest.mark.parametrize("when", ["start", "under-lock", "before-replace"])
    def test_layout_guard_blocks_legacy_save(
        self, destination, tmp_path, monkeypatch, evidence, when
    ):
        persistence.persist_snapshot(review(destination)[0])
        snapshot = review(destination, "9")[0]
        previous = destination.read_bytes()
        archives = tmp_path / "state/attune/backups"
        archives.mkdir()
        archive = archives / "historical.lua"
        archive.write_bytes(b"untouched")
        before = archive.stat()

        def introduce():
            path = (
                tmp_path / "config/attune/installation.json"
                if evidence == "registry"
                else tmp_path / "state/attune/transactions/unknown"
            )
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.touch()

        if when == "start":
            introduce()
        elif when == "under-lock":
            flock = persistence.fcntl.flock

            def lock(*args):
                flock(*args)
                introduce()

            monkeypatch.setattr(persistence.fcntl, "flock", lock)
        else:
            atomic = persistence._atomic_write

            def write(path, content, **kwargs):
                if path == destination:
                    introduce()
                return atomic(path, content, **kwargs)

            monkeypatch.setattr(persistence, "_atomic_write", write)
        with pytest.raises(persistence.LayoutBlockedError, match="output not replaced") as error:
            persistence.persist_snapshot(snapshot)
        assert not error.value.output_replaced
        assert destination.read_bytes() == previous
        assert archive.stat() == before and archive.read_bytes() == b"untouched"

    @pytest.mark.parametrize("api", ["restore", "recovery"])
    @pytest.mark.parametrize("evidence", ["registry", "journal"])
    @pytest.mark.parametrize("when", ["start", "under-lock", "before-replace"])
    def test_m2_commits_block_new_scope_evidence(
        self, destination, tmp_path, monkeypatch, api, evidence, when
    ):
        persistence.persist_snapshot(review(destination)[0])
        persistence.persist_snapshot(review(destination, "9")[0])
        backups = tmp_path / "state/attune/backups"
        candidate = next(backups.glob("*.lua"))
        if api == "recovery":
            destination.write_text("-- foreign original\n")
            draft = recovery.prepare_recovery(destination, candidate.name)
        else:
            draft = restoration.prepare_restore(destination, candidate.name)
        previous = destination.read_bytes()
        preserved = tmp_path / "state/attune/preserved"
        preserved.mkdir(mode=0o700)
        historical = preserved / "historical.bin"
        historical.write_bytes(b"untouched preservation evidence\r\n")
        historical.chmod(0o600)
        before = {
            p: (p.read_bytes(), p.stat())
            for directory in (backups, preserved)
            for p in directory.iterdir()
        }
        path = (
            tmp_path / "config/attune/installation.json"
            if evidence == "registry"
            else tmp_path / "state/attune/transactions/unknown"
        )

        def introduce():
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(b"new scoped layout evidence\n")

        if when == "start":
            introduce()
        elif when == "under-lock":
            flock = persistence.fcntl.flock

            def lock(*args):
                flock(*args)
                introduce()

            monkeypatch.setattr(persistence.fcntl, "flock", lock)
        else:
            atomic = persistence._atomic_write

            def write(target, content, **kwargs):
                if target == destination:
                    introduce()
                return atomic(target, content, **kwargs)

            monkeypatch.setattr(persistence, "_atomic_write", write)
        failure = recovery.RecoveryFailure if api == "recovery" else restoration.RestoreFailure
        with pytest.raises(failure, match="Legacy write blocked") as error:
            if isinstance(draft, recovery.RecoveryDraft):
                recovery.commit_recovery(draft)
            else:
                restoration.commit_restore(draft)
        assert error.value.may_have_written is False
        assert isinstance(error.value.__cause__, persistence.LayoutBlockedError)
        assert error.value.__cause__.output_replaced is False
        assert destination.read_bytes() == previous
        assert path.read_bytes() == b"new scoped layout evidence\n"
        for archive, (raw, info) in before.items():
            assert archive.stat() == info
            assert archive.read_bytes() == raw
        expected = {p: raw for p, (raw, _) in before.items()}
        if when == "before-replace":
            directory, suffix = (preserved, ".bin") if api == "recovery" else (backups, ".lua")
            expected[directory / (draft.previous_sha256 + suffix)] = previous
        assert {
            p: p.read_bytes() for directory in (backups, preserved) for p in directory.iterdir()
        } == expected

    @pytest.mark.parametrize("api", ["reviewed", "snapshot", "restore"])
    @pytest.mark.parametrize("original", ["foreign Lua!", persistence.MARKER + "invalid JSON!"])
    def test_recovery_does_not_weaken_ordinary_guards(self, destination, api, original):
        destination.write_text(original)
        snapshot, values, sections = review(destination)
        with pytest.raises(ValueError):
            if api == "reviewed":
                persistence.persist_reviewed(snapshot, values, sections)
            elif api == "snapshot":
                persistence.persist_snapshot(snapshot)
            else:
                restoration.commit_restore(
                    restoration.RestoreDraft(
                        str(destination),
                        str(destination),
                        str(destination.parent),
                        "0" * 64 + ".lua",
                        original,
                        snapshot.proposed_text,
                        "0" * 64,
                        "0" * 64,
                        "",
                        0,
                        0,
                        "2026-10-27T00:00:00+00:00",
                    )
                )
        assert destination.read_text() == original

    def test_snapshot_api_uses_same_transaction(self, destination):
        snapshot, _, _ = review(destination)
        assert persistence.persist_snapshot(snapshot) is None
        previous = destination.read_bytes()
        snapshot, _, _ = review(destination, "9")
        backup = persistence.persist_snapshot(snapshot)
        assert backup is not None and backup.read_bytes() == previous
        assert destination.read_text() == snapshot.proposed_text

    @pytest.mark.parametrize("refuse_at", [1, 3, 4])
    def test_snapshot_source_guard_refuses_before_replacement(self, destination, refuse_at):
        persistence.persist_reviewed(*review(destination))
        snapshot, _, _ = review(destination, "9")
        calls = 0

        def guard():
            nonlocal calls
            calls += 1
            if calls == refuse_at:
                raise ValueError("Source changed")

        with pytest.raises(ValueError, match="Source changed"):
            persistence.persist_snapshot(snapshot, expected_source=guard)
        assert destination.read_text() == snapshot.saved_text

    def test_unbound_review_refused_without_writes(self, destination, tmp_path):
        snapshot, values, sections = review(destination)
        with pytest.raises(ValueError, match="not bound"):
            persistence.persist_reviewed(replace(snapshot, resolved_path=None), values, sections)
        assert not destination.exists()
        assert not (tmp_path / "state").exists()

    @pytest.mark.parametrize("parent_link", [False, True])
    @pytest.mark.parametrize("when", ["before_save", "under_lock"])
    def test_same_content_retarget_refused(
        self, destination, tmp_path, monkeypatch, parent_link, when
    ):
        original = tmp_path / "original" / "attune.lua"
        replacement = tmp_path / "replacement" / "attune.lua"
        previous = persistence.build_text({"general:gaps_in": "1"}, config.ConfigSections())
        for target in (original, replacement):
            target.parent.mkdir()
            target.write_text(previous)
        link = tmp_path / "hypr" if parent_link else destination
        link.symlink_to(original.parent if parent_link else original)
        path = link / "attune.lua" if parent_link else link
        snapshot, values, sections = review(path)
        assert snapshot.resolved_path == original

        def retarget():
            link.unlink()
            link.symlink_to(replacement.parent if parent_link else replacement)

        if when == "before_save":
            retarget()
        else:
            flock = persistence.fcntl.flock

            def lock_and_retarget(fd, operation):
                flock(fd, operation)
                retarget()

            monkeypatch.setattr(persistence.fcntl, "flock", lock_and_retarget)
        with pytest.raises(ValueError, match="Destination changed"):
            persistence.persist_reviewed(snapshot, values, sections)
        assert original.read_text() == previous
        assert replacement.read_text() == previous
        assert link.is_symlink()
        assert not (tmp_path / "state" / "attune" / "backups").exists()
        if when == "before_save":
            assert not (tmp_path / "state").exists()

    def test_empty_provisioned_file(self, destination):
        destination.touch()
        persistence.persist_reviewed(*review(destination))
        assert destination.read_text().startswith(persistence.MARKER)

    def test_new_file_and_backup(self, destination, tmp_path):
        assert persistence.persist_reviewed(*review(destination)) is None
        previous = destination.read_bytes()
        backup = persistence.persist_reviewed(*review(destination, "9"))
        assert backup is not None
        assert backup.parent == tmp_path / "state" / "attune" / "backups"
        assert backup.read_bytes() == previous
        assert "gaps_in = 9" in destination.read_text()
        assert persistence.read_document(destination.read_text())

    def test_file_symlink_preserved(self, destination, tmp_path):
        target = tmp_path / "repo" / "attune.lua"
        target.parent.mkdir()
        target.write_text(persistence.build_text({}, config.ConfigSections()))
        destination.symlink_to(target)
        backup = persistence.persist_reviewed(*review(destination))
        assert destination.is_symlink()
        assert "gaps_in = 5" in target.read_text()
        assert backup is not None
        assert not backup.is_relative_to(target.parent)

    def test_parent_symlink_preserved(self, destination, tmp_path):
        real = tmp_path / "repo"
        real.mkdir()
        link = tmp_path / "hypr"
        link.symlink_to(real, target_is_directory=True)
        persistence.persist_reviewed(*review(link / "attune.lua"))
        assert link.is_symlink()
        assert (real / "attune.lua").exists()

    @pytest.mark.parametrize("kind", ["dangling", "parent", "cycle", "foreign", "main", "hardlink"])
    def test_rejected_destinations(self, destination, tmp_path, kind):
        if kind == "dangling":
            destination.symlink_to(tmp_path / "missing" / "attune.lua")
        elif kind == "parent":
            parent = tmp_path / "dangling"
            parent.symlink_to(tmp_path / "missing", target_is_directory=True)
            destination = parent / "attune.lua"
        elif kind == "cycle":
            destination.symlink_to(destination)
        elif kind == "foreign":
            destination.write_text('os.execute("never execute me")\n')
        elif kind == "main":
            main = tmp_path / "hyprland.lua"
            main.write_text("-- main config\n")
            destination.symlink_to(main)
        else:
            foreign = tmp_path / "foreign.lua"
            foreign.write_text(persistence.build_text({}, config.ConfigSections()))
            os.link(foreign, destination)
        before = destination.read_bytes() if destination.exists() else None
        snapshot = ReviewSnapshot(destination, (before or b"").decode(), "", destination.absolute())
        proposed = persistence.build_text({}, config.ConfigSections())
        with pytest.raises((ValueError, OSError)):
            persistence.persist_reviewed(
                replace(snapshot, proposed_text=proposed), {}, config.ConfigSections()
            )
        if before is not None:
            assert destination.read_bytes() == before

    def test_main_config_symlink_to_attune_is_rejected(self, destination, tmp_path):
        destination.write_text(persistence.build_text({}, config.ConfigSections()))
        main = tmp_path / "config" / "hypr" / "hyprland.lua"
        main.parent.mkdir(parents=True)
        main.symlink_to(destination)
        with pytest.raises(ValueError, match="main config"):
            persistence.persist_reviewed(*review(destination))

    def test_atomic_failure_leaves_previous_and_no_temporary(self, destination, monkeypatch):
        persistence.persist_reviewed(*review(destination))
        previous = destination.read_bytes()
        real_replace = os.replace

        def fail_target(source, target):
            if target == destination:
                raise OSError("replacement failed")
            real_replace(source, target)

        monkeypatch.setattr(persistence.os, "replace", fail_target)
        with pytest.raises(OSError, match="replacement failed"):
            persistence.persist_reviewed(*review(destination, "9"))
        assert destination.read_bytes() == previous
        assert list(destination.parent.glob(".attune-*")) == []

    def test_backup_failure_does_not_write(self, destination, tmp_path):
        persistence.persist_reviewed(*review(destination))
        previous = destination.read_bytes()
        (tmp_path / "state" / "attune" / "backups").write_text("not a directory")
        with pytest.raises(OSError):
            persistence.persist_reviewed(*review(destination, "9"))
        assert destination.read_bytes() == previous

    def test_backup_inside_repository_refused(self, destination, tmp_path, monkeypatch):
        persistence.persist_reviewed(*review(destination))
        previous = destination.read_bytes()
        (tmp_path / ".git").mkdir()
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "in-repo-state"))
        with pytest.raises(ValueError, match="outside the dotfiles repository"):
            persistence.persist_reviewed(*review(destination, "9"))
        assert destination.read_bytes() == previous

    @pytest.mark.parametrize("change", ["draft", "disk", "review"])
    def test_stale_review_no_writes(self, destination, tmp_path, change):
        persistence.persist_reviewed(*review(destination))
        snapshot, values, sections = review(destination, "9")
        if change == "draft":
            values["general:gaps_in"] = "10"
        elif change == "disk":
            destination.write_text(persistence.build_text({"general:gaps_in": "7"}, sections))
        else:
            snapshot = replace(snapshot, proposed_text=snapshot.proposed_text + "-- edited\n")
        previous = destination.read_bytes()
        with pytest.raises(ValueError):
            persistence.persist_reviewed(snapshot, values, sections)
        assert destination.read_bytes() == previous
        assert not (tmp_path / "state" / "attune" / "backups").exists()


class TestValidation:
    @pytest.mark.parametrize("decoder", ["json", "base64"])
    def test_recursive_decoder_is_normalized_without_writes(
        self, destination, monkeypatch, decoder
    ):
        text = persistence.build_text({}, config.ConfigSections())
        destination.write_text(text)

        def recursive(*args, **kwargs):
            raise RecursionError("recursive external data")

        if decoder == "json":
            monkeypatch.setattr(persistence.json, "loads", recursive)
        else:
            monkeypatch.setattr(persistence.base64, "b64decode", recursive)
        with pytest.raises(ValueError, match="too deeply nested") as error:
            persistence.read_document(destination.read_text())
        assert isinstance(error.value.__cause__, RecursionError)
        assert destination.read_text() == text

    def test_deeply_nested_record_fails_closed(self):
        record = base64.b64encode(b"[" * 2000 + b"0" + b"]" * 2000).decode("ascii")
        text = persistence.MARKER + persistence.RECORD + record + "\n"
        with pytest.raises(ValueError):
            persistence.read_document(text)

    def test_non_decoder_recursion_is_not_suppressed(self, monkeypatch):
        text = persistence.build_text({}, config.ConfigSections())

        def bug(*args):
            raise RecursionError("programming bug")

        monkeypatch.setattr(persistence, "build_document", bug)
        with pytest.raises(RecursionError, match="programming bug"):
            persistence.read_document(text)

    def test_default_destination_is_lua_even_in_legacy_mode(self, monkeypatch):
        monkeypatch.setattr(config, "is_lua_mode", lambda: False)
        monkeypatch.setattr(config, "_path_override", None)
        assert config.default_managed_path().name == "attune.lua"
        assert config.managed_path() == config.default_managed_path()
        assert config.HYPRMOD_DIR.name == "attune"

    def test_nonfinite_scalar_refused(self):
        with pytest.raises(ValueError, match="Non-finite"):
            persistence.build_text({"decoration:active_opacity": "1e999"}, config.ConfigSections())

    def test_lua_fallback_compiles_without_execution(self, tmp_path, monkeypatch):
        which = persistence.shutil.which
        if which("lua") is None:
            pytest.skip("lua fallback not installed")
        monkeypatch.setattr(
            persistence.shutil, "which", lambda name: None if name == "luac" else which(name)
        )
        sentinel = tmp_path / "must-not-exist"
        init = f'io.open("{sentinel}", "w"):close()'
        for variable in ("LUA_INIT", *(f"LUA_INIT_5_{minor}" for minor in range(1, 6))):
            monkeypatch.setenv(variable, init)
        persistence.validate_lua(f'io.open("{sentinel}", "w"):close()')
        assert not sentinel.exists()
        with pytest.raises(ValueError, match="syntax validation failed"):
            persistence.validate_lua("this is not valid Lua!")
        assert not sentinel.exists()

    @pytest.mark.parametrize("flag", ["0", "false", "off", "no"])
    def test_disabled_animation_two_fields_round_trip_and_save(self, destination, flag):
        sections = config.ConfigSections(animations=[f"animation = windows, {flag}"])
        snapshot, values, sections = review(destination, sections=sections)
        assert "enabled = false" in snapshot.proposed_text
        persistence.read_document(snapshot.proposed_text)
        persistence.persist_reviewed(snapshot, values, sections)
        assert config.read_all_sections(destination)[1]["animation"] == [
            f"animation = windows, {flag}"
        ]

    @pytest.mark.parametrize(
        "definition",
        [
            "windows",
            "windows, 1",
            "windows, true",
            "windows, maybe",
            "windows, 0, 5",
            "windows, maybe, 5, default",
            "windows, 2, 5, default",
            "windows, , 5, default",
            ", 0",
            "windows, 1, , default",
            "windows, 1, 5, ",
            "windows, 1, 5, default, slide, extra",
        ],
    )
    def test_malformed_animation_refused(self, definition):
        with pytest.raises(ValueError, match="Invalid animation"):
            persistence.build_text(
                {}, config.ConfigSections(animations=[f"animation = {definition}"])
            )

    @pytest.mark.parametrize("flag", ["0", "1", "false", "true", "off", "on", "no", "yes"])
    def test_full_animation_requires_recognized_boolean(self, flag):
        text = persistence.build_text(
            {}, config.ConfigSections(animations=[f"animation = windows, {flag}, 5, default"])
        )
        persistence.read_document(text)
        persistence.validate_lua(text)

    @pytest.mark.parametrize("key", ["exec", "input:kb_layout", "general:layout", "plugin:foo"])
    def test_unsupported_options(self, key):
        with pytest.raises(ValueError, match="Unsupported Attune option"):
            persistence.build_text({key: "5"}, config.ConfigSections())

    @pytest.mark.parametrize("section", ["binds", "exec_", "env", "plugins", "workspaces"])
    def test_unsupported_sections_even_empty(self, section):
        sections = config.ConfigSections()
        setattr(sections, section, [])
        with pytest.raises(ValueError, match="Unsupported Attune section"):
            persistence.build_text({}, sections)

    @pytest.mark.parametrize("line", ["exec = bad", "monitor = DP-1, disable\nexec = bad"])
    def test_section_directive_injection(self, line):
        with pytest.raises(ValueError):
            persistence.build_text({}, config.ConfigSections(monitors=[line]))

    def test_all_supported_output_reparses_and_compiles(self):
        sections = config.ConfigSections(
            monitors=["monitor = DP-1, preferred, auto, 1"],
            animations=["animation = windows, 1, 5, smooth"],
            beziers=["bezier = smooth, 0.1, 0.2, 0.3, 1"],
        )
        values = {
            "general:gaps_in": "5",
            "general:col.active_border": "rgba(ff0000ff) rgba(00ff00ff) 45deg",
            "decoration:rounding": "8",
            "animations:enabled": "true",
            "decoration:screen_shader": 'quote" and backslash\\ and os.execute("no")',
        }
        text = persistence.build_text(values, sections)
        persistence.read_document(text)
        persistence.validate_lua(text)
        assert text.index("hl.curve") < text.index("hl.animation")

    def test_owned_but_edited_file_refused(self, destination):
        persistence.persist_reviewed(*review(destination))
        destination.write_text(destination.read_text() + 'os.execute("no")\n')
        with pytest.raises(ValueError, match="edited outside"):
            persistence.persist_reviewed(*review(destination, "9"))

    def test_missing_validator_fails_closed(self, destination, monkeypatch):
        monkeypatch.setattr(persistence.shutil, "which", lambda _: None)
        with pytest.raises(ValueError, match="Install lua or luac"):
            persistence.persist_reviewed(*review(destination))
        assert not destination.exists()

    def test_syntax_failure_fails_closed(self, destination, monkeypatch):
        monkeypatch.setattr(
            persistence.subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess([], 1, stderr="syntax error"),
        )
        with pytest.raises(ValueError, match="syntax validation failed"):
            persistence.persist_reviewed(*review(destination))
        assert not destination.exists()

    def test_real_compile_does_not_execute(self, tmp_path):
        sentinel = tmp_path / "must-not-exist"
        persistence.validate_lua(f'io.open("{sentinel}", "w"):close()')
        assert not sentinel.exists()
        with pytest.raises(ValueError, match="syntax validation failed"):
            persistence.validate_lua("this is not valid Lua!")

    def test_read_attune_does_not_use_executing_reader(self, destination, monkeypatch):
        persistence.persist_reviewed(*review(destination))
        reader = MagicMock(side_effect=AssertionError("must not execute Lua"))
        monkeypatch.setattr(config, "load_any", reader)
        assert config.read_all_sections(destination)[0] == {"general:gaps_in": "5"}
        reader.assert_not_called()

    def test_settings_ignore_legacy_path_without_mutation(self, monkeypatch):
        store = MagicMock()
        store.get_string.return_value = "/arbitrary/hyprland.conf"
        monkeypatch.setattr(config, "_path_override", Path("/arbitrary/hyprland.conf"))
        settings.apply_saved_config_path(store)
        assert config.managed_path().name == "attune.lua"
        store.get_string.assert_not_called()
        store.set_string.assert_not_called()

    def test_missing_settings_preserve_explicit_generic_override(self, monkeypatch):
        path = Path("/generic/test.conf")
        monkeypatch.setattr(config, "_path_override", path)
        settings.apply_saved_config_path(None)
        assert config.managed_path() == path


class TestWindowPersistence:
    def test_review_binds_symlink_target(self, destination, tmp_path, monkeypatch):
        first = tmp_path / "first" / "attune.lua"
        second = tmp_path / "second" / "attune.lua"
        for path in (first, second):
            path.parent.mkdir()
            path.write_text(persistence.build_text({}, config.ConfigSections()))
        destination.symlink_to(first)
        monkeypatch.setattr(config, "managed_path", lambda: destination)
        win = MagicMock()
        win.app_state.get_all_live_values.return_value = {"general:gaps_in": "5"}
        win.collect_save_sections.return_value = config.ConfigSections()
        before = HyprModWindow.review_snapshot(win)
        destination.unlink()
        destination.symlink_to(second)
        after = HyprModWindow.review_snapshot(win)
        assert before.path == after.path
        assert before.saved_text == after.saved_text
        assert before.proposed_text == after.proposed_text
        assert before.resolved_path == first
        assert after.resolved_path == second
        assert before != after

    def test_retarget_during_review_refused(self, destination, tmp_path, monkeypatch):
        first = tmp_path / "first" / "attune.lua"
        second = tmp_path / "second" / "attune.lua"
        for path in (first, second):
            path.parent.mkdir()
            path.touch()
        destination.symlink_to(first)
        monkeypatch.setattr(config, "managed_path", lambda: destination)
        text = persistence.build_text({}, config.ConfigSections())

        def build_and_retarget(*args):
            destination.unlink()
            destination.symlink_to(second)
            return text

        monkeypatch.setattr(persistence, "build_text", build_and_retarget)
        with pytest.raises(ValueError, match="Destination changed during review"):
            HyprModWindow.review_snapshot(MagicMock())

    def test_review_uses_restricted_serializer(self, destination, monkeypatch):
        monkeypatch.setattr(config, "managed_path", lambda: destination)
        win = MagicMock()
        win.app_state.get_all_live_values.return_value = {"general:gaps_in": "5"}
        win.collect_save_sections.return_value = config.ConfigSections()
        snapshot = HyprModWindow.review_snapshot(win)
        assert snapshot == review(destination)[0]

    @pytest.mark.parametrize("failure", [False, True])
    def test_reviewed_save_uses_persistence_before_marking_saved(
        self, destination, monkeypatch, failure
    ):
        snapshot, values, sections = review(destination)
        win = MagicMock()
        win._page_stack.get_visible_child_name.return_value = "pending"
        win._monitors_page.is_confirm_pending.return_value = False
        win.review_snapshot.return_value = snapshot
        win.app_state.get_all_live_values.return_value = values
        win.collect_save_sections.return_value = sections
        persist = MagicMock(return_value=destination.parent / "state/attune/backups/test.lua")
        if failure:
            persist.side_effect = ValueError("unsafe")
        monkeypatch.setattr(persistence, "persist_reviewed", persist)
        HyprModWindow.save_reviewed(win, snapshot)
        persist.assert_called_once_with(snapshot, values, sections)
        if failure:
            win._perform_save.assert_not_called()
            win._banner.show_saved.assert_not_called()
        else:
            win._perform_save.assert_called_once_with()
            win._banner.show_saved.assert_called_once_with()
            assert "Backup:" in win.show_toast.call_args.args[0]
