from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager, suppress

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response
from websockets.typing import Subprotocol

from sbt2.server.transport.base import (
    Address,
    Channel,
    Endpoint,
    HttpRequest,
    Transport,
)


class _Channel(Channel):
    def __init__(self, connection: ServerConnection) -> None:
        self._connection = connection

    async def frames(self) -> AsyncIterator[bytes | str]:
        try:
            async for frame in self._connection:
                yield frame
        except ConnectionClosed:
            return

    async def send(self, frame: bytes) -> None:
        with suppress(ConnectionClosed):
            await self._connection.send(frame)

    async def close(self, code: int) -> None:
        await self._connection.close(code)


class WebsocketsTransport(Transport):
    """The transport on the ``websockets`` library, in asyncio."""

    @asynccontextmanager
    async def listening(
        self, address: Address, endpoint: Endpoint
    ) -> AsyncGenerator[Address]:
        async def handle(connection: ServerConnection) -> None:
            await endpoint.connected(_Channel(connection))

        def process_request(
            connection: ServerConnection, request: Request
        ) -> Response | None:
            response = endpoint.respond(_http_request(request))
            if response is None:
                return None
            return connection.respond(response.status, response.text)

        async with serve(
            handle,
            address.host,
            address.port,
            subprotocols=[Subprotocol(endpoint.subprotocol)],
            process_request=process_request,
        ) as server:
            host, port = server.sockets[0].getsockname()[:2]
            yield Address(host, port)


def _http_request(request: Request) -> HttpRequest:
    return HttpRequest(
        method=request.method,
        path=request.path,
        authorization=request.headers.get("Authorization"),
    )
