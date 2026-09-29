import subprocess
import sys
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

MEMORY_MAX = "MemoryMax=100M"
NO_SWAP = "MemorySwapMax=0"
OVER_CAP_MB = 300
UNDER_CAP_MB = 20
# Writing the bytes, rather than bytearray(n), makes sure every page is resident.
ALLOCATE = """
import sys
block = b"x" * (int(sys.argv[1]) * 2**20)
print("survived")
"""


@pytest.fixture
def unit() -> Iterator[str]:
    name = f"sbt2-test-{uuid.uuid4().hex}"
    yield name
    reset_failed(name)


def reset_failed(unit: str) -> None:
    reset = ["systemctl", "--user", "reset-failed", f"{unit}.scope"]
    subprocess.run(reset, capture_output=True, check=False)


def allocate_in_scope(
    unit: str, properties: Sequence[str], megabytes: int
) -> subprocess.CompletedProcess[str]:
    flags = [f"--property={p}" for p in properties]
    command = ["systemd-run", "--user", "--scope", "--quiet", f"--unit={unit}", *flags]
    child = [sys.executable, "-c", ALLOCATE, str(megabytes)]
    return subprocess.run(
        command + child, capture_output=True, text=True, timeout=60, check=False
    )


def scope_property(unit: str, name: str) -> str:
    show = ["systemctl", "--user", "show", f"{unit}.scope", f"--property={name}"]
    output = subprocess.run(show, capture_output=True, text=True, check=True).stdout
    return output.strip().removeprefix(f"{name}=")


@pytest.mark.characterization
@pytest.mark.systemd
@pytest.mark.unit
def test_a_child_over_the_cap_is_killed_with_sigkill(unit: str) -> None:
    result = allocate_in_scope(unit, [MEMORY_MAX, NO_SWAP], OVER_CAP_MB)

    assert result.returncode == -9
    assert "survived" not in result.stdout


@pytest.mark.characterization
@pytest.mark.systemd
@pytest.mark.unit
def test_a_killed_scope_reports_oom_kill_as_its_result(unit: str) -> None:
    allocate_in_scope(unit, [MEMORY_MAX, NO_SWAP], OVER_CAP_MB)

    assert scope_property(unit, "Result") == "oom-kill"


@pytest.mark.characterization
@pytest.mark.systemd
@pytest.mark.unit
def test_a_child_under_the_cap_runs_to_completion(unit: str) -> None:
    result = allocate_in_scope(unit, [MEMORY_MAX, NO_SWAP], UNDER_CAP_MB)

    assert result.returncode == 0
    assert "survived" in result.stdout
    assert scope_property(unit, "LoadState") == "not-found"


@pytest.mark.characterization
@pytest.mark.systemd
@pytest.mark.unit
def test_a_scope_killed_over_the_cap_stays_loaded_until_reset(unit: str) -> None:
    allocate_in_scope(unit, [MEMORY_MAX, NO_SWAP], OVER_CAP_MB)
    loaded_after_kill = scope_property(unit, "LoadState")

    reset_failed(unit)

    assert loaded_after_kill == "loaded"
    assert scope_property(unit, "LoadState") == "not-found"


def host_has_swap() -> bool:
    return len(Path("/proc/swaps").read_text().splitlines()) > 1


@pytest.mark.characterization
@pytest.mark.systemd
@pytest.mark.unit
@pytest.mark.skipif(not host_has_swap(), reason="the host has no swap to spill into")
def test_without_a_swap_limit_a_child_over_the_cap_survives_by_swapping(
    unit: str,
) -> None:
    result = allocate_in_scope(unit, [MEMORY_MAX], OVER_CAP_MB)

    assert result.returncode == 0
    assert "survived" in result.stdout
