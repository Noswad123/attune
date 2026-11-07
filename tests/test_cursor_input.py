"""Cursor shares the reviewed Input model, file, lock and publisher."""

from pathlib import Path

import pytest

from hyprmod.core import input as device
from hyprmod.core import persistence
from tests.test_input_persistence import INPUT_ONLY_TEXT

CURSOR_SPECS = {
    "cursor:no_warps": device.OptionSpec(bool, False),
    "cursor:persistent_warps": device.OptionSpec(bool, False),
    "cursor:warp_on_change_workspace": device.OptionSpec(int, 0, 0, 2, choices=(0, 1, 2)),
    "cursor:zoom_factor": device.OptionSpec(float, 1.0, 1, 10),
    "cursor:inactive_timeout": device.OptionSpec(float, 0.0, 0, 20),
    "cursor:hide_on_key_press": device.OptionSpec(bool, False),
    "cursor:hide_on_touch": device.OptionSpec(bool, True),
    "cursor:hide_on_tablet": device.OptionSpec(bool, False),
}
CURSOR_BODY = """    cursor = {
        hide_on_key_press = false,
        hide_on_tablet = false,
        hide_on_touch = true,
        inactive_timeout = 0.0,
        no_warps = false,
        persistent_warps = false,
        warp_on_change_workspace = 0,
        zoom_factor = 1.0,
    },
"""


@pytest.fixture
def roots(tmp_path):
    config = tmp_path / "config"
    (config / "hypr").mkdir(parents=True)
    return config, tmp_path / "state"


class TestCursorConfig:
    def test_upstream_specs_and_closed_allowlist(self):
        # Hyprland v0.56.1 src/config/values/ConfigValues.cpp, not UI increments.
        assert device.CURSOR_KEYS == frozenset(CURSOR_SPECS)
        assert {key: device.OPTION_SPECS[key] for key in device.CURSOR_KEYS} == CURSOR_SPECS
        assert len(device.INPUT_KEYS) == 23
        for key, spec in CURSOR_SPECS.items():
            assert type(device.DEFAULTS[key]) is spec.value_type

    @pytest.mark.parametrize("key", [k for k, s in CURSOR_SPECS.items() if s.value_type is bool])
    def test_boolean_nondefaults_roundtrip(self, key):
        value = not device.DEFAULTS[key]
        config = device.InputConfig(((key, value),))
        assert dict(config.values)[key] is value
        assert device.read_text(device.build_text(config)) == config

    @pytest.mark.parametrize("value", [0, 1, 2])
    def test_integer_choices(self, value):
        config = device.InputConfig((("cursor:warp_on_change_workspace", value),))
        assert type(dict(config.values)["cursor:warp_on_change_workspace"]) is int
        assert device.read_text(device.build_text(config)) == config

    @pytest.mark.parametrize("value", [-1, 3, "0", "1", "2", "force", 0.0, 1.0, 2.0, True, False])
    def test_invalid_integer_choices(self, value):
        with pytest.raises(ValueError):
            device.InputConfig((("cursor:warp_on_change_workspace", value),))

    @pytest.mark.parametrize("key", ["cursor:zoom_factor", "cursor:inactive_timeout"])
    @pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 10**400])
    def test_nonfinite_float_refused(self, key, value):
        with pytest.raises(ValueError):
            device.InputConfig(((key, value),))

    @pytest.mark.parametrize(
        "key,value", [("cursor:zoom_factor", 2.35), ("cursor:inactive_timeout", 0.25)]
    )
    def test_ui_increments_are_not_model_restrictions(self, key, value):
        assert device.OPTION_SPECS[key].step is None
        config = device.InputConfig(((key, value),))
        assert dict(config.values)[key] == value
        assert device.read_text(device.build_text(config)) == config

    @pytest.mark.parametrize(
        "key",
        [
            "cursor:theme",
            "cursor:size",
            "cursor:no_hardware_cursors",
            "cursor:invisible",
            "cursor:default_monitor",
            "cursor:warp_on_toggle_special",
            "cursor:zoom_rigid",
            "cursor:enable_hyprcursor",
            "cursor:unknown",
        ],
    )
    def test_unknown_cursor_options_refused(self, key):
        with pytest.raises(ValueError, match="Unknown input option"):
            device.InputConfig(((key, True),))


