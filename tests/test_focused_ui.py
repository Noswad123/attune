"""Policy tests without GTK or compositor access."""

from copy import deepcopy
from pathlib import Path

import pytest

from hyprmod.core.focused_ui import GENERAL_OPTIONS, PAGE_IDS, ReviewSnapshot, filter_schema
from hyprmod.core.schema import get_options_flat, load_schema


class TestFocusedSchema:
    def test_only_supported_groups_and_general_options(self):
        focused = filter_schema(load_schema())
        assert {group["id"] for group in focused["groups"]} == {
            "general",
            "decoration",
            "animations",
        }
        options = get_options_flat(focused)
        assert {key for key in options if key.startswith("general:")} == GENERAL_OPTIONS
        assert all(
            key in GENERAL_OPTIONS or key.startswith(("decoration:", "animations:"))
            for key in options
        )

    def test_does_not_mutate_shared_catalog(self):
        catalog = load_schema()
        original = deepcopy(catalog)
        focused = filter_schema(catalog)
        focused["groups"][0]["sections"][0]["options"][0]["label"] = "Changed"
        assert catalog == original

    def test_drops_empty_groups_and_hidden_page_redirects(self):
        catalog = {
            "groups": [
                {"id": "general", "sections": [{"options": [{"key": "general:layout"}]}]},
                {
                    "id": "decoration",
                    "hidden": True,
                    "parent_page": "profiles",
                    "sections": [{"options": [{"key": "decoration:rounding"}, {"key": "exec"}]}],
                },
                {"id": "plugin", "sections": [{"options": [{"key": "plugin:visual"}]}]},
            ]
        }
        groups = filter_schema(catalog)["groups"]
        assert len(groups) == 1
        assert groups[0] == {
            "id": "decoration",
            "sections": [{"options": [{"key": "decoration:rounding"}]}],
        }

    def test_all_registered_destinations_are_focused(self):
        assert PAGE_IDS == {
            "general",
            "decoration",
            "animations",
            "monitors",
            "pending",
            "health",
            "backups",
            "settings",
            "search",
        }


class TestReviewSnapshot:
    @pytest.mark.parametrize(
        ("path", "saved", "proposed"),
        [
            (Path("other.lua"), "old", "new"),
            (Path("attune.lua"), "external edit", "new"),
            (Path("attune.lua"), "old", "newer draft"),
        ],
    )
    def test_stale_when_any_reviewed_input_changes(self, path, saved, proposed):
        reviewed = ReviewSnapshot(Path("attune.lua"), "old", "new")
        assert reviewed != ReviewSnapshot(path, saved, proposed)

    def test_same_draft_and_destination_match(self):
        assert ReviewSnapshot(Path("attune.lua"), "old", "new") == ReviewSnapshot(
            Path("attune.lua"), "old", "new"
        )
