"""Source data and publication tests use only explicit temporary destinations."""

import json
import os
import stat
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest

from hyprmod.core import health, persistence, route_approval
from hyprmod.core import source_bindings as source

BUNDLE = Path(__file__).resolve().parents[1] / "integrations/hyprland/jdawson/keybindings.tsv"
PROTECTED = (
    "hypr/hyprland.lua",
    "hypr/hyprland.conf",
    "hypr/attune.lua",
    "hypr/attune-bindings.lua",
    "hypr/keybindings-bridge.lua",
    "hypr/attune-appearance.lua",
    "hypr/attune-displays.lua",
    "attune/installation.json",
)


@pytest.fixture
def bundle():
    return BUNDLE.read_bytes().decode("utf-8")


@pytest.fixture
def selected(tmp_path, bundle):
    path = tmp_path / "config/hypr/keybindings.tsv"
    path.parent.mkdir(parents=True)
    path.write_text(bundle, encoding="utf-8")
    path.chmod(0o600)
    return path, tmp_path / "state"


@pytest.fixture
def linked_installation(selected, tmp_path):
    root = tmp_path / "actual-config"
    installed = root / "hypr/keybindings.tsv"
    installed.parent.mkdir(parents=True)
    installed.symlink_to(selected[0])
    for path in (selected[0], installed):
        path.with_name(source.BRIDGE_BASENAME).write_bytes(
            BUNDLE.with_name(source.BRIDGE_BASENAME).read_bytes()
        )
    return selected, root, installed


def changed(config, **values):
    return replace(config, bindings=(replace(config.bindings[0], **values), *config.bindings[1:]))


def draft(selected):
    baseline = source.observe(*selected)
    proposal = changed(
        baseline.config, key="  Shift + CONTROL + F12  ", description="Edited terminal"
    )
    return source.prepare_review(baseline, proposal), proposal


class TestCodec:
    def test_disabled_transport_and_unique_ids(self, bundle):
        config = source.read_text(bundle)
        disabled = changed(config, flags=("disabled",))
        assert not disabled.bindings[0].enabled
        assert config.bindings[0].enabled
        assert source.fixed_metadata(disabled) == source.fixed_metadata(config)
        assert source.read_text(source.build_text(disabled)) == disabled
        assert source._config_from(json.loads(json.dumps(asdict(disabled)))) == disabled
        with pytest.raises(ValueError, match="Duplicate"):
            replace(disabled, bindings=(*disabled.bindings, disabled.bindings[0]))
        with pytest.raises(ValueError):
            changed(disabled, key="")
        with pytest.raises(ValueError):
            changed(disabled, description="")

    @pytest.mark.parametrize("disabled_index", [0, 1])
    def test_only_enabled_rows_claim_shortcuts(self, bundle, disabled_index):
        config = source.read_text(bundle)
        rows = list(config.bindings)
        rows[disabled_index] = replace(rows[disabled_index], flags=("disabled",))
        rows[1 - disabled_index] = replace(rows[1 - disabled_index], key="win + t")
        rows[disabled_index] = replace(rows[disabled_index], key="SUPER + T")
        draft = replace(config, bindings=tuple(rows))
        assert source.read_text(source.build_text(draft)) == draft
        with pytest.raises(ValueError, match="Duplicate"):
            replace(config, bindings=tuple(replace(row, flags=()) for row in rows))
        both_disabled = replace(
            draft, bindings=tuple(replace(row, flags=("disabled",)) for row in rows)
        )
        assert source.read_text(source.build_text(both_disabled)) == both_disabled

    def test_actual_bundle_byte_exact_and_no_callbacks(self, bundle):
        config = source.read_text(bundle)
        assert len(config.bindings) == 80
        assert source.build_text(config).encode("utf-8") == BUNDLE.read_bytes()
        assert set(asdict(config.bindings[0])) == {
            "id",
            "context",
            "submap",
            "flags",
            "key",
            "description",
        }
        assert all(token not in bundle for token in ("hl.bind", "function(", "hl.dispatch"))
        assert config.bindings[4].key == "SUPER + CTRL + Q"
        assert config.bindings[-1].flags == ("locked", "repeating")
        with pytest.raises(FrozenInstanceError):
            config.catalog = "other"  # type: ignore[misc]

    def test_descriptions_are_inert_and_whitespace_is_preserved(self, bundle, tmp_path):
        sentinel = tmp_path / "must-not-exist"
        description = f"""  os.execute("touch {sentinel}"); dofile('/tmp/evil.lua')  """
        config = changed(
            source.read_text(bundle), key="  ctrl + Shift + F12  ", description=description
        )
        text = source.build_text(config)
        assert source.read_text(text) == config
        assert config.bindings[0].description == description
        assert "\t  ctrl + Shift + F12  \t" in text
        assert not sentinel.exists()

    @pytest.mark.parametrize(
        "key",
        [
            "",
            "x\ny",
            "x\ty",
            "SUPER++T",
            "UNKNOWN + T",
            "CTRL+CONTROL+T",
            "A B",
            "x\x00",
            "x\u202e",
            "x" * 257,
        ],
    )
    def test_invalid_keys(self, key):
        with pytest.raises(ValueError):
            source.validate_key(key)

    @pytest.mark.parametrize(
        "key",
        ["SUPER + mouse:272", "mouse_up", "XF86AudioPlay", " SUPER + CTRL + Q ", "h", "SHIFT + 3"],
    )
    def test_valid_exact_keys(self, key):
        assert source.validate_key(key) == key

    def test_native_submap_not_descriptive_context(self):
        a = source.SourceBinding("a", "global", "", (), "CTRL + H", "First")
        b = source.SourceBinding("b", "manager", "", (), " control + h ", "Second")
        with pytest.raises(ValueError, match="Duplicate"):
            source.SourceConfig(source.CATALOG, (a, b))
        config = source.SourceConfig(source.CATALOG, (a, replace(b, submap="wisp")))
        assert source.read_text(source.build_text(config)) == config
        assert source.key_identity("SUPER + CTRL + Q") == source.key_identity("control+win+q")

    @pytest.mark.parametrize(
        "edit",
        [
            lambda t: t.replace("v1\n", "v2\n", 1),
            lambda t: t.replace("jdawson.hyprland", "foreign", 1),
            lambda t: t.replace("id\tcontext", "action\tcontext", 1),
            lambda t: t.replace("\n", "\r\n"),
            lambda t: t[:-1],
            lambda t: t + "\n",
            lambda t: t + "-- Lua\n",
            lambda t: t.replace("Open terminal (Return)", "x\tbad"),
            lambda t: t.replace("Open terminal (Return)", "x\x7f"),
            lambda t: t.replace("Open terminal (Return)", "x" * 513),
            lambda t: t.replace("terminal.t\t", "terminal.return\t"),
            lambda t: t.replace("locked,repeating", "repeating,locked"),
            lambda t: t.replace("locked,repeating", "locked,locked"),
            lambda t: t.replace("auto_consuming", "exec"),
            lambda t: t.replace("\tmanager\t", "\tunknown\t"),
            lambda t: t.replace("\twisp\twisp\t", "\twisp\tmanager\t"),
        ],
    )
    def test_invalid_schema(self, bundle, edit):
        with pytest.raises(ValueError):
            source.read_text(edit(bundle))

    def test_limits_and_strict_immutability(self, bundle):
        config = source.read_text(bundle)
        with pytest.raises(ValueError):
            replace(config, bindings=list(config.bindings))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            replace(config.bindings[0], flags=["locked"])  # type: ignore[arg-type]
        row = config.bindings[0]
        with pytest.raises(ValueError):
            source.SourceConfig(
                source.CATALOG, tuple(replace(row, id=f"a{n}", key=f"F{n}") for n in range(1001))
            )
        with pytest.raises(ValueError):
            source.SourceConfig(
                source.CATALOG,
                tuple(
                    replace(row, id=f"a{n}", key=f"F{n}", description="x" * 512)
                    for n in range(1000)
                ),
            )
        with pytest.raises(ValueError):
            source.read_text("x" * (source.MAX_INPUT_BYTES + 1))