class TestCursorCodec:
    def test_exact_whole_batch_and_typed_cursor_body(self):
        config = device.InputConfig.from_mapping(device.DEFAULTS)
        text = device.build_text(config)
        expected_body = INPUT_ONLY_TEXT.split("\n", 2)[2].replace(
            "hl.config({\n", "hl.config({\n" + CURSOR_BODY, 1
        )
        assert text.split("\n", 2)[2] == expected_body
        assert text.count("hl.config(") == 1
        assert device.read_text(text) == config
        persistence.validate_lua(text)

    @pytest.mark.parametrize(
        "key,value,wrong",
        [
            ("cursor:no_warps", False, "0"),
            ("cursor:warp_on_change_workspace", 1, "true"),
            ("cursor:zoom_factor", 2.35, '"2.35"'),
            ("cursor:inactive_timeout", 0.25, "0"),
        ],
    )
    def test_public_leaf_emitter_must_prove_exact_type_and_value(
        self, monkeypatch, key, value, wrong
    ):
        original = device.keyword_to_lua
        leaf = key.rsplit(":", 1)[1]
        snippet = original(key, str(value).lower())
        corrupted = snippet.replace(f"{leaf} = {str(value).lower()},", f"{leaf} = {wrong},")
        assert corrupted != snippet
        monkeypatch.setattr(device, "keyword_to_lua", lambda *args: corrupted)
        with pytest.raises(ValueError, match="typed input emission"):
            device.build_text(device.InputConfig(((key, value),)))

    def test_metadata_cannot_mask_changed_cursor_body(self):
        text = device.build_text(device.InputConfig.from_mapping(device.DEFAULTS))
        with pytest.raises(ValueError, match="edited outside Attune"):
            device.read_text(text.replace("zoom_factor = 1.0,", "zoom_factor = 2.0,"))

    def test_pre_cursor_allowlist_rejects_forward_records(self, monkeypatch):
        text = device.build_text(device.InputConfig((("cursor:no_warps", True),)))
        monkeypatch.setattr(device, "INPUT_KEYS", device.INPUT_KEYS - device.CURSOR_KEYS)
        with pytest.raises(ValueError, match="Unknown input option"):
            device.read_text(text)


class TestCursorPersistence:
    def test_composite_workers_publish_edit_remove_and_reopen(self, roots):
        config_root, state_root = roots
        target = config_root / "hypr" / device.BASENAME
        target.write_text(INPUT_ONLY_TEXT)
        target.chmod(0o600)
        protected = target.with_name("attune-bindings.lua")
        protected.write_text("opaque sibling fixture\n")
        before = protected.read_bytes(), protected.stat()
        baseline = device.run_observe(*roots)
        assert baseline.text == INPUT_ONLY_TEXT
        assert not state_root.exists()

        values = dict(device.DEFAULTS)
        values.update({"cursor:zoom_factor": 2.35, "cursor:inactive_timeout": 0.25})
        proposals = [device.InputConfig.from_mapping(values)]
        values["input:repeat_rate"] = 30
        proposals.append(device.InputConfig.from_mapping(values))
        values["cursor:warp_on_change_workspace"] = 2
        proposals.append(device.InputConfig.from_mapping(values))
        values.pop("cursor:zoom_factor")
        proposals.append(device.InputConfig.from_mapping(values))
        proposals.append(device.InputConfig.from_mapping(dict(baseline.config.values)))

        for proposed in proposals:
            old_text = baseline.text
            review = device.run_prepare_review(baseline, proposed)
            assert device.InputReview.from_json(review.to_json()) == review
            assert device.InputBaseline.from_json(baseline.to_json()) == baseline
            assert not (config_root / "hypr" / "attune-cursor.lua").exists()
            saved = device.persist_reviewed(review, proposed)
            assert saved.outcome == "saved", saved.error
            assert device.InputSaveResult.from_json(saved.to_json()) == saved
            if saved.backup_path is None:
                pytest.fail("Missing composite Input backup")
            assert Path(saved.backup_path).parent == state_root / "attune/input-backups"
            assert Path(saved.backup_path).read_text() == old_text
            baseline = device.run_observe(*roots)
            assert baseline == saved.baseline
            assert baseline.config == proposed
            assert target.read_text() == review.proposed_text
            assert (protected.read_bytes(), protected.stat()) == before

        assert target.read_text() == INPUT_ONLY_TEXT
        assert "cursor" not in baseline.text
        assert {p.name for p in target.parent.iterdir()} == {device.BASENAME, protected.name}
        assert {p.name for p in (state_root / "attune").iterdir()} == {
            "input.lock",
            "input-backups",
        }
        noop = device.persist_reviewed(
            device.run_prepare_review(baseline, baseline.config), baseline.config
        )
        assert noop.outcome == "no-op", noop.error
