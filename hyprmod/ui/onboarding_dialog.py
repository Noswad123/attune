"""Informational welcome dialog without setup or configuration writes."""

from gi.repository import Adw

from hyprmod.core import config


class OnboardingDialog(Adw.AlertDialog):
    def __init__(self) -> None:
        super().__init__(
            heading="Welcome to Attune",
            body=(
                "Tune appearance, displays, and motion with live previews. "
                "Ctrl+S opens Pending Changes, where you review the exact diff before "
                "choosing Save Reviewed Changes.\n\n"
                f"Managed output: {config.managed_path()}\n\n"
                "After your first save, manually load that file from your Hyprland Lua "
                "entrypoint using dofile with its absolute path, after your appearance defaults. "
                "See Settings for integration details. Attune never modifies your entrypoint, "
                "inserts includes, migrates configuration, or reloads the compositor on startup."
            ),
        )
        self.add_response("close", "Continue")
        self.set_default_response("close")
        self.set_close_response("close")
