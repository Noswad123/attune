"""Dedicated bindings persistence, exclusively against explicit temporary paths."""

import base64
import json
import os
import stat
import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from hyprmod.core import bindings, persistence


@pytest.fixture
def roots(tmp_path):
    config = tmp_path / "config"
    (config / "hypr").mkdir(parents=True)
    return config, tmp_path / "state"


def draft(roots, lines=("bind = SUPER, Q, killactive",)):
    baseline = bindings.observe(*roots)
    config = bindings.BindingsConfig(lines)
    return bindings.prepare_review(baseline, config), config


class TestCodec:
    def test_number_key_and_workspace_dispatch(self):
        config = bindings.BindingsConfig(("bind = SUPER, 1, workspace, 1",))
        assert bindings.read_text(bindings.build_text(config)) == config

    @pytest.mark.parametrize("kind", ["bind", "binde", "bindl", "bindr", "bindn"])
    @pytest.mark.parametrize("dispatcher,method", [("exec", "exec_cmd"), ("execr", "exec_raw")])
    def test_flags_commands_and_roundtrip(self, kind, dispatcher, method, tmp_path):
        sentinel = tmp_path / "must-not-exist"
        command = f"""sh -c 'echo "$HOME, $USER"; touch {sentinel}' # cafe"""
        line = f"{kind} = CTRL SUPER, Return, {dispatcher}, {command}"
        config = bindings.BindingsConfig((line,))
        text = bindings.build_text(config)
        assert bindings.read_text(text) == config
        assert bindings.validate_line(line).arg == command
        body = text.split("\n", 2)[2]
        assert f"hl.dsp.{method}({json.dumps(command)})" in body
        assert not sentinel.exists()

    @pytest.mark.parametrize("dispatcher,method", [("exec", "exec_cmd"), ("execr", "exec_raw")])
    @pytest.mark.parametrize(
        "command",
        [
            'printf "%s,%s" "$HOME" "a\\b"; notify-send "done"',
            'echo "$USER" && echo done || echo failed | wc -c',
            "hyprctl --instance other monitors",
        ],
    )
    def test_ordinary_commands_are_literal_in_emitted_body(self, dispatcher, method, command):
        config = bindings.BindingsConfig((f"bind = SUPER, T, {dispatcher}, {command}",))
        body = bindings.build_text(config).split("\n", 2)[2]
        assert body == f'hl.bind("SUPER + T", hl.dsp.{method}({json.dumps(command)}))\n'

    @pytest.mark.parametrize(
        "command",
        [
            "hyprctl --instance other dispatch killactive",
            "hyprctl keyword general:gaps_in 5; notify-send done",
            'hyprctl dispatch exec echo "$HOME, hello"',
        ],
    )
    def test_exec_migration_rewrites_refused_not_silently_coerced(self, command):
        line = f"bind = SUPER, T, exec, {command}"
        with pytest.raises(ValueError, match="explicit direct action, or Raw command"):
            bindings.validate_line(line)
        # Even an exact old metadata/body pair is no longer admissible.
        record = json.dumps({"version": 1, "binds": [line]}, sort_keys=True, separators=(",", ":"))
        text = (
            persistence.MARKER
            + bindings.RECORD
            + base64.b64encode(record.encode("ascii")).decode("ascii")
            + "\n"
            + bindings.keyword_to_lua("bind", line.partition(" = ")[2])
            + "\n"
        )
        with pytest.raises(ValueError, match="literal emission"):
            bindings.read_text(text)
        raw = bindings.BindingsConfig((f"bind = SUPER, T, execr, {command}",))
        body = bindings.build_text(raw).split("\n", 2)[2]
        assert body == f'hl.bind("SUPER + T", hl.dsp.exec_raw({json.dumps(command)}))\n'

    @pytest.mark.parametrize("dispatcher", ["exec", "execr"])
    @pytest.mark.parametrize(
        "emitted",
        [
            'hl.dispatch(function() return "echo original" end)',
            'hl.dispatch(hl.dsp.exec_cmd("echo changed"))',
            'hl.dispatch(hl.dsp.exec_raw("echo changed"))',
            'hl.dispatch(hl.dsp.future_exec("echo original"))',
            r'hl.dispatch(hl.dsp.exec_cmd("echo \zoriginal"))',
        ],
    )
    def test_unproven_public_emission_fails_closed(self, monkeypatch, dispatcher, emitted):
        monkeypatch.setattr(bindings, "dispatch_to_lua", lambda *args: emitted)
        with pytest.raises(ValueError, match="literal emission"):
            bindings.validate_line(f"bind = SUPER, T, {dispatcher}, echo original")

    def test_unicode_and_alias_normalization(self):
        config = bindings.BindingsConfig(("bind = SUPER CONTROL, T, exec, echo caf\u00e9",))
        assert config.lines == ("bind = CTRL SUPER, T, exec, echo caf\u00e9",)
        assert bindings.read_text(bindings.build_text(config)) == config
        with pytest.raises(ValueError, match="Duplicate keyboard"):
            bindings.BindingsConfig(("bind = CONTROL, T, exec, one", "bindr = CTRL, t, exec, two"))

    @pytest.mark.parametrize(
        "line",
        [
            "bindm = SUPER, mouse:272, movewindow",
            "bindel = SUPER, T, exec, x",
            "bindd = SUPER, T, label, exec, x",
            "unbind = SUPER, T",
            "bind = SUPER, code:12, exec, x",
            "bind = SUPER, catchall, exec, x",
            "bind = SUPER, mouse_up, exec, x",
            "bind = SUPER, T, submap, resize",
            "bind = SUPER, T, custom_callback, x",
            "bind = SUPER, T, exec, x\n",
            "bind = SUPER, T, exec, x\r",
            "bind = SUPER, T, exec, x\x00",
            "bind = SUPER, T, exec, x\u202e",
            "bind = SUPER, T, killactive,",
            "bind = SUPER, T, resizeactive, nonsense",
            "bind = SUPER, T, killactive, address:0x123",
            "bind = UNKNOWN, T, exec, x",
        ],
    )
    def test_refuses_lossy_unsupported_and_controls(self, line):
        with pytest.raises(ValueError):
            bindings.validate_line(line)

    def test_foreign_edited_and_unknown_version(self):
        text = bindings.build_text(bindings.BindingsConfig())
        token = base64.b64encode(json.dumps({"version": 2, "binds": []}).encode()).decode()
        for bad in (
            "",
            "hl.bind('x')\n",
            text + "-- edited\n",
            persistence.MARKER + bindings.RECORD + token + "\n",
        ):
            with pytest.raises(ValueError):
                bindings.read_text(bad)

    def test_limits_and_immutable_input(self):
        with pytest.raises(ValueError):
            bindings.BindingsConfig(["bind = SUPER, T, exec, x"])  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            bindings.BindingsConfig(tuple(f"bind = SUPER, F{n}, exec, x" for n in range(1001)))
        with pytest.raises(ValueError):
            bindings.build_text(
                bindings.BindingsConfig(
                    ("bind = SUPER, T, exec, " + "x" * (bindings.MAX_INPUT_BYTES - 100),)
                )
            )
        with pytest.raises(ValueError):
            bindings.BindingsBaseline.from_json("[" * 25)


