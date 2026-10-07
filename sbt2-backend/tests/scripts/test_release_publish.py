import os
import subprocess
from pathlib import Path

import pytest

LIB = Path(__file__).parents[3] / "scripts" / "release-lib.sh"
# set, so release-lib.sh takes nothing from the maintainer's .env
NO_TOKENS = {"GH_TOKEN": "unused", "GHCR_TOKEN": "unused"}
FAKE_GIT = """#!/bin/sh
case "$1" in
fetch) exit 0 ;;
rev-parse) echo "$FAKE_MAIN" ;;
esac
"""


def check_build(tmp_path: Path, built: str | None) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text(FAKE_GIT)
    git.chmod(0o755)
    build_dir = tmp_path / "release"
    if built is not None:
        build_dir.mkdir()
        (build_dir / "head").write_text(f"{built}\n")
    fakes = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_MAIN": "abc",
        "SBT2_RELEASE_DIR": str(build_dir),
    }
    return subprocess.run(
        ["bash", "-c", f'. "{LIB}" && check_build'],
        env=os.environ | NO_TOKENS | fakes,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.unit
def test_publish_refuses_without_a_build(tmp_path: Path) -> None:
    done = check_build(tmp_path, None)

    assert done.returncode != 0
    assert "run make build first" in done.stderr


@pytest.mark.unit
def test_publish_refuses_a_build_of_an_older_main(tmp_path: Path) -> None:
    done = check_build(tmp_path, "old")

    assert done.returncode != 0
    assert "origin/main moved since the build" in done.stderr


@pytest.mark.unit
def test_publish_accepts_a_build_of_the_current_main(tmp_path: Path) -> None:
    done = check_build(tmp_path, "abc")

    assert done.returncode == 0
