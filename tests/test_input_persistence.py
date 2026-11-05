"""Input data and the shared publisher, using only explicit temporary roots."""

import base64
import json
import os
import stat
import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from hyprmod.core import bindings, owned_output, persistence, route_approval
from hyprmod.core import input as device


@pytest.fixture
def roots(tmp_path):
    config = tmp_path / "config"
    (config / "hypr").mkdir(parents=True)
    return config, tmp_path / "state"


def draft(roots, values=None):
    config = device.InputConfig.from_mapping(
        {"input:kb_layout": "no", "input:kb_variant": ""} if values is None else values
    )
    return device.prepare_review(device.observe(*roots), config), config


class TestConfig:
    @pytest.mark.parametrize("key", sorted(device.INPUT_KEYS))
    def test_each_default_typed_and_roundtrips(self, key):
        values = {key: device.DEFAULTS[key]}
        if key == "input:kb_variant":
            values["input:kb_layout"] = "us"
        config = device.InputConfig.from_mapping(values)
        assert device.read_text(device.build_text(config)) == config
        assert type(dict(config.values)[key]) is device.OPTION_SPECS[key].value_type
        assert len(device.INPUT_KEYS) == 15

    @pytest.mark.parametrize("key", sorted(device.INPUT_KEYS))
    def test_each_wrong_type_refused(self, key):
        wrong = "false" if device.OPTION_SPECS[key].value_type is not str else False
        with pytest.raises(ValueError):
            device.InputConfig(((key, wrong),))

    @pytest.mark.parametrize(
        "key", [k for k, s in device.OPTION_SPECS.items() if s.minimum is not None]
    )
    def test_numeric_bounds_and_boolean_rejected(self, key):
        spec = device.OPTION_SPECS[key]
        if spec.minimum is None or spec.maximum is None:
            pytest.fail("Expected numeric bounds")
        for good in (spec.minimum, spec.maximum):
            config = device.InputConfig(((key, good),))
            assert device.read_text(device.build_text(config)) == config
        for bad in (spec.minimum - 1, spec.maximum + 1, True, False, "0"):
            with pytest.raises(ValueError):
                device.InputConfig(((key, bad),))

    @pytest.mark.parametrize(
        "key", ["input:sensitivity", "input:scroll_factor", "input:touchpad:scroll_factor"]
    )
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 10**400])
    def test_nonfinite_and_huge_numbers(self, key, bad):
        with pytest.raises(ValueError):
            device.InputConfig(((key, bad),))

    @pytest.mark.parametrize("key", ["input:scroll_factor", "input:touchpad:scroll_factor"])
    def test_conservative_scroll_step(self, key):
        assert dict(device.InputConfig(((key, 2),)).values)[key] == 2.0
        for bad in (0, 0.15, 2.1, 10):
            with pytest.raises(ValueError):
                device.InputConfig(((key, bad),))

    def test_zero_false_empty_and_absent_are_distinct(self):
        config = device.InputConfig.from_mapping(
            {
                "input:repeat_rate": 0,
                "input:sensitivity": -0.0,
                "input:left_handed": False,
                "input:kb_options": "",
                "input:accel_profile": "",
            }
        )
        assert config != device.InputConfig()
        text = device.build_text(config)
        assert "sensitivity = 0.0," in text and "sensitivity = -0.0" not in text
        assert device.read_text(text) == config

    @pytest.mark.parametrize(
        "layout,variant",
        [("no", ""), ("us,no", ""), ("us,no", ","), ("us,no", "intl,"), ("us,no", ",nodeadkeys")],
    )
    def test_layout_variant_atomic(self, layout, variant):
        config = device.InputConfig.from_mapping(
            {"input:kb_layout": layout, "input:kb_variant": variant}
        )
        assert device.read_text(device.build_text(config)) == config

    @pytest.mark.parametrize(
        "values",
        [
            {"input:kb_variant": ""},
            {"input:kb_variant": "intl"},
            {"input:kb_layout": ""},
            {"input:kb_layout": "us,no", "input:kb_variant": "intl"},
            {"input:kb_layout": "us", "input:kb_variant": ","},
            {"input:kb_layout": "us,,no"},
            {"input:accel_profile": "custom"},
            {"input:unknown": True},
            {"device:kb_layout": "us"},
        ],
    )
    def test_invalid_models(self, values):
        with pytest.raises(ValueError):
            device.InputConfig.from_mapping(values)

    @pytest.mark.parametrize("key", ["input:kb_layout", "input:kb_variant", "input:kb_options"])
    @pytest.mark.parametrize(
        "bad",
        [
            "$layout",
            "us;os.execute('bad')",
            "a\n",
            "a\x00",
            "a\u202e",
            "a\ud800",
            "../file",
            "/tmp/file",
            "us no",
            "a" * 1025,
        ],
    )
    def test_injection_and_nonascii_refused(self, key, bad):
        with pytest.raises(ValueError):
            device.InputConfig.from_mapping({"input:kb_layout": "us", key: bad})

    def test_canonical_sort_immutability_duplicate_and_unknown_options_preserved(self):
        options = "grp:alt_shift_toggle,future_group:unknown_tag-2"
        config = device.InputConfig.from_mapping(
            {"input:kb_options": options, "input:kb_layout": "no"}
        )
        assert config.values == tuple(sorted(config.values))
        assert (
            dict(device.read_text(device.build_text(config)).values)["input:kb_options"] == options
        )
        with pytest.raises(ValueError):
            device.InputConfig((("input:left_handed", True), ("input:left_handed", False)))
        with pytest.raises(ValueError):
            device.InputConfig([("input:left_handed", True)])  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            device.InputConfig((["input:left_handed", True],))  # type: ignore[arg-type]

    def test_forged_noncanonical_number_rejected(self):
        config = device.InputConfig((("input:sensitivity", 0.0),))
        object.__setattr__(config, "values", (("input:sensitivity", -0.0),))
        with pytest.raises(ValueError, match="canonical InputConfig"):
            device.build_text(config)
        object.__setattr__(config, "values", (("input:sensitivity", 0),))
        with pytest.raises(ValueError, match="canonical InputConfig"):
            device.build_text(config)