class TestPersistence:
    @pytest.mark.parametrize("empty", [False, True])
    def test_first_repeat_noop_delete_reopen(self, roots, empty):
        target = roots[0] / "hypr" / bindings.BASENAME
        if empty:
            target.touch(mode=0o600)
        review, config = draft(roots)
        assert review.baseline.status == ("empty" if empty else "absent")
        assert not roots[1].exists()
        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "saved", result.error
        assert result.baseline == bindings.observe(*roots)
        if result.baseline is None:
            pytest.fail("Saved result lacks verified baseline")
        assert result.baseline.text == review.proposed_text
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        review2, config2 = draft(roots)
        before = target.stat()
        noop = bindings.persist_reviewed(review2, config2)
        assert noop.outcome == "no-op", noop.error
        assert target.stat() == before
        deletion, blank = draft(roots, ())
        removed = bindings.persist_reviewed(deletion, blank)
        assert removed.outcome == "saved", removed.error
        assert bindings.observe(*roots).config == blank
        if removed.backup_path is None:
            pytest.fail("Replacement lacks prior backup")
        backup = Path(removed.backup_path)
        assert backup.read_text() == review.proposed_text
        assert backup.name == review2.baseline.sha256 + ".lua"
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600
        for directory in (roots[1] / "attune", backup.parent):
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700

    def test_stow_symlink_preserved_and_unrelated_files_untouched(self, roots, tmp_path):
        stow = tmp_path / "dotfiles"
        stow.mkdir()
        (stow / ".git").mkdir()
        output = stow / bindings.BASENAME
        output.write_text(bindings.build_text(bindings.BindingsConfig()))
        target = roots[0] / "hypr" / bindings.BASENAME
        target.symlink_to(output)
        protected = [
            roots[0] / "hypr" / name
            for name in (
                "attune.lua",
                "hyprland.lua",
                "attune-appearance.lua",
                "attune-displays.lua",
            )
        ]
        for path in protected:
            path.write_text("literal fixture, never parsed\n")
        original = [(p.read_bytes(), p.stat()) for p in protected]
        review, config = draft(roots)
        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "saved", result.error
        assert target.is_symlink()
        assert [(p.read_bytes(), p.stat()) for p in protected] == original

    @pytest.mark.parametrize("mode", ["legacy", "pair"])
    def test_independent_of_visual_mode_registry_and_journal(self, roots, mode):
        config, state = roots
        visual = config / "hypr/attune.lua"
        visual.write_bytes(
            (Path(__file__).parent / "fixtures/canonical_v1/combined.lua").read_bytes()
        )
        protected = [visual]
        if mode == "pair":
            registry = config / "attune/installation.json"
            registry.parent.mkdir()
            registry.write_text('{"fixture":"not interpreted by bindings"}\n')
            journal = state / "attune/transactions/fixture/journal.json"
            journal.parent.mkdir(parents=True)
            (state / "attune").chmod(0o700)
            journal.write_text("literal existing journal fixture\n")
            protected.extend([registry, journal])
            for name in ("attune-appearance.lua", "attune-displays.lua"):
                path = config / "hypr" / name
                path.write_text("-- literal scoped fixture: never interpreted\n")
                protected.append(path)
        before = [(p.read_bytes(), p.stat()) for p in protected]
        review, proposed = draft(roots)
        result = bindings.persist_reviewed(review, proposed)
        assert result.outcome == "saved", result.error
        assert [(p.read_bytes(), p.stat()) for p in protected] == before

    @pytest.mark.parametrize("kind", ["foreign", "unknown", "main", "hardlink", "dangling"])
    def test_unsafe_observation_refuses_without_state(self, roots, kind):
        target = roots[0] / "hypr" / bindings.BASENAME
        if kind in {"foreign", "unknown"}:
            target.write_text(
                "-- foreign\n"
                if kind == "foreign"
                else persistence.MARKER + "-- Attune bindings data v9: e30=\n"
            )
        elif kind == "main":
            main = target.with_name("hyprland.lua")
            main.write_text("main config")
            target.symlink_to(main)
        elif kind == "hardlink":
            main = target.with_name("attune.lua")
            main.write_text("prior")
            os.link(main, target)
        else:
            target.symlink_to(target.parent / "missing" / bindings.BASENAME)
        with pytest.raises(ValueError):
            bindings.observe(*roots)
        assert not roots[1].exists()

    def test_stale_source_and_draft_clean_failure(self, roots):
        review, config = draft(roots)
        wrong = bindings.persist_reviewed(review, bindings.BindingsConfig())
        assert wrong.outcome == "failed" and not wrong.may_have_written
        target = Path(review.baseline.lexical_path)
        target.write_text(bindings.build_text(bindings.BindingsConfig()))
        stale = bindings.persist_reviewed(review, config)
        assert stale.outcome == "failed" and not stale.may_have_written
        assert stale.baseline is None
        assert not roots[1].exists()

    def test_same_bytes_new_inode_requires_fresh_review(self, roots):
        target = roots[0] / "hypr" / bindings.BASENAME
        target.write_text(bindings.build_text(bindings.BindingsConfig()))
        review, config = draft(roots)
        alternate = target.with_suffix(".new")
        alternate.write_bytes(target.read_bytes())
        alternate.replace(target)
        with pytest.raises(ValueError, match="changed"):
            bindings.prepare_review(review.baseline, config)
        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written

    def test_change_during_lock_acquisition_refuses(self, roots, monkeypatch):
        review, config = draft(roots)
        original = bindings.fcntl.flock

        def flock(fd, operation):
            original(fd, operation)
            Path(review.baseline.lexical_path).touch(mode=0o600)

        monkeypatch.setattr(bindings.fcntl, "flock", flock)
        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert Path(review.baseline.lexical_path).read_bytes() == b""

    def test_compile_refusal_cannot_publish(self, roots, monkeypatch):
        review, config = draft(roots)

        def refuse(text):
            raise ValueError("compiler refused")

        monkeypatch.setattr(persistence, "validate_lua", refuse)
        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert not Path(review.baseline.lexical_path).exists()

    def test_retarget_at_final_stage_refuses(self, roots, tmp_path, monkeypatch):
        review, config = draft(roots)
        original = persistence._atomic_write
        replacement = tmp_path / "elsewhere"
        replacement.mkdir()
        other = replacement / bindings.BASENAME
        other.write_text(bindings.build_text(bindings.BindingsConfig()))

        def changed(path, content, **kwargs):
            Path(review.baseline.lexical_path).symlink_to(other)
            original(path, content, **kwargs)

        monkeypatch.setattr(persistence, "_atomic_write", changed)
        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert other.read_text() != review.proposed_text

    @pytest.mark.parametrize("late", [False, True])
    def test_write_and_late_fsync_failure_flags(self, roots, monkeypatch, late):
        review, config = draft(roots)
        original = os.fsync
        calls = 0

        def fsync(fd):
            nonlocal calls
            calls += 1
            if calls == (2 if late else 1):
                raise OSError("fsync failure")
            original(fd)

        monkeypatch.setattr(os, "fsync", fsync)
        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "failed"
        assert result.may_have_written is late
        assert result.baseline is None
        assert Path(review.baseline.lexical_path).exists() is late

    def test_postread_failure_is_uncertain(self, roots, monkeypatch):
        review, config = draft(roots)
        original = bindings.observe

        def observe(*args):
            current = original(*args)
            if current.status == "owned":
                raise ValueError("post-read unavailable")
            return current

        monkeypatch.setattr(bindings, "observe", observe)
        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "failed" and result.may_have_written
        assert result.baseline is None

    def test_foreign_stage_is_never_cleaned(self, roots, monkeypatch):
        review, config = draft(roots)
        foreign = roots[0] / "hypr/.attune-foreign"
        foreign.write_text("not our scratch")
        original = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name.startswith(".attune-") and path != foreign:
                raise OSError("scratch cleanup failed")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
        result = bindings.persist_reviewed(review, config)
        # Exclusive publication leaves two links if cleanup fails. Never adopt it.
        assert result.outcome == "failed" and result.may_have_written
        assert result.baseline is None
        assert foreign.read_text() == "not our scratch"

    @pytest.mark.parametrize("unsafe", ["body", "mode", "hardlink"])
    def test_existing_backup_collision_fails_before_lock(self, roots, unsafe):
        target = roots[0] / "hypr" / bindings.BASENAME
        target.write_text(bindings.build_text(bindings.BindingsConfig()))
        review, config = draft(roots)
        backups = roots[1] / "attune/bindings-backups"
        backups.mkdir(parents=True, mode=0o700)
        backups.parent.chmod(0o700)
        backup = backups / (review.baseline.sha256 + ".lua")
        backup.write_text("wrong" if unsafe == "body" else target.read_text())
        backup.chmod(0o644 if unsafe == "mode" else 0o600)
        if unsafe == "hardlink":
            os.link(backup, backups / "alias")
        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert not (backups.parent / "bindings.lock").exists()
        assert target.read_text() == review.baseline.text

    @pytest.mark.parametrize("unsafe", ["git", "permissions", "locklink", "backuplink"])
    def test_state_collisions_refuse(self, roots, unsafe):
        target = roots[0] / "hypr" / bindings.BASENAME
        target.write_text(bindings.build_text(bindings.BindingsConfig()))
        review, config = draft(roots)
        state = roots[1] / "attune"
        state.mkdir(parents=True, mode=0o700)
        if unsafe == "git":
            (roots[1] / ".git").mkdir()
        elif unsafe == "permissions":
            state.chmod(0o755)
        elif unsafe == "locklink":
            (state / "bindings.lock").symlink_to(target)
        else:
            backups = state / "bindings-backups"
            backups.mkdir(mode=0o700)
            (backups / (review.baseline.sha256 + ".lua")).symlink_to(target)
        before = target.read_bytes()
        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert target.read_bytes() == before

    @pytest.mark.parametrize("marker_kind", ["directory", "worktree-file"])
    def test_backup_root_git_refused_before_lock_or_evidence(self, roots, marker_kind):
        target = roots[0] / "hypr" / bindings.BASENAME
        target.write_text(bindings.build_text(bindings.BindingsConfig()))
        review, config = draft(roots)
        backups = roots[1] / "attune/bindings-backups"
        backups.mkdir(parents=True, mode=0o700)
        backups.parent.chmod(0o700)
        marker = backups / ".git"
        if marker_kind == "directory":
            marker.mkdir()
        else:
            marker.write_text("gitdir: nonexistent-worktree-metadata\n")
        before = target.read_bytes(), target.stat(), marker.stat()
        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.baseline is None and result.backup_path is None
        assert result.error is not None and "outside Git" in result.error
        assert (target.read_bytes(), target.stat(), marker.stat()) == before
        assert set(backups.iterdir()) == {marker}
        assert set(backups.parent.iterdir()) == {backups}

    @pytest.mark.parametrize("marker_kind", ["directory", "worktree-file"])
    @pytest.mark.parametrize("when", ["under-lock", "final-guard", "post-publication"])
    def test_backup_root_git_races_refuse_with_honest_flags(
        self, roots, monkeypatch, marker_kind, when
    ):
        review, config = draft(roots)
        target = Path(review.baseline.lexical_path)
        backups = roots[1] / "attune/bindings-backups"
        backups.mkdir(parents=True, mode=0o700)
        backups.parent.chmod(0o700)
        marker = backups / ".git"

        def introduce_git():
            if marker_kind == "directory":
                marker.mkdir()
            else:
                marker.write_text("gitdir: nonexistent-worktree-metadata\n")

        if when == "under-lock":
            original_flock = bindings.fcntl.flock

            def flock(fd, operation):
                original_flock(fd, operation)
                introduce_git()

            monkeypatch.setattr(bindings.fcntl, "flock", flock)
        else:
            original_write = persistence._atomic_write

            def atomic_write(path, content, **kwargs):
                if when == "final-guard":
                    introduce_git()
                original_write(path, content, **kwargs)
                if when == "post-publication":
                    introduce_git()

            monkeypatch.setattr(persistence, "_atomic_write", atomic_write)

        result = bindings.persist_reviewed(review, config)
        assert result.outcome == "failed"
        assert result.may_have_written is (when == "post-publication")
        assert result.baseline is None and result.backup_path is None
        assert result.error is not None and "outside Git" in result.error
        assert set(backups.iterdir()) == {marker}
        if when == "post-publication":
            assert target.read_text() == review.proposed_text
        else:
            assert not target.exists()

    def test_cancel_and_daemon_refusal(self, roots):
        review, config = draft(roots)
        cancel = threading.Event()
        cancel.set()
        result = bindings.persist_reviewed(review, config, cancel_event=cancel)
        assert result.outcome == "failed" and not result.may_have_written
        results = []
        thread = threading.Thread(
            target=lambda: results.append(bindings.persist_reviewed(review, config)), daemon=True
        )
        thread.start()
        thread.join()
        assert results[0].outcome == "failed"
        assert "non-daemon" in results[0].error
        assert not roots[1].exists()


