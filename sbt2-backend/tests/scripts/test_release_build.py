import os
import subprocess
from pathlib import Path

import pytest

LIB = Path(__file__).parents[3] / "scripts" / "release-lib.sh"
TOKENS = {"GH_TOKEN": "gh-secret", "GHCR_TOKEN": "ghcr-secret"}
PROBE = 'echo "$GH_TOKEN|$GHCR_TOKEN|$CARGO_BUILD_JOBS|$(nice)|$(ionice)"'


def build_sees(extra: dict[str, str]) -> list[str]:
    done = subprocess.run(
        ["bash", "-c", f". \"{LIB}\" && run_build sh -c '{PROBE}'"],
        env=os.environ | TOKENS | extra,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip().split("|")


@pytest.mark.unit
def test_a_build_runs_without_the_tokens_at_the_lowest_priority() -> None:
    gh, ghcr, _, niceness, io_class = build_sees({})

    assert (gh, ghcr) == ("", "")
    assert niceness == "19"
    assert io_class == "idle"


@pytest.mark.unit
def test_a_build_uses_half_the_cores_unless_told_otherwise() -> None:
    # nproc counts the cores this process may use, as process_cpu_count does
    half = str(((os.process_cpu_count() or 1) + 1) // 2)

    assert build_sees({})[2] == half
    assert build_sees({"SBT2_BUILD_JOBS": "3"})[2] == "3"
