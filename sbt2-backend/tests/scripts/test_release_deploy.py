import os
import subprocess
from pathlib import Path

import pytest

LIB = Path(__file__).parents[3] / "scripts" / "release-lib.sh"
# set, so release-lib.sh takes nothing from the maintainer's .env
NO_TOKENS = {"GH_TOKEN": "unused", "GHCR_TOKEN": "unused"}


def fake(bin_dir: Path, name: str, status: int) -> None:
    command = bin_dir / name
    command.write_text(f'#!/bin/sh\necho "{name} $*" >>"$FAKE_LOG"\nexit {status}\n')
    command.chmod(0o755)


def deploy(
    tmp_path: Path, *, service: int, update: int
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake(bin_dir, "systemctl", service)
    fake(bin_dir, "podman", update)
    path = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_LOG": str(tmp_path / "log"),
    }
    return subprocess.run(
        ["bash", "-c", f'. "{LIB}" && deploy'],
        env=os.environ | NO_TOKENS | path,
        check=False,
        capture_output=True,
        text=True,
    )


def calls(tmp_path: Path) -> list[str]:
    return (tmp_path / "log").read_text().splitlines()


@pytest.mark.unit
def test_deploy_runs_podman_auto_update(tmp_path: Path) -> None:
    done = deploy(tmp_path, service=0, update=0)

    assert done.returncode == 0
    assert "podman auto-update" in calls(tmp_path)


@pytest.mark.unit
def test_deploy_skips_without_a_server_service(tmp_path: Path) -> None:
    done = deploy(tmp_path, service=1, update=0)

    assert done.returncode == 0
    assert not any(call.startswith("podman") for call in calls(tmp_path))
    assert "no sbt2-server service" in done.stderr


@pytest.mark.unit
def test_deploy_only_warns_when_the_update_fails(tmp_path: Path) -> None:
    done = deploy(tmp_path, service=0, update=1)

    assert done.returncode == 0
    assert "the deploy failed" in done.stderr