class TestReadWorkers:
    def test_actual_observe_and_stdin_review(self, roots):
        baseline = bindings.run_observe(*roots)
        assert baseline == bindings.observe(*roots)
        proposed = bindings.BindingsConfig(("bind = SUPER, T, exec, echo '$HOME, x'; true",))
        review = bindings.run_prepare_review(baseline, proposed)
        assert review == bindings.prepare_review(baseline, proposed)
        assert bindings.BindingsReview.from_json(review.to_json()) == review
        with pytest.raises(ValueError):
            replace(review, review_hash="0" * 64)
        assert not roots[1].exists()

    def test_wrong_worker_context_and_cancel(self, roots, monkeypatch, tmp_path):
        baseline = bindings.observe(*roots)
        wrong = replace(baseline, state_root=str(tmp_path / "other"))
        with monkeypatch.context() as patch:
            patch.setattr(
                bindings.health,
                "run_bounded",
                lambda *a, **k: subprocess.CompletedProcess([], 0, wrong.to_json(), ""),
            )
            with pytest.raises(ValueError, match="different roots"):
                bindings.run_observe(*roots)
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(InterruptedError):
            bindings.run_observe(*roots, cancel_event=cancel)
        with pytest.raises(ValueError):
            bindings.run_observe(*roots, timeout=float("inf"))

    def test_exact_review_echo_and_transport_limits(self, roots, monkeypatch):
        review, config = draft(roots)
        wrong = bindings.prepare_review(review.baseline, bindings.BindingsConfig())

        def worker(*args, **kwargs):
            assert args[0][1:3] == ["-I", "-B"]
            assert kwargs["process_group"] is True
            request = json.loads(kwargs["input_text"])
            assert request["proposed"]["lines"] == list(config.lines)
            return subprocess.CompletedProcess([], 0, wrong.to_json(), "")

        monkeypatch.setattr(bindings.health, "run_bounded", worker)
        with pytest.raises(ValueError, match="different review request"):
            bindings.run_prepare_review(review.baseline, config)
        with pytest.raises(ValueError, match="limit"):
            bindings.BindingsReview.from_json(" " * (bindings.MAX_TRANSPORT_BYTES + 1))
        data = json.loads(review.to_json())
        data["proposed"]["lines"][0] = "bind = MOD4, Q, killactive"
        with pytest.raises(ValueError, match="Noncanonical"):
            bindings.BindingsReview.from_json(json.dumps(data))