class TestCodec:
    def test_actual_batch_body_not_metadata(self):
        config = device.InputConfig.from_mapping({**device.DEFAULTS, "input:kb_layout": "no"})
        text = device.build_text(config)
        assert text.isascii()
        body = text.split("\n", 2)[2]
        assert body.count("hl.config(") == 1
        assert 'kb_layout = "no",' in body
        assert 'kb_variant = "",' in body and 'kb_options = "",' in body
        assert '["tap-to-click"] = true,' in body
        assert "repeat_rate = 25," in body
        assert "scroll_factor = 1.0," in body
        assert "left_handed = false," in body
        assert device.read_text(text) == config
        persistence.validate_lua(text)

    def test_public_emitter_gate(self, monkeypatch):
        monkeypatch.setattr(device, "keyword_to_lua", lambda *a: "hl.config({ kb_layout = false })")
        with pytest.raises(ValueError, match="typed input emission"):
            device.build_text(device.InputConfig((("input:kb_layout", "no"),)))

    def test_foreign_unknown_metadata_and_edited_body(self):
        text = device.build_text(device.InputConfig.from_mapping(device.DEFAULTS))
        for bad in (
            "",
            "-- authored\n",
            text + "-- edit\n",
            text.replace("repeat_rate = 25", "repeat_rate = 26"),
        ):
            with pytest.raises(ValueError):
                device.read_text(bad)
        for data in (
            {"version": 2, "values": {}},
            {"version": True, "values": {}},
            {"version": 1, "values": {"input:unknown": 1}},
            {"version": 1, "values": []},
        ):
            token = base64.b64encode(json.dumps(data).encode()).decode()
            with pytest.raises(ValueError):
                device.read_text(persistence.MARKER + device.RECORD + token + "\n")

    def test_transport_strictness_and_review_fingerprint(self, roots):
        review, config = draft(roots)
        assert device.InputReview.from_json(review.to_json()) == review
        assert device.InputBaseline.from_json(review.baseline.to_json()) == review.baseline
        for changed in ({"review_hash": "0" * 64}, {"added_lines": True}, {"diff": "edited"}):
            with pytest.raises(ValueError):
                replace(review, **changed)
        for bad in ("[" * 25, " " * (device.MAX_TRANSPORT_BYTES + 1), '{"x":1,"x":2}'):
            with pytest.raises(ValueError):
                device.InputReview.from_json(bad)
        data = json.loads(review.to_json())
        data["proposed"]["values"].reverse()
        with pytest.raises(ValueError, match="Noncanonical"):
            device.InputReview.from_json(json.dumps(data))
        assert not roots[1].exists()


