import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager

from sbt2.protocol.v1.envelope_pb2 import (
    Capability,
    ClientMessage,
    ServerMessage,
    Welcome,
)
from sbt2.server import Address, Handler, Outbox, Server, Settings

TOKEN = "lab-token"
SERVED = (Capability.CAPABILITY_RUNS, Capability.CAPABILITY_RESULTS)

type Scenario = Callable[[str], Awaitable[None]]


class FakeServer:
    """The real server transport with handlers a test registers; it records
    every request it receives."""

    def __init__(self, capabilities: Iterable[Capability.ValueType] = SERVED) -> None:
        self.requests: list[ClientMessage] = []
        self._welcome = Welcome(server_version="fake", capabilities=capabilities)
        self._routes: dict[str, Handler] = {"hello": self._hello}

    def answer(self, body: str, handler: Handler) -> None:
        self._routes[body] = handler

    def received(self, body: str) -> list[ClientMessage]:
        return [each for each in self.requests if each.WhichOneof("body") == body]

    @asynccontextmanager
    async def serving(self) -> AsyncGenerator[str]:
        routes = {body: self._recorded(each) for body, each in self._routes.items()}
        server = Server(Settings(TOKEN), routes)
        async with server.listening(Address("127.0.0.1", 0)) as bound:
            yield f"ws://{bound.host}:{bound.port}"

    def _recorded(self, handler: Handler) -> Handler:
        async def recorded(request: ClientMessage, outbox: Outbox) -> ServerMessage:
            self.requests.append(request)
            return await handler(request, outbox)

        return recorded

    async def _hello(self, _request: ClientMessage, _outbox: Outbox) -> ServerMessage:
        return ServerMessage(welcome=self._welcome)


def run(scenario: Scenario, server: FakeServer) -> None:
    async def main() -> None:
        async with server.serving() as url:
            await asyncio.wait_for(scenario(url), timeout=10)

    asyncio.run(main())


def replying(message: ServerMessage) -> Handler:
    async def reply(_request: ClientMessage, _outbox: Outbox) -> ServerMessage:
        return message

    return reply
