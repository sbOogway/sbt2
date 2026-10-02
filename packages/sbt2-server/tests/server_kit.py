import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from websockets.asyncio.client import ClientConnection, connect
from websockets.typing import Subprotocol

from sbt2.protocol.v1.envelope_pb2 import ClientMessage, Hello, ServerMessage
from sbt2.server import Address, Server, Settings

TOKEN = "s3cret-token"
SUBPROTOCOL = Subprotocol("sbt2.v1")
AUTHORIZATION = {"Authorization": f"Bearer {TOKEN}"}

type Scenario = Callable[[str], Awaitable[None]]


@asynccontextmanager
async def serving(server: Server) -> AsyncGenerator[str]:
    async with server.listening(Address("127.0.0.1", 0)) as bound:
        yield f"ws://{bound.host}:{bound.port}"


def run(scenario: Scenario, server: Server | None = None) -> None:
    async def main() -> None:
        async with serving(server or Server(Settings(TOKEN))) as url:
            await asyncio.wait_for(scenario(url), timeout=10)

    asyncio.run(main())


def client(url: str) -> connect:
    return connect(url, subprotocols=[SUBPROTOCOL], additional_headers=AUTHORIZATION)


def hello(request_id: int, client_version: str = "test") -> ClientMessage:
    return ClientMessage(
        request_id=request_id, hello=Hello(client_version=client_version)
    )


async def ask(connection: ClientConnection, frame: bytes | str) -> ServerMessage:
    await connection.send(frame)
    reply = await connection.recv()
    assert isinstance(reply, bytes)
    return ServerMessage.FromString(reply)


async def greet(connection: ClientConnection) -> ServerMessage:
    return await ask(connection, hello(1).SerializeToString())
