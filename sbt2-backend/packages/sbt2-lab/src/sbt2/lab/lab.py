from collections.abc import Mapping
from importlib.metadata import version
from types import TracebackType
from typing import Any, Self

from sbt2.lab.errors import MissingCapabilityError
from sbt2.lab.jobs import finished
from sbt2.lab.runs import Runs, stored_runs
from sbt2.lab.session import Session
from sbt2.lab.submission import submit_run
from sbt2.protocol.v1.envelope_pb2 import Capability, ClientMessage, Hello, Welcome

_NEEDED = {
    Capability.CAPABILITY_RUNS: "runs",
    Capability.CAPABILITY_RESULTS: "results",
}


class Lab:
    """A notebook's connection to an sbt2 server, which runs its strategies."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @classmethod
    async def connect(cls, url: str, token: str) -> Self:
        """Connect to the server at ``url``, such as ``wss://host:8765``, with
        its API token."""
        session = await Session.open(url, token)
        try:
            _check(await _greet(session))
        except BaseException:
            await session.close()
            raise
        return cls(session)

    async def run(self, spec: Mapping[str, Any], strategy: str) -> Runs:
        """Run ``spec`` on the server and return its runs once the job finishes.

        ``spec`` holds the keys of a spec file but ``strategy``, which is
        ``"module:Class"``. The module is sent as source, so it may import only
        what the server has: sbt2, nautilus and the standard library.
        """
        request = submit_run(spec, strategy)
        [reply] = await self._session.ask(ClientMessage(submit_run=request))
        submitted = reply.job_submitted
        await finished(self._session, submitted)
        return await stored_runs(self._session, submitted.run_ids)

    async def close(self) -> None:
        await self._session.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        _kind: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self.close()


async def _greet(session: Session) -> Welcome:
    hello = Hello(client_version=version("sbt2-lab"))
    [reply] = await session.ask(ClientMessage(hello=hello))
    return reply.welcome


def _check(welcome: Welcome) -> None:
    missing = [
        name for kind, name in _NEEDED.items() if kind not in welcome.capabilities
    ]
    if missing:
        raise MissingCapabilityError(
            f"the server does not serve {' and '.join(missing)}"
        )