class TestReview:
    @pytest.mark.parametrize(
        "companion", [None, "-- old bridge\n", "\n" + source.BRIDGE_CAPABILITY + "\n"]
    )
    def test_unsupported_bridge_refuses_disabled_but_not_enabled(self, selected, companion):
        path, state = selected
        if companion is not None:
            path.with_name(source.BRIDGE_BASENAME).write_text(companion)
        baseline = source.observe(*selected)
        disabled = changed(baseline.config, flags=("disabled",))
        with pytest.raises(
            ValueError, match="Update the source keybindings bridge.*restore defaults"
        ):
            source.prepare_review(baseline, disabled)
        # A constructed pure review is not authority to bypass writer preflight.
        review = source.SourceReview(baseline, disabled, *source._review_fields(baseline, disabled))
        result = source.persist_reviewed(review, disabled)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.error and "Update the source keybindings bridge" in result.error
        assert not state.exists() and path.read_text() == baseline.text
        enabled = changed(baseline.config, description="Still editable")
        assert (
            source.persist_reviewed(source.prepare_review(baseline, enabled), enabled).outcome
            == "saved"
        )

    def test_disabled_observable_with_old_bridge(self, selected):
        path, state = selected
        config = changed(source.read_text(path.read_text()), flags=("disabled",))
        path.write_text(source.build_text(config))
        path.with_name(source.BRIDGE_BASENAME).write_text("-- old bridge\n")
        baseline = source.observe(path, state)
        assert baseline.config == config
        with pytest.raises(ValueError, match="Update the source keybindings bridge"):
            source.prepare_review(baseline, config)
        assert not state.exists() and path.read_text() == baseline.text

    def test_disabled_does_not_allow_base_flag_edits(self, selected):
        path, _ = selected
        path.with_name(source.BRIDGE_BASENAME).write_text(source.BRIDGE_CAPABILITY + "\n")
        baseline = source.observe(*selected)
        rows = baseline.config.bindings
        index = next(i for i, row in enumerate(rows) if row.flags == ("locked", "repeating"))
        for flags in (("disabled",), ("disabled", "locked"), ("disabled", "mouse")):
            proposal = replace(
                baseline.config,
                bindings=(*rows[:index], replace(rows[index], flags=flags), *rows[index + 1 :]),
            )
            with pytest.raises(ValueError, match="base flags.*read-only"):
                source.prepare_review(baseline, proposal)

    @pytest.mark.parametrize("unsafe", ["public", "hardlink", "directory"])
    def test_unsafe_bridge_refused_without_state(self, selected, unsafe):
        path, state = selected
        bridge = path.with_name(source.BRIDGE_BASENAME)
        if unsafe == "directory":
            bridge.mkdir()
        else:
            bridge.write_text(source.BRIDGE_CAPABILITY + "\n")
            if unsafe == "public":
                bridge.chmod(0o666)
            else:
                os.link(bridge, bridge.with_name("bridge-alias"))
        baseline = source.observe(*selected)
        with pytest.raises(ValueError, match="Update the source keybindings bridge"):
            source.prepare_review(baseline, changed(baseline.config, flags=("disabled",)))
        assert not state.exists()

    def test_bridge_must_be_selected_companion_not_config_or_cwd(
        self, selected, tmp_path, monkeypatch
    ):
        root = tmp_path / "actual-config"
        (root / "hypr").mkdir(parents=True)
        (root / "hypr" / source.BRIDGE_BASENAME).write_text(source.BRIDGE_CAPABILITY + "\n")
        monkeypatch.chdir(root / "hypr")
        baseline = source.observe(*selected, config_root=root)
        with pytest.raises(ValueError, match="Update the source keybindings bridge"):
            source.prepare_review(baseline, changed(baseline.config, flags=("disabled",)))

    def test_protected_context_strict_pure_transport(self, selected, tmp_path, monkeypatch):
        baseline = source.observe(*selected, config_root=tmp_path / "actual-config")
        assert baseline.config_root == str(tmp_path / "actual-config")
        assert baseline.installed_route.lexical_path == str(
            tmp_path / "actual-config/hypr/keybindings.tsv"
        )
        assert baseline.installed_route not in baseline.protected
        for installed in (
            asdict(baseline.installed_route),
            replace(baseline.installed_route, lexical_path=str(tmp_path / "wrong/keybindings.tsv")),
            replace(baseline.installed_route, facts=list(baseline.installed_route.facts)),
        ):
            with pytest.raises(ValueError):
                replace(baseline, installed_route=installed)  # type: ignore[arg-type]
        expected = tuple(str(tmp_path / "actual-config" / name) for name in PROTECTED)
        assert tuple(p.lexical_path for p in baseline.protected[: len(PROTECTED)]) == expected
        assert all(p.lexical_path != str(selected[1] / "attune") for p in baseline.protected)
        for protected in (
            list(baseline.protected),
            baseline.protected[:-1],
            baseline.protected[::-1],
        ):
            with pytest.raises(ValueError):
                replace(baseline, protected=protected)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            replace(baseline, config_root=str(tmp_path / "different-config"))
        data = json.loads(baseline.to_json())
        data["protected"][0]["facts"][0]["identity"][0] = True
        with pytest.raises(ValueError):
            source.SourceBaseline.from_json(json.dumps(data))
        data = json.loads(baseline.to_json())
        data["installed_route"]["facts"][0]["identity"][0] = True
        with pytest.raises(ValueError):
            source.SourceBaseline.from_json(json.dumps(data))
        monkeypatch.setattr(route_approval, "_resolve", lambda *a, **k: pytest.fail("resolve"))
        monkeypatch.setattr(route_approval, "_fact", lambda *a, **k: pytest.fail("stat"))
        monkeypatch.setattr(persistence, "read_stable", lambda *a, **k: pytest.fail("read"))
        assert source.SourceBaseline.from_json(baseline.to_json()) == baseline

    def test_roundtrip_diff_and_tampering(self, selected):
        review, proposal = draft(selected)
        assert source.SourceBaseline.from_json(review.baseline.to_json()) == review.baseline
        assert source.SourceReview.from_json(review.to_json()) == review
        assert review.added_lines == review.removed_lines == 1
        assert "Edited terminal" in review.diff
        for field, value in (
            ("diff", ""),
            ("review_hash", "0" * 64),
            ("added_lines", True),
            ("proposed_text", review.baseline.text),
        ):
            with pytest.raises(ValueError):
                replace(review, **{field: value})
        result = source.persist_reviewed(review, changed(proposal, description="later edit"))
        assert result.outcome == "failed" and not result.may_have_written
        assert result.baseline is None
        assert not selected[1].exists()

    @pytest.mark.parametrize(
        "field,value",
        [("id", "new-id"), ("context", "manager"), ("submap", "wisp"), ("flags", ("locked",))],
    )
    def test_immutable_metadata(self, selected, field, value):
        baseline = source.observe(*selected)
        proposal = changed(baseline.config, **{field: value})
        with pytest.raises(ValueError, match="read-only"):
            source.prepare_review(baseline, proposal)

    def test_no_delete_add_reorder(self, selected):
        baseline = source.observe(*selected)
        rows = baseline.config.bindings
        for new in (rows[1:], rows[::-1], (*rows, replace(rows[0], id="new", key="F24"))):
            with pytest.raises(ValueError, match="read-only"):
                source.prepare_review(baseline, replace(baseline.config, bindings=new))

    def test_transport_limits_schema_and_duplicate_fields(self, selected):
        baseline = source.observe(*selected)
        for text in (
            "[" * 25,
            " " * (source.MAX_TRANSPORT_BYTES + 1),
            '{"lexical_path":"x","lexical_path":"y"}',
            baseline.to_json().replace('"flags":[]', '"flags":{}', 1),
        ):
            with pytest.raises(ValueError):
                source.SourceBaseline.from_json(text)


