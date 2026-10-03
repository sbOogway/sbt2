import subprocess
import sys
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from jeepney import DBusAddress, MatchRule, Message, Properties, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import DBusConnection, open_dbus_connection
from jeepney.wrappers import DBusErrorResponse, unwrap_msg

type UnitProperty = tuple[str, tuple[str, Any]]

SYSTEMD = "org.freedesktop.systemd1"
MANAGER = DBusAddress(
    "/org/freedesktop/systemd1", bus_name=SYSTEMD, interface=f"{SYSTEMD}.Manager"
)
MEMORY_MAX: UnitProperty = ("MemoryMax", ("t", 100 * 2**20))
NO_SWAP: UnitProperty = ("MemorySwapMax", ("t", 0))
OVER_CAP_MB = 300
UNDER_CAP_MB = 20
# systemd unloads a scope a few milliseconds after its last process exits.
UNLOAD_SECONDS = 5
POLL_SECONDS = 0.01
# The child waits for its stdin to close, so that it allocates only once in its scope.
# Writing the bytes, rather than bytearray(n), makes sure every page is resident.
ALLOCATE = """
import sys
sys.stdin.read()
block = b"x" * (int(sys.argv[1]) * 2**20)
print("survived")
"""


@pytest.fixture
def unit() -> Iterator[str]:
    name = f"sbt2-test-{uuid.uuid4().hex}"
    yield name
    reset_failed(name)


def call(bus: DBusConnection, message: Message) -> tuple[Any, ...]:
    return unwrap_msg(bus.send_and_get_reply(message))


def reset_failed(unit: str) -> None:
    reset = new_method_call(MANAGER, "ResetFailedUnit", "s", (f"{unit}.scope",))
    with open_dbus_connection() as bus, suppress(DBusErrorResponse):
        call(bus, reset)


def blocked_child(megabytes: int) -> subprocess.Popen[str]:
    command = [sys.executable, "-c", ALLOCATE, str(megabytes)]
    return subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )


def job_removed(scope: str) -> MatchRule:
    rule = MatchRule(
        type="signal",
        interface=f"{SYSTEMD}.Manager",
        member="JobRemoved",
        path=MANAGER.object_path,
    )
    rule.add_arg_condition(2, scope)
    return rule


def place_in_scope(unit: str, pid: int, properties: Sequence[UnitProperty]) -> str:
    """Start the scope ``unit`` holding ``pid``, and return its start job's result."""
    scope = f"{unit}.scope"
    rule = job_removed(scope)
    signature = "ssa(sv)a(sa(sv))"
    body = (scope, "fail", [("PIDs", ("au", [pid])), *properties], [])
    start = new_method_call(MANAGER, "StartTransientUnit", signature, body)
    with open_dbus_connection() as bus, bus.filter(rule) as removed:
        call(bus, message_bus.AddMatch(rule))
        call(bus, new_method_call(MANAGER, "Subscribe"))
        call(bus, start)
        signal = bus.recv_until_filtered(removed, timeout=30)
    return signal.body[3]


def allocate_in_scope(
    unit: str, properties: Sequence[UnitProperty], megabytes: int
) -> subprocess.CompletedProcess[str]:
    child = blocked_child(megabytes)
    place_in_scope(unit, child.pid, properties)
    stdout, stderr = child.communicate("", timeout=60)
    return subprocess.CompletedProcess(child.args, child.returncode, stdout, stderr)


def scope_property(unit: str, interface: str, name: str) -> str:
    load = new_method_call(MANAGER, "LoadUnit", "s", (f"{unit}.scope",))
    with open_dbus_connection() as bus:
        (path,) = call(bus, load)
        scope = DBusAddress(path, bus_name=SYSTEMD, interface=f"{SYSTEMD}.{interface}")
        ((_, value),) = call(bus, Properties(scope).get(name))
    return value


def load_state(unit: str) -> str:
    return scope_property(unit, "Unit", "LoadState")


def settled_load_state(unit: str) -> str:
    """The scope's load state once it is not-found, or after ``UNLOAD_SECONDS``."""
    deadline = time.monotonic() + UNLOAD_SECONDS
    while (state := load_state(unit)) != "not-found" and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
    return state


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

    assert scope_property(unit, "Scope", "Result") == "oom-kill"


@pytest.mark.characterization
@pytest.mark.systemd
@pytest.mark.unit
def test_a_child_under_the_cap_runs_to_completion(unit: str) -> None:
    result = allocate_in_scope(unit, [MEMORY_MAX, NO_SWAP], UNDER_CAP_MB)

    assert result.returncode == 0
    assert "survived" in result.stdout
    assert settled_load_state(unit) == "not-found"


@pytest.mark.characterization
@pytest.mark.systemd
@pytest.mark.unit
def test_a_scope_killed_over_the_cap_stays_loaded_until_reset(unit: str) -> None:
    allocate_in_scope(unit, [MEMORY_MAX, NO_SWAP], OVER_CAP_MB)
    loaded_after_kill = load_state(unit)

    reset_failed(unit)

    assert loaded_after_kill == "loaded"
    assert load_state(unit) == "not-found"


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


@pytest.mark.characterization
@pytest.mark.systemd
@pytest.mark.unit
def test_without_a_user_session_bus_no_connection_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    with pytest.raises(KeyError, match="DBUS_SESSION_BUS_ADDRESS"):
        open_dbus_connection()


@pytest.mark.characterization
@pytest.mark.systemd
@pytest.mark.unit
def test_a_pid_is_in_the_scope_once_its_start_job_is_done(unit: str) -> None:
    child = blocked_child(UNDER_CAP_MB)

    result = place_in_scope(unit, child.pid, [MEMORY_MAX, NO_SWAP])
    cgroup = Path(f"/proc/{child.pid}/cgroup").read_text()
    child.communicate("", timeout=60)

    assert result == "done"
    assert cgroup.strip().endswith(f"{unit}.scope")
