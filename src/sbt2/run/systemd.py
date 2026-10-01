from typing import Any

from jeepney import DBusAddress, MatchRule, Message, Properties, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import DBusConnection, open_dbus_connection
from jeepney.wrappers import DBusErrorResponse, unwrap_msg

_SYSTEMD = "org.freedesktop.systemd1"
_MANAGER = DBusAddress(
    "/org/freedesktop/systemd1", bus_name=_SYSTEMD, interface=f"{_SYSTEMD}.Manager"
)
_START_SECONDS = 30
_PROCESS_GONE = "org.freedesktop.DBus.Error.UnixProcessIdUnknown"


class NoUserSessionError(RuntimeError):
    pass


class SystemdScope:
    """Caps each child in its own transient systemd scope, ``sbt2-{run_id}``,
    with swap off so that a child over its cap is killed rather than swapped."""

    def check(self) -> None:
        with _session() as bus:
            try:
                _call(bus, Properties(_MANAGER).get("Version"))
            except DBusErrorResponse as error:
                raise NoUserSessionError(
                    f"no systemd user manager to cap each run's memory in: {error}"
                ) from None

    def cap(self, run_id: str, pid: int, memory_max: int) -> None:
        """Return once the process ``pid`` is in the scope of ``run_id``, or at
        once if it has already exited, for the batch to reap it by its exit code."""
        try:
            self._start_scope(run_id, pid, memory_max)
        except DBusErrorResponse as error:
            if error.name != _PROCESS_GONE:
                raise

    def _start_scope(self, run_id: str, pid: int, memory_max: int) -> None:
        scope = _scope(run_id)
        properties = [
            ("PIDs", ("au", [pid])),
            ("MemoryMax", ("t", memory_max)),
            ("MemorySwapMax", ("t", 0)),
        ]
        body = (scope, "fail", properties, [])
        start = new_method_call(
            _MANAGER, "StartTransientUnit", "ssa(sv)a(sa(sv))", body
        )
        result = _job_result(scope, start)
        if result != "done":
            raise RuntimeError(f"systemd could not cap run {run_id}: {result}")

    def out_of_memory(self, run_id: str) -> bool:
        """A killed scope stays loaded until it is reset, so it is reset here."""
        scope = _scope(run_id)
        with _session() as bus:
            result = _scope_result(bus, scope)
            if result != "success":
                _call(bus, new_method_call(_MANAGER, "ResetFailedUnit", "s", (scope,)))
        return result == "oom-kill"


def _scope(run_id: str) -> str:
    return f"sbt2-{run_id}.scope"


def _session() -> DBusConnection:
    try:
        return open_dbus_connection()
    except (KeyError, OSError) as error:
        raise NoUserSessionError(
            f"no systemd user session bus to cap each run's memory in: {error!r}"
        ) from None


def _call(bus: DBusConnection, message: Message) -> tuple[Any, ...]:
    return unwrap_msg(bus.send_and_get_reply(message))


def _job_result(scope: str, start: Message) -> str:
    """Send ``start`` for ``scope`` and wait for its job to be removed."""
    removed = _job_removed(scope)
    with _session() as bus, bus.filter(removed) as signals:
        _call(bus, message_bus.AddMatch(removed))
        _call(bus, new_method_call(_MANAGER, "Subscribe"))
        _call(bus, start)
        signal = bus.recv_until_filtered(signals, timeout=_START_SECONDS)
    return signal.body[3]


def _job_removed(scope: str) -> MatchRule:
    # systemd signals under its unique bus name, which a sender rule would not match
    rule = MatchRule(
        type="signal",
        interface=f"{_SYSTEMD}.Manager",
        member="JobRemoved",
        path=_MANAGER.object_path,
    )
    rule.add_arg_condition(2, scope)
    return rule


def _scope_result(bus: DBusConnection, scope: str) -> str:
    """The scope's result, ``success`` for a scope that is already gone."""
    (path,) = _call(bus, new_method_call(_MANAGER, "LoadUnit", "s", (scope,)))
    unit = DBusAddress(path, bus_name=_SYSTEMD, interface=f"{_SYSTEMD}.Scope")
    ((_, result),) = _call(bus, Properties(unit).get("Result"))
    return result
