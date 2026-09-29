import subprocess
from collections.abc import Sequence

_RUN = ("systemd-run", "--user", "--scope", "--quiet")


class NoUserSessionError(RuntimeError):
    pass


class SystemdScope:
    """Runs each child in its own transient systemd scope, ``sbt2-{run_id}``,
    with swap off so that a child over its cap is killed rather than swapped."""

    def check(self) -> None:
        try:
            result = subprocess.run(
                [*_RUN, "true"], capture_output=True, text=True, check=False
            )
        except FileNotFoundError:
            raise NoUserSessionError("systemd-run is not installed") from None
        if result.returncode != 0:
            raise NoUserSessionError(
                f"no systemd user session to cap each run's memory in: "
                f"{result.stderr.strip()}"
            )

    def start(
        self, run_id: str, command: Sequence[str], memory_max: int
    ) -> subprocess.Popen[bytes]:
        scope = [
            *_RUN,
            f"--unit={_unit(run_id)}",
            f"--property=MemoryMax={memory_max}",
            "--property=MemorySwapMax=0",
        ]
        return subprocess.Popen([*scope, *command], stdin=subprocess.PIPE)

    def out_of_memory(self, run_id: str) -> bool:
        """A killed scope stays loaded until it is reset, so it is reset here."""
        scope = f"{_unit(run_id)}.scope"
        show = ["systemctl", "--user", "show", scope, "--property=Result", "--value"]
        shown = subprocess.run(show, capture_output=True, text=True, check=False)
        reset = ["systemctl", "--user", "reset-failed", scope]
        subprocess.run(reset, capture_output=True, check=False)
        return shown.stdout.strip() == "oom-kill"


def _unit(run_id: str) -> str:
    return f"sbt2-{run_id}"
