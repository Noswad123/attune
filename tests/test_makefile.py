"""Development launcher installation stays local and preserves the venv entrypoint."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def developer_launcher(tmp_path):
    venv = tmp_path / "development environment"
    launcher = venv / "bin" / "attune"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    return launcher


class TestMakeInstall:
    @pytest.mark.parametrize("target", ["install", "install-dev"])
    def test_installs_into_home_local_bin(self, developer_launcher, target):
        subprocess.run(
            ["make", "-C", str(ROOT), target, f"VENV={developer_launcher.parent.parent}"],
            check=True,
            capture_output=True,
            text=True,
        )
        installed = Path.home() / ".local" / "bin" / "attune"
        assert installed.read_bytes() == developer_launcher.read_bytes()
        assert os.access(installed, os.X_OK)
        assert not installed.is_symlink()
        assert not (Path.home() / ".local" / "share" / "applications").exists()

    def test_destination_and_staging_overrides(self, developer_launcher, tmp_path):
        staging = tmp_path / "staging root"
        subprocess.run(
            [
                "make",
                "-C",
                str(ROOT),
                "install",
                f"VENV={developer_launcher.parent.parent}",
                "BINDIR=/custom/bin",
                f"DESTDIR={staging}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert (staging / "custom" / "bin" / "attune").read_bytes() == (
            developer_launcher.read_bytes()
        )

    def test_missing_environment_fails_before_creating_destination(self, tmp_path):
        destination = tmp_path / "not installed"
        result = subprocess.run(
            [
                "make",
                "-C",
                str(ROOT),
                "install",
                f"VENV={tmp_path / 'missing'}",
                f"BINDIR={destination}",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "make build" in result.stderr
        assert not destination.exists()

    def test_build_uses_locked_environment_and_overridable_uv(self):
        result = subprocess.run(
            ["make", "-C", str(ROOT), "--dry-run", "build", "UV=/custom/uv"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert '"/custom/uv" sync --locked' in result.stdout