class TestObservation:
    @pytest.mark.parametrize("relative", PROTECTED)
    @pytest.mark.parametrize("explicit", [False, True])
    def test_actual_config_alias_refused_before_reads_or_state_writes(
        self, selected, tmp_path, monkeypatch, relative, explicit
    ):
        path, state = selected
        root = tmp_path / "actual-config"
        protected = root / relative
        protected.parent.mkdir(parents=True)
        protected.symlink_to(path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
        monkeypatch.setattr(persistence, "read_stable", lambda *a, **k: pytest.fail("read"))
        with pytest.raises(ValueError, match="collid|alias"):
            source.observe(path, state, **({"config_root": root} if explicit else {}))
        assert not state.exists()
        assert protected.is_symlink()

    def test_private_state_source_overlap_is_not_frozen_evidence(self, selected):
        path, state = selected
        private = state / "attune"
        private.mkdir(parents=True, mode=0o700)
        target = private / source.BASENAME
        path.rename(target)
        with pytest.raises(ValueError, match="collid|alias"):
            source.observe(target, state)

    def test_existing_only_and_fixed_basenames(self, selected):
        path, state = selected
        wrong = path.with_name("other.tsv")
        wrong.write_bytes(path.read_bytes())
        with pytest.raises(ValueError):
            source.observe(wrong, state)
        path.unlink()
        with pytest.raises((OSError, ValueError)):
            source.observe(path, state)
        assert not path.exists() and not state.exists()
        path.symlink_to(wrong)
        with pytest.raises(ValueError):
            source.observe(path, state)

    @pytest.mark.parametrize("mode", [0o400, 0o200, 0o700, 0o666, 0o4600])
    def test_unsafe_permissions(self, selected, mode):
        path, state = selected
        path.chmod(mode)
        try:
            with pytest.raises(ValueError):
                source.observe(path, state)
        finally:
            path.chmod(0o600)

    def test_foreign_empty_and_hardlink_refused(self, selected):
        path, state = selected
        for text in ("", "hl.bind('x', function() end)\n"):
            path.write_text(text)
            with pytest.raises(ValueError):
                source.observe(path, state)
        path.write_bytes(BUNDLE.read_bytes())
        os.link(path, path.with_name("alias"))
        with pytest.raises(ValueError):
            source.observe(path, state)
        assert not state.exists()

    def test_unsafe_parent(self, selected):
        path, state = selected
        path.parent.chmod(0o777)
        try:
            with pytest.raises(ValueError):
                source.observe(path, state)
        finally:
            path.parent.chmod(0o755)

    def test_protected_alias_and_no_author_reads(self, selected, monkeypatch):
        path, state = selected
        author = path.with_name("hyprland.lua")
        author.symlink_to(path)
        with pytest.raises(ValueError, match="collid|alias"):
            source.observe(path, state)
        author.unlink()
        author.write_text("unreadable authored callbacks")
        original = persistence.read_stable
        reads = []

        def read(target, **kwargs):
            reads.append(target)
            assert target.name != "hyprland.lua"
            return original(target, **kwargs)

        monkeypatch.setattr(persistence, "read_stable", read)
        monkeypatch.setattr(persistence, "validate_lua", lambda *a: pytest.fail("Lua compiler"))
        monkeypatch.setattr(health, "run_bounded", lambda *a, **k: pytest.fail("command or IPC"))
        review, proposal = draft(selected)
        assert source.persist_reviewed(review, proposal).outcome == "saved"
        assert reads and all(p.name != "hyprland.lua" for p in reads)
        assert author.read_text() == "unreadable authored callbacks"


class TestPublication:
    @pytest.mark.parametrize("companion", ["old", "missing"])
    def test_installed_alias_requires_both_capable_bridges(self, linked_installation, companion):
        selected, root, installed = linked_installation
        path, state = selected
        bridge = installed.with_name(source.BRIDGE_BASENAME)
        bridge.unlink()
        if companion == "old":
            bridge.write_text("-- old installed bridge\n")
        baseline = source.observe(path, state, config_root=root)
        proposal = changed(baseline.config, flags=("disabled",))
        with pytest.raises(
            ValueError, match="Update the source keybindings bridge.*restore defaults"
        ):
            source.prepare_review(baseline, proposal)
        review = source.SourceReview(baseline, proposal, *source._review_fields(baseline, proposal))
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.error and "Update the source keybindings bridge" in result.error
        assert not state.exists() and path.read_text() == baseline.text
        assert installed.is_symlink()

    def test_installed_alias_save_reassign_reopen_and_reenable(self, linked_installation):
        selected, root, installed = linked_installation
        path, state = selected
        baseline = source.run_observe(path, state, config_root=root)
        assert baseline.installed_route.resolved_path == baseline.resolved_path
        assert source.SourceBaseline.from_json(baseline.to_json()) == baseline
        link_stat = installed.lstat()
        rows = baseline.config.bindings
        proposal = replace(
            baseline.config,
            bindings=(
                replace(rows[0], key="win + t"),
                replace(rows[1], flags=("disabled",)),
                *rows[2:],
            ),
        )
        review = source.run_prepare_review(baseline, proposal)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "saved", result.error
        reopened = source.observe(path, state, config_root=root)
        assert result.baseline == reopened and reopened.config == proposal
        assert installed.lstat() == link_stat and installed.read_text() == source.build_text(
            proposal
        )
        assert reopened.installed_route != baseline.installed_route
        noop = source.persist_reviewed(source.prepare_review(reopened, proposal), proposal)
        assert noop.outcome == "no-op", noop.error
        restored = source.persist_reviewed(
            source.prepare_review(reopened, baseline.config), baseline.config
        )
        assert restored.outcome == "saved", restored.error
        assert path.read_text() == baseline.text and installed.lstat() == link_stat

    def test_unrelated_offline_source_ignores_old_installed_bridge(
        self, linked_installation, monkeypatch
    ):
        selected, root, installed = linked_installation
        path, state = selected
        installed.unlink()
        installed.write_text("unrelated installed data is metadata-only, never parsed")
        installed.with_name(source.BRIDGE_BASENAME).write_text("-- old installed bridge\n")
        original = installed.stat()
        read = persistence.read_stable
        open_file = source.os.open

        def guarded_read(target, **kwargs):
            assert target != installed
            return read(target, **kwargs)

        def guarded_open(target, *args, **kwargs):
            assert Path(target) not in (installed, installed.with_name(source.BRIDGE_BASENAME))
            return open_file(target, *args, **kwargs)

        monkeypatch.setattr(persistence, "read_stable", guarded_read)
        monkeypatch.setattr(source.os, "open", guarded_open)
        baseline = source.observe(path, state, config_root=root)
        proposal = changed(baseline.config, flags=("disabled",))
        result = source.persist_reviewed(source.prepare_review(baseline, proposal), proposal)
        assert result.outcome == "saved", result.error
        assert installed.stat() == original
        assert result.baseline is not None
        assert result.baseline.installed_route == baseline.installed_route

    @pytest.mark.parametrize("dependency", ["route", "bridge"])
    @pytest.mark.parametrize("stage", ["before-save", "under-lock", "final-publish"])
    def test_installed_route_or_bridge_retarget_after_review(
        self, linked_installation, tmp_path, monkeypatch, dependency, stage
    ):
        selected, root, installed = linked_installation
        path, state = selected
        bridge = installed.with_name(source.BRIDGE_BASENAME)
        old_bridge = tmp_path / "old-bridge.lua"
        old_bridge.write_text("-- old bridge\n")
        if dependency == "route":
            # Initially unrelated. Retargeting makes the old installed loader relevant.
            unrelated = tmp_path / "unrelated/keybindings.tsv"
            unrelated.parent.mkdir()
            unrelated.write_bytes(path.read_bytes())
            installed.unlink()
            installed.symlink_to(unrelated)
            bridge.unlink()
            bridge.symlink_to(old_bridge)
        baseline = source.observe(path, state, config_root=root)
        proposal = changed(baseline.config, flags=("disabled",))
        review = source.prepare_review(baseline, proposal)

        def retarget():
            target = installed if dependency == "route" else bridge
            target.unlink()
            target.symlink_to(path if dependency == "route" else old_bridge)

        if stage == "before-save":
            retarget()
            with pytest.raises(ValueError, match="changed"):
                source.prepare_review(baseline, proposal)
        elif stage == "under-lock":
            flock = source.fcntl.flock

            def acquire(fd, flags):
                flock(fd, flags)
                retarget()

            monkeypatch.setattr(source.fcntl, "flock", acquire)
        else:
            write = persistence._atomic_write

            def atomic(target, raw, **kwargs):
                if target == path:
                    retarget()
                write(target, raw, **kwargs)

            monkeypatch.setattr(persistence, "_atomic_write", atomic)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert path.read_text() == baseline.text
        if stage == "before-save":
            assert not state.exists()

    def test_unrelated_installed_change_after_publish_is_uncertain(
        self, linked_installation, monkeypatch
    ):
        selected, root, installed = linked_installation
        path, state = selected
        installed.unlink()
        installed.write_text("unrelated installed data")
        baseline = source.observe(path, state, config_root=root)
        proposal = changed(baseline.config, flags=("disabled",))
        review = source.prepare_review(baseline, proposal)
        write = persistence._atomic_write

        def atomic(target, raw, **kwargs):
            write(target, raw, **kwargs)
            if target == path:
                installed.write_text("external edit must not be masked as our replacement")

        monkeypatch.setattr(persistence, "_atomic_write", atomic)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and result.may_have_written
        assert result.baseline is None

    def test_reassigned_disabled_key_persists_and_reenable_refuses_without_losing_draft(
        self, selected
    ):
        path, state = selected
        path.with_name(source.BRIDGE_BASENAME).write_bytes(
            BUNDLE.with_name(source.BRIDGE_BASENAME).read_bytes()
        )
        baseline = source.observe(path, state)
        rows = baseline.config.bindings
        proposal = replace(
            baseline.config,
            bindings=(
                replace(rows[0], key="win + t"),
                replace(rows[1], flags=("disabled",)),
                *rows[2:],
            ),
        )
        result = source.persist_reviewed(source.prepare_review(baseline, proposal), proposal)
        assert result.outcome == "saved", result.error
        reopened = source.observe(path, state)
        assert reopened.config == proposal
        saved = path.read_bytes()
        with pytest.raises(ValueError, match="Duplicate"):
            replace(proposal, bindings=(proposal.bindings[0], rows[1], *rows[2:]))
        assert path.read_bytes() == saved
        assert source.build_text(proposal).encode() == saved
        assert not proposal.bindings[1].enabled and proposal.bindings[1].key == "SUPER + T"

    def test_disable_save_reopen_reenable_exact_bytes(self, selected, monkeypatch):
        path, state = selected
        original = path.read_bytes()
        bridge = path.with_name(source.BRIDGE_BASENAME)
        bridge.write_bytes(BUNDLE.with_name(source.BRIDGE_BASENAME).read_bytes())
        path.with_name("hyprland.lua").write_text("must never open main Lua")
        open_file = source.os.open

        def guarded_open(target, *args, **kwargs):
            assert Path(target).name != "hyprland.lua"
            return open_file(target, *args, **kwargs)

        monkeypatch.setattr(source.os, "open", guarded_open)
        baseline = source.run_observe(path, state)
        rows = baseline.config.bindings
        proposal = replace(
            baseline.config, bindings=(rows[0], replace(rows[1], flags=("disabled",)), *rows[2:])
        )
        review = source.run_prepare_review(baseline, proposal)
        assert source.SourceReview.from_json(review.to_json()) == review
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "saved", result.error
        reopened = source.observe(path, state)
        assert reopened.config == proposal and len(reopened.config.bindings) == 80
        assert reopened.config.bindings[1].key == "SUPER + T"
        assert not reopened.config.bindings[1].enabled
        assert source.fixed_metadata(reopened.config) == source.fixed_metadata(baseline.config)
        result = source.persist_reviewed(
            source.prepare_review(reopened, baseline.config), baseline.config
        )
        assert result.outcome == "saved", result.error
        assert path.read_bytes() == original

    @pytest.mark.parametrize("stage", ["before-save", "under-lock", "final-publish"])
    def test_capability_drift_invalidates_review(self, selected, monkeypatch, stage):
        path, state = selected
        bridge = path.with_name(source.BRIDGE_BASENAME)
        bridge.write_bytes(BUNDLE.with_name(source.BRIDGE_BASENAME).read_bytes())
        baseline = source.observe(*selected)
        proposal = changed(baseline.config, flags=("disabled",))
        review = source.prepare_review(baseline, proposal)

        def drift():
            bridge.write_text("-- old bridge\n")

        if stage == "before-save":
            drift()
        elif stage == "under-lock":
            flock = source.fcntl.flock

            def acquire(fd, flags):
                flock(fd, flags)
                drift()

            monkeypatch.setattr(source.fcntl, "flock", acquire)
        else:
            write = persistence._atomic_write

            def atomic(target, raw, **kwargs):
                if target == path:
                    drift()
                write(target, raw, **kwargs)

            monkeypatch.setattr(persistence, "_atomic_write", atomic)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert path.read_text() == baseline.text
        if stage == "before-save":
            assert not state.exists()

    def test_bridge_alias_to_main_is_not_read(self, selected, monkeypatch):
        path, state = selected
        main = path.with_name("hyprland.lua")
        main.write_text(source.BRIDGE_CAPABILITY + "\n")
        path.with_name(source.BRIDGE_BASENAME).symlink_to(main)
        baseline = source.observe(*selected)
        proposal = changed(baseline.config, flags=("disabled",))
        open_file = source.os.open

        def guarded_open(target, *args, **kwargs):
            assert Path(target) == path
            return open_file(target, *args, **kwargs)

        monkeypatch.setattr(source.os, "open", guarded_open)
        with pytest.raises(ValueError, match="Update the source keybindings bridge"):
            source.prepare_review(baseline, proposal)
        assert not state.exists()

    @pytest.mark.parametrize("relative", PROTECTED)
    @pytest.mark.parametrize("stage", ["before-save", "under-lock", "final-publish"])
    def test_actual_config_alias_introduced_after_review(
        self, selected, tmp_path, monkeypatch, relative, stage
    ):
        path, state = selected
        root = tmp_path / "actual-config"
        protected = root / relative
        protected.parent.mkdir(parents=True)
        other = tmp_path / "authored-content"
        other.write_text("never read or executed")
        protected.symlink_to(other)
        baseline = source.observe(path, state, config_root=root)
        proposal = changed(baseline.config, description="attempted edit")
        review = source.prepare_review(baseline, proposal)
        # Review and Save must retain the explicit context rather than re-read the environment.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "unrelated-config"))

        def introduce_alias():
            protected.unlink()
            protected.symlink_to(path)

        if stage == "before-save":
            introduce_alias()
        elif stage == "under-lock":
            flock = source.fcntl.flock

            def acquire(fd, flags):
                flock(fd, flags)
                introduce_alias()

            monkeypatch.setattr(source.fcntl, "flock", acquire)
        else:
            write = persistence._atomic_write

            def atomic(target, raw, **kwargs):
                if target == path:
                    introduce_alias()
                write(target, raw, **kwargs)

            monkeypatch.setattr(persistence, "_atomic_write", atomic)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed", result
        assert result.baseline is None and not result.may_have_written
        assert path.read_text() == baseline.text
        assert not tuple(path.parent.glob(".attune-*"))
        if stage == "before-save":
            assert not state.exists()
        elif stage == "under-lock":
            assert not (state / "attune/source-bindings-backups").exists()
        else:
            assert result.backup_path is not None
            assert not tuple((state / "attune/source-bindings-backups").glob(".attune-*"))

    @pytest.mark.parametrize("relative", PROTECTED)
    def test_actual_config_alias_introduced_before_review(self, selected, tmp_path, relative):
        root = tmp_path / "actual-config"
        protected = root / relative
        protected.parent.mkdir(parents=True)
        baseline = source.observe(*selected, config_root=root)
        protected.symlink_to(selected[0])
        with pytest.raises(ValueError, match="collid|alias"):
            source.prepare_review(baseline, baseline.config)
        assert not selected[1].exists()

    def test_protected_metadata_changed_without_collision_is_stale(self, selected, tmp_path):
        root = tmp_path / "actual-config"
        protected = root / "hypr/hyprland.lua"
        protected.parent.mkdir(parents=True)
        protected.write_text("before")
        baseline = source.observe(*selected, config_root=root)
        proposal = changed(baseline.config, description="edited")
        review = source.prepare_review(baseline, proposal)
        protected.write_text("after")
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.baseline is None and not selected[1].exists()

    def test_legitimate_actual_config_stow_source_and_repeated_save(self, selected, tmp_path):
        root = tmp_path / "actual-config"
        (root / "hypr").mkdir(parents=True)
        link = root / "hypr/keybindings.tsv"
        link.symlink_to(selected[0])
        (root / "hypr/hyprland.lua").write_text("authored content remains separate")
        baseline = source.observe(*selected, config_root=root)
        for description in ("First save", "Second save"):
            proposal = changed(baseline.config, description=description)
            result = source.persist_reviewed(source.prepare_review(baseline, proposal), proposal)
            assert result.outcome == "saved", result.error
            if result.baseline is None:
                pytest.fail("Missing verified baseline")
            baseline = result.baseline
            assert baseline.config_root == str(root)
        assert link.is_symlink()
        assert link.read_text() == baseline.text

    def test_same_bytes_external_replacement_is_stale(self, selected):
        review, proposal = draft(selected)
        path = selected[0]
        replacement = path.with_name("external-replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(path)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.baseline is None and not selected[1].exists()

    def test_parent_stow_link_preserved(self, selected, tmp_path):
        path, state = selected
        directory = tmp_path / "source-directory"
        path.parent.rename(directory)
        path.parent.symlink_to(directory, target_is_directory=True)
        link_before = path.parent.lstat()
        review, proposal = draft(selected)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "saved", result.error
        assert path.parent.lstat() == link_before
        assert (directory / source.BASENAME).read_text() == source.build_text(proposal)

    @pytest.mark.parametrize("kind", ["symlink", "foreign", "mode", "hardlink"])
    def test_unsafe_existing_backup(self, selected, tmp_path, kind):
        review, proposal = draft(selected)
        directory = selected[1] / "attune/source-bindings-backups"
        directory.mkdir(parents=True, mode=0o700)
        directory.parent.chmod(0o700)
        backup = directory / (review.baseline.sha256 + ".tsv")
        if kind == "symlink":
            backup.symlink_to(selected[0])
        else:
            backup.write_text("foreign" if kind == "foreign" else review.baseline.text)
            backup.chmod(0o644 if kind == "mode" else 0o600)
            if kind == "hardlink":
                os.link(backup, tmp_path / "backup-alias")
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.baseline is None and selected[0].read_text() == review.baseline.text
        assert not (directory.parent / "source-bindings.lock").exists()

    def test_existing_verified_backup_is_reused(self, selected):
        review, proposal = draft(selected)
        directory = selected[1] / "attune/source-bindings-backups"
        directory.mkdir(parents=True, mode=0o700)
        directory.parent.chmod(0o700)
        backup = directory / (review.baseline.sha256 + ".tsv")
        backup.write_text(review.baseline.text)
        backup.chmod(0o600)
        identity = backup.stat()
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "saved", result.error
        assert backup.stat() == identity

    @pytest.mark.parametrize("kind", ["state-symlink", "backup-symlink", "public-state"])
    def test_unsafe_storage_refused(self, selected, tmp_path, kind):
        review, proposal = draft(selected)
        state = selected[1]
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        if kind == "state-symlink":
            state.symlink_to(elsewhere, target_is_directory=True)
        else:
            (state / "attune").mkdir(parents=True, mode=0o700)
            if kind == "public-state":
                (state / "attune").chmod(0o755)
            else:
                (state / "attune/source-bindings-backups").symlink_to(elsewhere)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert not (state / "attune/source-bindings.lock").exists()
        assert not tuple(elsewhere.iterdir())

    @pytest.mark.parametrize("kind", ["lock", "state", "source-retarget"])
    def test_identity_changes_during_lock_acquisition(self, selected, monkeypatch, tmp_path, kind):
        path, state = selected
        if kind == "source-retarget":
            actual = tmp_path / "actual/keybindings.tsv"
            actual.parent.mkdir()
            path.rename(actual)
            path.symlink_to(actual)
            other = tmp_path / "other/keybindings.tsv"
            other.parent.mkdir()
            other.write_bytes(actual.read_bytes())
        review, proposal = draft(selected)
        original = source.fcntl.flock

        def acquire(fd, flags):
            original(fd, flags)
            if kind == "lock":
                lock = state / "attune/source-bindings.lock"
                lock.rename(lock.with_name("old-lock"))
                lock.touch(mode=0o600)
            elif kind == "state":
                (state / "attune").rename(state / "old-attune")
                (state / "attune").mkdir(mode=0o700)
                (state / "attune/source-bindings.lock").touch(mode=0o600)
            else:
                path.unlink()
                path.symlink_to(tmp_path / "other/keybindings.tsv")

        monkeypatch.setattr(source.fcntl, "flock", acquire)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.baseline is None
        assert not (state / "attune/source-bindings-backups").exists()

    def test_backup_tamper_before_final_publish(self, selected, monkeypatch):
        review, proposal = draft(selected)
        original = persistence._atomic_write

        def write(path, raw, **kwargs):
            if path == selected[0]:
                backup = (
                    selected[1]
                    / "attune/source-bindings-backups"
                    / (review.baseline.sha256 + ".tsv")
                )
                backup.write_text("tampered")
            original(path, raw, **kwargs)

        monkeypatch.setattr(persistence, "_atomic_write", write)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.baseline is None
        assert selected[0].read_text() == review.baseline.text

    def test_real_rename_then_fsync_failure_is_sticky(self, selected, monkeypatch):
        review, proposal = draft(selected)
        fsync, rename = os.fsync, os.replace
        published = False

        def replace_file(src, dst):
            nonlocal published
            rename(src, dst)
            if Path(dst) == selected[0]:
                published = True

        def sync(fd):
            if published:
                raise OSError("directory sync after successful rename")
            fsync(fd)

        monkeypatch.setattr(persistence.os, "replace", replace_file)
        monkeypatch.setattr(persistence.os, "fsync", sync)
        result = source.persist_reviewed(review, proposal)
        assert published
        assert result.outcome == "failed" and result.may_have_written
        assert result.baseline is None and result.backup_path is not None
        assert selected[0].read_text() == source.build_text(proposal)

    def test_save_repeat_noop_private_durable_backup(self, selected):
        path, state = selected
        original = path.read_bytes()
        review, proposal = draft(selected)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "saved", result.error
        assert result.may_have_written and result.baseline == source.observe(*selected)
        assert result.backup_path == str(
            state / "attune/source-bindings-backups" / (review.baseline.sha256 + ".tsv")
        )
        if result.backup_path is None or result.baseline is None:
            pytest.fail("Missing verified save evidence")
        backup = Path(result.backup_path)
        assert backup.read_bytes() == original
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600
        assert stat.S_IMODE(backup.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(backup.parent.parent.stat().st_mode) == 0o700
        assert sorted(p.name for p in backup.parent.parent.iterdir()) == [
            "source-bindings-backups",
            "source-bindings.lock",
        ]
        second = changed(proposal, description="Second save")
        result2 = source.persist_reviewed(source.prepare_review(result.baseline, second), second)
        assert result2.outcome == "saved", result2.error
        if result2.baseline is None:
            pytest.fail("Missing repeated Save baseline")
        before = path.stat()
        backups = tuple(backup.parent.iterdir())
        noop = source.persist_reviewed(source.prepare_review(result2.baseline, second), second)
        assert noop.outcome == "no-op", noop.error
        assert not noop.may_have_written and noop.backup_path is None
        assert path.stat() == before
        assert tuple(backup.parent.iterdir()) == backups

    def test_fresh_noop_no_backup_or_replacement(self, selected, monkeypatch):
        baseline = source.observe(*selected)
        monkeypatch.setattr(persistence, "_atomic_write", lambda *a, **k: pytest.fail("write"))
        result = source.persist_reviewed(
            source.prepare_review(baseline, baseline.config), baseline.config
        )
        assert result.outcome == "no-op", result.error
        assert not (selected[1] / "attune/source-bindings-backups").exists()

    def test_stow_git_source_and_same_bytes_retarget(self, selected, tmp_path):
        path, state = selected
        repo = tmp_path / "dotfiles"
        repo.mkdir()
        (repo / ".git").mkdir()
        target = repo / source.BASENAME
        path.rename(target)
        path.symlink_to(target)
        review, proposal = draft(selected)
        assert source.persist_reviewed(review, proposal).outcome == "saved"
        assert path.is_symlink() and path.read_text() == source.build_text(proposal)
        review, proposal = draft(selected)
        other = repo / "other"
        other.mkdir()
        other_target = other / source.BASENAME
        other_target.write_bytes(target.read_bytes())
        path.unlink()
        path.symlink_to(other_target)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.baseline is None

    @pytest.mark.parametrize("location", ["root", "attune", "backups"])
    @pytest.mark.parametrize("marker_kind", ["file", "directory"])
    def test_git_backup_root_and_ancestors_refused(self, selected, location, marker_kind):
        review, proposal = draft(selected)
        state = selected[1]
        root = {
            "root": state,
            "attune": state / "attune",
            "backups": state / "attune/source-bindings-backups",
        }[location]
        root.mkdir(parents=True, mode=0o700)
        if (state / "attune").exists():
            (state / "attune").chmod(0o700)
        marker = root / ".git"
        if marker_kind == "directory":
            marker.mkdir()
        else:
            marker.write_text("gitdir: elsewhere\n")
        before = selected[0].read_bytes()
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.baseline is None and selected[0].read_bytes() == before
        assert not (state / "attune/source-bindings.lock").exists()

    def test_stale_under_lock(self, selected, monkeypatch):
        review, proposal = draft(selected)
        original = source.fcntl.flock

        def flock(fd, flags):
            original(fd, flags)
            selected[0].write_text(
                source.build_text(changed(review.baseline.config, description="external"))
            )

        monkeypatch.setattr(source.fcntl, "flock", flock)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert result.baseline is None
        assert not (selected[1] / "attune/source-bindings-backups").exists()

    @pytest.mark.parametrize("stage", ["backup", "final-check", "rename", "sync", "postread"])
    def test_failure_uncertainty_and_no_old_baseline(self, selected, monkeypatch, stage):
        review, proposal = draft(selected)
        original = persistence._atomic_write
        observe = source.observe

        def write(path, raw, **kwargs):
            if path == selected[0]:
                if stage == "final-check":
                    selected[0].write_text(
                        source.build_text(changed(review.baseline.config, description="external"))
                    )
                if stage == "rename":
                    kwargs["before_replace"]()
                    raise OSError("rename uncertain")
                original(path, raw, **kwargs)
                if stage == "sync":
                    raise OSError("directory fsync failed after rename")
            elif stage == "backup":
                raise OSError("backup failed")
            else:
                original(path, raw, **kwargs)

        def postread(path, state, **kwargs):
            if stage == "postread" and path.read_text() == source.build_text(proposal):
                raise ValueError("postread unavailable")
            return observe(path, state, **kwargs)

        monkeypatch.setattr(persistence, "_atomic_write", write)
        monkeypatch.setattr(source, "observe", postread)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed", result
        assert result.baseline is None
        assert result.may_have_written == (stage in {"rename", "sync", "postread"})
        if stage == "backup":
            assert result.backup_path is None
            assert selected[0].read_text() == review.baseline.text

    def test_backup_fsync_failure_blocks_output(self, selected, monkeypatch):
        review, proposal = draft(selected)

        def fail(fd):
            raise OSError("fsync failed")

        monkeypatch.setattr(source.os, "fsync", fail)
        result = source.persist_reviewed(review, proposal)
        assert result.outcome == "failed" and not result.may_have_written
        assert selected[0].read_text() == review.baseline.text

    def test_cancel_and_daemon_have_no_side_effects(self, selected):
        review, proposal = draft(selected)
        cancel = threading.Event()
        cancel.set()
        result = source.persist_reviewed(review, proposal, cancel_event=cancel)
        assert result.outcome == "failed" and not result.may_have_written
        results = []
        worker = threading.Thread(
            target=lambda: results.append(source.persist_reviewed(review, proposal)), daemon=True
        )
        worker.start()
        worker.join(5)
        assert results[0].outcome == "failed"
        assert not selected[1].exists()

    def test_failed_result_cannot_adopt_baseline(self, selected):
        baseline = source.observe(*selected)
        with pytest.raises(ValueError):
            source.SourceSaveResult("failed", baseline, None, False, "failure")
        with pytest.raises(ValueError):
            source.SourceSaveResult("saved", baseline, None, True, None)


class TestWorkers:
    @pytest.mark.parametrize("relative", PROTECTED)
    def test_actual_worker_refuses_default_config_alias(
        self, selected, tmp_path, monkeypatch, relative
    ):
        root = tmp_path / "actual-config"
        protected = root / relative
        protected.parent.mkdir(parents=True)
        protected.symlink_to(selected[0])
        monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
        with pytest.raises(ValueError, match="collid|alias"):
            source.run_observe(*selected)
        assert not selected[1].exists()

    def test_default_root_captured_before_child_and_explicit_echo(
        self, selected, tmp_path, monkeypatch
    ):
        root = tmp_path / "actual-config"
        (root / "hypr").mkdir(parents=True)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
        run = health.run_bounded

        def launch(command, **kwargs):
            assert command[command.index("--config-root") + 1] == str(root)
            monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "child-environment"))
            return run(command, **kwargs)

        monkeypatch.setattr(health, "run_bounded", launch)
        baseline = source.run_observe(*selected)
        assert baseline.config_root == str(root)
        proposal = changed(baseline.config, description="worker review")
        assert source.run_prepare_review(baseline, proposal).baseline == baseline
        wrong = source.observe(*selected, config_root=tmp_path / "wrong-root")

        def wrong_context(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, wrong.to_json(), "")

        monkeypatch.setattr(health, "run_bounded", wrong_context)
        with pytest.raises(ValueError, match="context"):
            source.run_observe(*selected, config_root=root)

    def test_review_worker_rejects_different_cli_config_root(self, selected, tmp_path):
        baseline = source.observe(*selected, config_root=tmp_path / "actual-config")
        request = route_approval._json(
            {"baseline": asdict(baseline), "proposal": asdict(baseline.config)}
        )
        result = health.run_bounded(
            [
                sys.executable,
                "-I",
                "-B",
                "-m",
                "hyprmod.core.source_bindings",
                "review",
                "--path",
                baseline.lexical_path,
                "--state-root",
                baseline.state_root,
                "--config-root",
                str(tmp_path / "wrong-root"),
            ],
            input_text=request,
            timeout=15,
            max_bytes=source.MAX_TRANSPORT_BYTES,
            process_group=True,
        )
        assert result.returncode != 0 and "context differs" in result.stderr
        assert not selected[1].exists()

    def test_actual_stdin_byte_limit(self, selected):
        baseline = source.observe(*selected)
        request = route_approval._json(
            {"baseline": asdict(baseline), "proposal": asdict(baseline.config)}
        )
        command = [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.source_bindings",
            "review",
            "--path",
            str(selected[0]),
            "--state-root",
            str(selected[1]),
            "--config-root",
            baseline.config_root,
        ]
        result = health.run_bounded(
            command,
            input_text=" " * (source.MAX_TRANSPORT_BYTES + 1) + request,
            timeout=15,
            max_bytes=2 * source.MAX_TRANSPORT_BYTES,
            process_group=True,
        )
        assert result.returncode != 0 and "transport exceeds limit" in result.stderr
        assert not selected[1].exists()

    def test_actual_read_workers_and_stdin(self, selected):
        baseline = source.run_observe(*selected)
        assert baseline == source.observe(*selected)
        proposal = changed(baseline.config, key="SHIFT + F24", description="worker data")
        review = source.run_prepare_review(baseline, proposal)
        assert review == source.prepare_review(baseline, proposal)
        assert not selected[1].exists()

    def test_actual_cancel(self, selected):
        event = threading.Event()
        event.set()
        with pytest.raises(InterruptedError):
            source.run_observe(*selected, cancel_event=event)
        baseline = source.observe(*selected)
        with pytest.raises(InterruptedError):
            source.run_prepare_review(baseline, baseline.config, cancel_event=event)

    @pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
    def test_invalid_timeout(self, selected, timeout):
        with pytest.raises(ValueError):
            source.run_observe(*selected, timeout=timeout)

    def test_context_echo_and_supervision(self, selected, monkeypatch, tmp_path):
        baseline = source.observe(*selected)
        other = tmp_path / "other/keybindings.tsv"
        other.parent.mkdir()
        other.write_text(baseline.text)
        wrong = source.observe(other, selected[1])
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            assert command[1:3] == ["-I", "-B"]
            assert kwargs["process_group"] is True
            assert kwargs["max_bytes"] == source.MAX_TRANSPORT_BYTES
            return subprocess.CompletedProcess(command, 0, wrong.to_json(), "")

        monkeypatch.setattr(health, "run_bounded", run)
        with pytest.raises(ValueError, match="context"):
            source.run_observe(*selected)
        proposal = changed(baseline.config, key="F24")
        wrong_review = source.prepare_review(baseline, changed(proposal, description="wrong"))

        def review_run(command, **kwargs):
            request = json.loads(kwargs["input_text"])
            assert request["proposal"] == json.loads(route_approval._json(asdict(proposal)))
            return subprocess.CompletedProcess(command, 0, wrong_review.to_json(), "")

        monkeypatch.setattr(health, "run_bounded", review_run)
        with pytest.raises(ValueError, match="different review"):
            source.run_prepare_review(baseline, proposal)
        assert len(commands) == 1

    def test_cli_context_mismatch_and_no_mutator_mode(self, selected):
        baseline = source.observe(*selected)
        request = route_approval._json(
            {"baseline": asdict(baseline), "proposal": asdict(baseline.config)}
        )
        command = [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "hyprmod.core.source_bindings",
            "review",
            "--path",
            str(selected[0]),
            "--state-root",
            str(selected[1] / "wrong"),
            "--config-root",
            baseline.config_root,
        ]
        result = health.run_bounded(
            command,
            input_text=request,
            timeout=15,
            max_bytes=source.MAX_TRANSPORT_BYTES,
            process_group=True,
        )
        assert result.returncode != 0 and "context" in result.stderr
        command[5] = "save"
        result = health.run_bounded(command, timeout=15, max_bytes=4096, process_group=True)
        assert result.returncode != 0
        assert not selected[1].exists()
