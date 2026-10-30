"""Attune's supported UI scope and exact pending-review snapshot."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

SCHEMA_PAGES = ("general", "decoration", "animations")
SECTION_PAGES = ("monitors",)
UTILITY_PAGES = ("pending", "health", "backups", "scope-recovery", "settings")
PAGE_IDS = frozenset((*SCHEMA_PAGES, *SECTION_PAGES, *UTILITY_PAGES, "search"))
GENERAL_OPTIONS = frozenset(
    (
        "general:gaps_in",
        "general:gaps_out",
        "general:border_size",
        "general:col.active_border",
        "general:col.inactive_border",
    )
)


def filter_schema(catalog: dict) -> dict:
    """Filter before building pages, state, and the search index."""
    focused = deepcopy(catalog)
    groups = []
    for group in focused.get("groups", []):
        group_id = group["id"]
        if group_id not in SCHEMA_PAGES:
            continue
        sections = []
        for section in group.get("sections", []):
            section["options"] = [
                option
                for option in section.get("options", [])
                if (
                    option["key"] in GENERAL_OPTIONS
                    if group_id == "general"
                    else option["key"].startswith(f"{group_id}:")
                )
            ]
            if section["options"]:
                sections.append(section)
        if sections:
            group["sections"] = sections
            group.pop("parent_page", None)
            group.pop("hidden", None)
            groups.append(group)
    focused["groups"] = groups
    return focused


@dataclass(frozen=True)
class ReviewSnapshot:
    path: Path
    saved_text: str
    proposed_text: str
    resolved_path: Path | None = None
