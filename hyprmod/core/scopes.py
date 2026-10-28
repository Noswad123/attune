"""Logical output identities for the inactive M3 split model."""

from enum import StrEnum
from types import MappingProxyType


class Scope(StrEnum):
    APPEARANCE = "appearance"
    DISPLAYS = "displays"


SCOPE_BASENAMES = MappingProxyType(
    {
        Scope.APPEARANCE: "attune-appearance.lua",
        Scope.DISPLAYS: "attune-displays.lua",
    }
)
