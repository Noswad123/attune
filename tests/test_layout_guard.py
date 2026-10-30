"""Metadata exclusion never reads Lua/registry bytes or creates state."""

import os
from pathlib import Path

import pytest

from hyprmod.core import layout_guard


class TestLayoutGuard:
    def test_absence_and_archives_are_clear(self, tmp_path, monkeypatch):
        config, state = tmp_path / "config", tmp_path / "state"
        monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("No byte reads"))
        assert layout_guard.block_reason(config, state) is None
        assert not config.exists() and not state.exists()
        for name in ("backups", "preserved"):
            (state / "attune" / name).mkdir(parents=True)
        assert layout_guard.block_reason(config, state) is None
        (state / "attune/transactions").mkdir(mode=0o700)
        assert layout_guard.block_reason(config, state) is None

    @pytest.mark.parametrize("kind", ["file", "directory", "symlink", "fifo"])
    def test_any_registry_blocks_without_open(self, tmp_path, monkeypatch, kind):
        registry = tmp_path / "config/attune/installation.json"
        registry.parent.mkdir(parents=True)
        if kind == "file":
            registry.write_bytes(b"malformed")
        elif kind == "directory":
            registry.mkdir()
        elif kind == "symlink":
            registry.symlink_to(tmp_path / "absent")
        else:
            os.mkfifo(registry)
        monkeypatch.setattr(Path, "open", lambda *_: pytest.fail("No byte reads"))
        assert layout_guard.block_reason(tmp_path / "config", tmp_path / "state")

    @pytest.mark.parametrize("kind", ["entry", "file", "symlink", "permissions"])
    def test_unsafe_or_nonempty_transactions_block(self, tmp_path, kind):
        directory = tmp_path / "state/attune/transactions"
        directory.parent.mkdir(parents=True)
        if kind == "file":
            directory.touch()
        elif kind == "symlink":
            directory.symlink_to(tmp_path / "absent")
        else:
            directory.mkdir(mode=0o700)
            if kind == "entry":
                (directory / "even-terminal-history").touch()
            else:
                directory.chmod(0)
        try:
            assert layout_guard.block_reason(tmp_path / "config", tmp_path / "state")
        finally:
            if kind == "permissions":
                directory.chmod(0o700)

    def test_symlink_parent_and_invalid_context_block(self, tmp_path):
        config = tmp_path / "config"
        config.symlink_to(tmp_path / "absent")
        assert layout_guard.block_reason(config, tmp_path / "state")
        assert layout_guard.block_reason(Path("relative"), tmp_path / "state")
