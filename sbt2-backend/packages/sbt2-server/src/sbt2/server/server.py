import asyncio
import json
from collections.abc import Iterable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from http import HTTPStatus
from importlib.metadata import version

from sbt2.protocol.v1.envelope_pb2 import (
    Capability,
    ClientMessage,
    ServerMessage,
    Welcome,
)
from sbt2.server.auth import BearerToken
from sbt2.server.connection import Connection
from sbt2.server.routing import Handler, Outbox, Router
from sbt2.server.transport import (
    Address,
    Channel,
    Endpoint,
    HttpRequest,
    HttpResponse,
    Transport,
    WebsocketsTransport,
)

HEALTH = "/health"


@dataclass(frozen=True)
class Settings:
    """``token`` is the API token every client must present; ``queue_size`` the
    messages a connection may fall behind before it is closed."""

    token: str
    queue_size: int = 256
    transport: Transport = field(default_factory=WebsocketsTransport)

    def __post_init__(self) -> None:
        # asyncio.Queue takes a size of 0 for no bound at all
        if self.queue_size < 1:
            raise ValueError(f"queue_size must be at least 1, not {self.queue_size}")


class Server:
    """Serves the protocol: it admits clients presenting the token, answers
    ``Hello``, advertising ``capabilities``, and sends every other body to the
    handler ``routes`` registers for it, by the body's field name in
    ``ClientMessage``."""

    def __init__(
        self,
        settings: Settings,
        routes: Mapping[str, Handler] | None = None,
        capabilities: Iterable[Capability.ValueType] = (),
    ) -> None:
        router = Router({"hello": _welcomer(capabilities), **(routes or {})})
        self._settings = settings
        self._endpoint = _Endpoint(settings, router)

    def listening(self, address: Address) -> AbstractAsyncContextManager[Address]:
        """Serve on ``address`` while the context is open; it gives the address
        bound, whose port is a free one when ``address``'s is 0."""
        return self._settings.transport.listening(address, self._endpoint)

    async def serve(self, address: Address) -> None:
        """Serve on ``address`` until cancelled."""
        async with self.listening(address):
            await asyncio.Future[None]()


class _Endpoint(Endpoint):
    subprotocol = "sbt2.v1"

    def __init__(self, settings: Settings, router: Router) -> None:
        self._token = BearerToken(settings.token)
        self._queue_size = settings.queue_size
        self._router = router
        self._health = HttpResponse(
            HTTPStatus.OK,
            json.dumps({"status": "ok", "version": version("sbt2-server")}),
            "application/json",
        )

    def respond(self, request: HttpRequest) -> HttpResponse | None:
        if request.method == "GET" and request.path == HEALTH:
            return self._health
        if not self._token.admits(request.authorization):
            return HttpResponse(HTTPStatus.UNAUTHORIZED, "Unauthorized")
        return None

    async def connected(self, channel: Channel) -> None:
        await Connection(channel, self._router, self._queue_size).serve()


def _welcomer(capabilities: Iterable[Capability.ValueType]) -> Handler:
    welcome = Welcome(
        server_version=version("sbt2-server"), capabilities=list(capabilities)
    )

    async def answer(_request: ClientMessage, _outbox: Outbox) -> ServerMessage:
        reply = ServerMessage()
        reply.welcome.CopyFrom(welcome)
        return reply

    return answer