class TestPersistence:
    @pytest.mark.parametrize("empty", [False, True])
    def test_first_repeat_noop_clear_and_verified_backup(self, roots, empty):
        target = roots[0] / "hypr" / device.BASENAME
        if empty:
            target.touch(mode=0o600)
        review, config = draft(roots)
        assert review.baseline.status == ("empty" if empty else "absent")
        assert not roots[1].exists()
        saved = device.persist_reviewed(review, config)
        assert saved.outcome == "saved", saved.error
        assert device.InputSaveResult.from_json(saved.to_json()) == saved
        if saved.baseline is None:
            pytest.fail("Missing fresh baseline")
        assert saved.baseline == device.observe(*roots)
        before = target.stat()
        noop = device.persist_reviewed(device.prepare_review(saved.baseline, config), config)
        assert noop.outcome == "no-op", noop.error
        assert target.stat() == before
        cleared = device.InputConfig()
        result = device.persist_reviewed(device.prepare_review(saved.baseline, cleared), cleared)
        assert result.outcome == "saved", result.error
        assert device.observe(*roots).config == cleared
        assert device.observe(*roots).status == "owned"
        assert target.read_text() == device.build_text(cleared) != ""
        if result.backup_path is None:
            pytest.fail("Missing durable backup")
        backup = Path(result.backup_path)
        assert backup.read_bytes() == review.proposed_text.encode()
        assert backup.name == saved.baseline.sha256 + ".lua"
        for file in (target, backup, roots[1] / "attune/input.lock"):
            assert stat.S_IMODE(file.stat().st_mode) == 0o600
        for folder in (roots[1] / "attune", backup.parent):
            assert stat.S_IMODE(folder.stat().st_mode) == 0o700

    def test_parent_stow_chain_in_git_and_protected_files_unchanged(self, roots, tmp_path):
        config, state = roots
        stow = tmp_path / "stow"
        stow.mkdir()
        (stow / ".git").mkdir()
        (config / "hypr").rmdir()
        (config / "hypr").symlink_to(stow)
        target = stow / device.BASENAME
        target.write_text(device.build_text(device.InputConfig()))
        protected = [
            stow / name
            for name in (
                "hyprland.lua",
                "hyprland.conf",
                "attune.lua",
                "attune-appearance.lua",
                "attune-displays.lua",
                "attune-bindings.lua",
                "keybindings.tsv",
                "keybindings-bridge.lua",
            )
        ]
        registry = config / "attune/installation.json"
        registry.parent.mkdir()
        journal = state / "attune/transactions/existing/journal.json"
        journal.parent.mkdir(parents=True)
        (state / "attune").chmod(0o700)
        protected.extend([registry, journal])
        for path in protected:
            path.write_text("opaque fixture, must never be parsed\n")
        before = [(p.read_bytes(), p.stat()) for p in protected]
        review, config_model = draft(roots)
        result = device.persist_reviewed(review, config_model)
        assert result.outcome == "saved", result.error
        assert (config / "hypr").is_symlink()
        assert [(p.read_bytes(), p.stat()) for p in protected] == before

    @pytest.mark.parametrize("writer,other", [(device, bindings), (bindings, device)])
    @pytest.mark.parametrize("alias", ["symlink", "hardlink"])
    def test_cross_owned_alias_refused_before_writes(self, roots, tmp_path, writer, other, alias):
        selected = roots[0] / "hypr" / writer.BASENAME
        # Both lexical leaves can resolve to the selected writer's fixed basename.
        destination = tmp_path / writer.BASENAME
        destination.write_text("opaque bytes")
        selected.symlink_to(destination)
        protected = selected.with_name(other.BASENAME)
        if alias == "symlink":
            protected.symlink_to(destination)
        else:
            os.link(destination, protected)
        before = destination.read_bytes(), destination.stat()
        with pytest.raises(ValueError):
            writer.observe(*roots)
        assert (destination.read_bytes(), destination.stat()) == before
        assert not roots[1].exists()

    @pytest.mark.parametrize(
        "name",
        [
            "hyprland.lua",
            "hyprland.conf",
            "attune.lua",
            "attune-appearance.lua",
            "attune-displays.lua",
            "keybindings.tsv",
            "keybindings-bridge.lua",
        ],
    )
    def test_other_protected_aliases(self, roots, tmp_path, name):
        destination = tmp_path / device.BASENAME
        destination.write_text(device.build_text(device.InputConfig()))
        selected = roots[0] / "hypr" / device.BASENAME
        selected.symlink_to(destination)
        selected.with_name(name).symlink_to(destination)
        with pytest.raises(ValueError, match="collide"):
            device.observe(*roots)
        assert not roots[1].exists()

    @pytest.mark.parametrize("when", ["under-lock", "before-publish"])
    def test_protected_alias_race(self, roots, monkeypatch, when):
        review, config = draft(roots)
        target = Path(review.baseline.lexical_path)
        protected = target.with_name(bindings.BASENAME)
        if when == "under-lock":
            original = owned_output.fcntl.flock

            def flock(*args):
                original(*args)
                protected.symlink_to(target)

            monkeypatch.setattr(owned_output.fcntl, "flock", flock)
        else:
            original_write = persistence._atomic_write

            def write(path, content, **kwargs):
                protected.symlink_to(target)
                original_write(path, content, **kwargs)

            monkeypatch.setattr(persistence, "_atomic_write", write)
        result = device.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert not target.exists()

    @pytest.mark.parametrize(
        "kind", ["foreign", "executable", "writable", "hardlink", "missing-parent"]
    )
    def test_unsafe_file_or_parent_no_state(self, roots, kind):
        target = roots[0] / "hypr" / device.BASENAME
        if kind == "missing-parent":
            target.parent.rmdir()
        else:
            target.write_text(
                "foreign" if kind == "foreign" else device.build_text(device.InputConfig())
            )
            if kind == "executable":
                target.chmod(0o700)
            elif kind == "writable":
                target.chmod(0o666)
            elif kind == "hardlink":
                os.link(target, target.with_suffix(".alias"))
        with pytest.raises((ValueError, OSError)):
            device.observe(*roots)
        assert not roots[1].exists()

    def test_stale_review_and_proposal_no_state(self, roots):
        review, config = draft(roots)
        result = device.persist_reviewed(review, device.InputConfig())
        assert result.outcome == "failed" and not result.may_have_written
        Path(review.baseline.lexical_path).touch(mode=0o600)
        result = device.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert not roots[1].exists()

    def test_file_stow_link_and_exclusive_absent_collision(self, roots, tmp_path, monkeypatch):
        destination = tmp_path / device.BASENAME
        destination.write_text(device.build_text(device.InputConfig()))
        target = roots[0] / "hypr" / device.BASENAME
        target.symlink_to(destination)
        review, config = draft(roots)
        result = device.persist_reviewed(review, config)
        assert result.outcome == "saved", result.error
        assert target.is_symlink() and destination.read_text() == review.proposed_text
        target.unlink()
        review, config = draft(roots)
        original = os.link

        def link(source, output, **kwargs):
            Path(output).write_text("racing writer")
            return original(source, output, **kwargs)

        monkeypatch.setattr(os, "link", link)
        failed = device.persist_reviewed(review, config)
        assert failed.outcome == "failed" and failed.may_have_written
        assert failed.baseline is None
        assert target.read_text() == "racing writer"

    def test_existing_rename_failure_keeps_verified_backup(self, roots, monkeypatch):
        target = roots[0] / "hypr" / device.BASENAME
        target.write_text(device.build_text(device.InputConfig()))
        review, config = draft(roots)
        original = os.replace

        def rename(source, output):
            if Path(output) == target:
                raise OSError("rename refused")
            return original(source, output)

        monkeypatch.setattr(os, "replace", rename)
        result = device.persist_reviewed(review, config)
        assert result.outcome == "failed" and result.may_have_written
        assert result.baseline is None
        if result.backup_path is None:
            pytest.fail("Missing verified backup")
        assert Path(result.backup_path).read_text() == review.baseline.text == target.read_text()
        assert device.InputSaveResult.from_json(result.to_json()) == result

    def test_backup_durability_failure_cannot_publish(self, roots, monkeypatch):
        target = roots[0] / "hypr" / device.BASENAME
        target.write_text(device.build_text(device.InputConfig()))
        review, config = draft(roots)
        backups = roots[1] / "attune/input-backups"
        backups.mkdir(parents=True, mode=0o700)
        backups.parent.chmod(0o700)
        backup = backups / (review.baseline.sha256 + ".lua")
        backup.write_text(review.baseline.text)
        backup.chmod(0o600)
        original = os.fsync

        def sync(fd):
            if os.fstat(fd).st_ino == backup.stat().st_ino:
                raise OSError("backup sync failed")
            original(fd)

        monkeypatch.setattr(os, "fsync", sync)
        result = device.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.backup_path is None and result.baseline is None
        assert target.read_text() == review.baseline.text

    def test_storage_route_change_during_lock_refused(self, roots, tmp_path, monkeypatch):
        review, config = draft(roots)
        original = owned_output.fcntl.flock

        def flock(*args):
            original(*args)
            state = roots[1] / "attune"
            state.rename(tmp_path / "retired-state")
            state.mkdir(mode=0o700)
            (state / "input.lock").touch(mode=0o600)

        monkeypatch.setattr(owned_output.fcntl, "flock", flock)
        result = device.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert not Path(review.baseline.lexical_path).exists()

    @pytest.mark.parametrize("change", ["lock-identity", "backups-mode"])
    def test_private_storage_change_under_lock(self, roots, tmp_path, monkeypatch, change):
        review, config = draft(roots)
        backups = roots[1] / "attune/input-backups"
        backups.mkdir(parents=True, mode=0o700)
        backups.parent.chmod(0o700)
        original = owned_output.fcntl.flock

        def flock(*args):
            original(*args)
            if change == "lock-identity":
                lock = backups.parent / "input.lock"
                lock.rename(tmp_path / "old-lock")
                lock.touch(mode=0o600)
            else:
                backups.chmod(0o755)

        monkeypatch.setattr(owned_output.fcntl, "flock", flock)
        result = device.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert not Path(review.baseline.lexical_path).exists()

    def test_cancellation_after_compilation_cannot_publish(self, roots, monkeypatch):
        review, config = draft(roots)
        cancel = threading.Event()
        original = persistence.validate_lua

        def compile(text):
            original(text)
            cancel.set()

        monkeypatch.setattr(persistence, "validate_lua", compile)
        result = device.persist_reviewed(review, config, cancel_event=cancel)
        assert result.outcome == "failed" and not result.may_have_written
        assert not Path(review.baseline.lexical_path).exists()

    @pytest.mark.parametrize("when", ["under-lock", "before-publish", "after-publish"])
    def test_backup_git_races(self, roots, monkeypatch, when):
        review, config = draft(roots)
        backups = roots[1] / "attune/input-backups"
        backups.mkdir(parents=True, mode=0o700)
        backups.parent.chmod(0o700)
        marker = backups / ".git"
        if when == "under-lock":
            original = owned_output.fcntl.flock

            def flock(*args):
                original(*args)
                marker.mkdir()

            monkeypatch.setattr(owned_output.fcntl, "flock", flock)
        else:
            original_write = persistence._atomic_write

            def write(path, content, **kwargs):
                if when == "before-publish":
                    marker.mkdir()
                original_write(path, content, **kwargs)
                if when == "after-publish":
                    marker.mkdir()

            monkeypatch.setattr(persistence, "_atomic_write", write)
        result = device.persist_reviewed(review, config)
        assert result.outcome == "failed" and result.baseline is None
        assert result.may_have_written is (when == "after-publish")
        assert result.error is not None and "outside Git" in result.error

    @pytest.mark.parametrize(
        "unsafe",
        [
            "state-git",
            "backup-git",
            "backup-git-file",
            "state-mode",
            "lock-mode",
            "lock-link",
            "backup-link",
            "backup-bytes",
        ],
    )
    def test_private_storage_refusals_before_lock(self, roots, unsafe):
        target = roots[0] / "hypr" / device.BASENAME
        target.write_text(device.build_text(device.InputConfig()))
        review, config = draft(roots)
        state = roots[1] / "attune"
        backups = state / "input-backups"
        backups.mkdir(parents=True, mode=0o700)
        state.chmod(0o700)
        lock = state / "input.lock"
        backup = backups / (review.baseline.sha256 + ".lua")
        if unsafe == "state-git":
            (roots[1] / ".git").mkdir()
        elif unsafe == "backup-git":
            (backups / ".git").mkdir()
        elif unsafe == "backup-git-file":
            (backups / ".git").write_text("gitdir: nowhere\n")
        elif unsafe == "state-mode":
            state.chmod(0o755)
        elif unsafe == "lock-mode":
            lock.touch(mode=0o644)
        elif unsafe == "lock-link":
            lock.symlink_to(target)
        elif unsafe == "backup-link":
            backup.symlink_to(target)
        else:
            backup.write_text("wrong")
            backup.chmod(0o600)
        result = device.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert target.read_text() == review.baseline.text
        assert not lock.exists() or unsafe in {"lock-mode", "lock-link"}

    @pytest.mark.parametrize(
        "stage", ["compile", "stage-fsync", "rename", "directory-fsync", "post-read"]
    )
    def test_failure_uncertainty_honest(self, roots, monkeypatch, stage):
        review, config = draft(roots)
        if stage == "compile":

            def refuse(*args):
                raise ValueError("compiler refused")

            monkeypatch.setattr(persistence, "validate_lua", refuse)
        elif stage in {"stage-fsync", "directory-fsync"}:
            original_sync = os.fsync
            calls = 0

            def sync(fd):
                nonlocal calls
                calls += 1
                if calls == (1 if stage == "stage-fsync" else 2):
                    raise OSError("sync failed")
                original_sync(fd)

            monkeypatch.setattr(os, "fsync", sync)
        elif stage == "rename":

            def link(*args, **kwargs):
                raise OSError("exclusive link refused")

            monkeypatch.setattr(os, "link", link)
        else:
            original_observe = device.observe

            def observe(*args):
                baseline = original_observe(*args)
                if baseline.status == "owned":
                    raise ValueError("postread unavailable")
                return baseline

            monkeypatch.setattr(device, "observe", observe)
        result = device.persist_reviewed(review, config)
        assert result.outcome == "failed" and result.baseline is None
        assert result.may_have_written is (stage in {"rename", "directory-fsync", "post-read"})

    def test_cancellation_daemon_and_lock_timeout(self, roots, monkeypatch):
        review, config = draft(roots)
        cancel = threading.Event()
        cancel.set()
        result = device.persist_reviewed(review, config, cancel_event=cancel)
        assert result.outcome == "failed" and not result.may_have_written
        results = []
        thread = threading.Thread(
            target=lambda: results.append(device.persist_reviewed(review, config)), daemon=True
        )
        thread.start()
        thread.join()
        assert results[0].outcome == "failed" and "non-daemon" in results[0].error
        assert not roots[1].exists()

        def busy(*args):
            raise BlockingIOError()

        monkeypatch.setattr(owned_output.fcntl, "flock", busy)
        monkeypatch.setattr(owned_output, "LOCK_TIMEOUT", 0)
        result = device.persist_reviewed(review, config)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.error is not None and "timed out" in result.error


class TestWorkers:
    def test_actual_isolated_observe_review_and_repeated_save(self, roots):
        baseline = device.run_observe(*roots)
        assert baseline == device.observe(*roots)
        config = device.InputConfig.from_mapping(device.DEFAULTS)
        review = device.run_prepare_review(baseline, config)
        assert review == device.prepare_review(baseline, config)
        assert not roots[1].exists()
        result = device.persist_reviewed(review, config)
        assert result.outcome == "saved", result.error
        fresh = device.run_observe(*roots)
        assert fresh == result.baseline
        repeat = device.run_prepare_review(fresh, config)
        assert device.persist_reviewed(repeat, config).outcome == "no-op"

    def test_context_cancel_timeout_and_exact_request(self, roots, monkeypatch, tmp_path):
        baseline = device.observe(*roots)
        wrong = replace(baseline, state_root=str(tmp_path / "other"))
        with monkeypatch.context() as patch:
            patch.setattr(
                device.health,
                "run_bounded",
                lambda *a, **k: subprocess.CompletedProcess([], 0, wrong.to_json(), ""),
            )
            with pytest.raises(ValueError, match="different roots"):
                device.run_observe(*roots)
        config = device.InputConfig.from_mapping(device.DEFAULTS)
        wrong_review = device.prepare_review(baseline, device.InputConfig())

        def worker(*args, **kwargs):
            assert args[0][1:3] == ["-I", "-B"]
            assert kwargs["process_group"] is True
            request = json.loads(kwargs["input_text"])
            assert request["proposed"] == json.loads(
                route_approval._json({"values": config.values})
            )
            return subprocess.CompletedProcess([], 0, wrong_review.to_json(), "")

        with monkeypatch.context() as patch:
            patch.setattr(device.health, "run_bounded", worker)
            with pytest.raises(ValueError, match="different review request"):
                device.run_prepare_review(baseline, config)
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(InterruptedError):
            device.run_observe(*roots, cancel_event=cancel)
        for timeout in (0, -1, float("inf"), float("nan")):
            with pytest.raises(ValueError):
                device.run_observe(*roots, timeout=timeout)
