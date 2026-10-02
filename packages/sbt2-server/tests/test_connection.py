import asyncio
from collections.abc import AsyncIterator
from tempfile import TemporaryFile

import pytest

from sbt2.protocol.v1.envelope_pb2 import ClientMessage, Hello, ServerMessage, Welcome
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server import Outbox, Router
from sbt2.server.connection import Connection
from sbt2.server.transport import Channel


class ControlledChannel(Channel):
    def __init__(self) -> None:
        self.disconnected = asyncio.Event()
        self.writing = asyncio.Event()
        self.capacity = asyncio.Semaphore(0)
        self.sent: asyncio.Queue[ServerMessage] = asyncio.Queue()
        self.close_code: int | None = None

    async def frames(self) -> AsyncIterator[bytes | str]:
        yield ClientMessage(request_id=7, hello=Hello()).SerializeToString()
        await self.disconnected.wait()

    async def send(self, frame: bytes) -> None:
        self.writing.set()
        await self.capacity.acquire()
        await self.sent.put(ServerMessage.FromString(frame))

    async def close(self, code: int) -> None:
        self.close_code = code
        self.disconnected.set()


@pytest.mark.unit
def test_streaming_waits_for_queue_capacity() -> None:
    async def scenario() -> None:
        channel = ControlledChannel()
        queued: list[int] = []
        filled = asyncio.Event()

        async def stream(request: ClientMessage, outbox: Outbox) -> ServerMessage:
            for index in range(8):
                await outbox.send(
                    ServerMessage(
                        request_id=request.request_id,
                        welcome=Welcome(server_version=str(index)),
                    )
                )
                queued.append(index)
                if len(queued) == 2:
                    filled.set()
            return ServerMessage(welcome=Welcome(server_version="done"))

        task = asyncio.create_task(
            Connection(channel, Router({"hello": stream}), 1).serve()
        )
        await asyncio.wait_for(filled.wait(), 2)
        assert queued == [0, 1]
        received = []
        for _ in range(9):
            channel.capacity.release()
            received.append(await asyncio.wait_for(channel.sent.get(), 2))
        channel.disconnected.set()
        await task
        assert [each.welcome.server_version for each in received] == [
            *map(str, range(8)),
            "done",
        ]
        assert {each.request_id for each in received} == {7}
        assert channel.close_code is None

    asyncio.run(scenario())


@pytest.mark.unit
def test_disconnect_releases_pending_streams() -> None:
    async def scenario() -> None:
        channel = ControlledChannel()
        released = asyncio.Event()
        handles = []

        async def stream(_request: ClientMessage, outbox: Outbox) -> ServerMessage:
            try:
                with TemporaryFile() as file:
                    handles.append(file)
                    for _ in range(10):
                        await outbox.send(ServerMessage(welcome=Welcome()))
            finally:
                released.set()
            return ServerMessage(welcome=Welcome())

        task = asyncio.create_task(
            Connection(channel, Router({"hello": stream}), 1).serve()
        )
        await asyncio.wait_for(channel.writing.wait(), 2)
        channel.disconnected.set()
        await asyncio.wait_for(task, 2)
        assert released.is_set()
        assert handles[0].closed

    asyncio.run(scenario())


@pytest.mark.unit
def test_stream_failure_ends_with_a_correlated_error() -> None:
    async def scenario() -> None:
        channel = ControlledChannel()
        channel.capacity.release()
        channel.capacity.release()

        async def failing(request: ClientMessage, outbox: Outbox) -> ServerMessage:
            await outbox.send(
                ServerMessage(request_id=request.request_id, welcome=Welcome())
            )
            raise RuntimeError("private path /srv/results")

        task = asyncio.create_task(
            Connection(channel, Router({"hello": failing}), 1).serve()
        )
        first = await asyncio.wait_for(channel.sent.get(), 2)
        last = await asyncio.wait_for(channel.sent.get(), 2)
        channel.disconnected.set()
        await task
        assert first.request_id == last.request_id == 7
        assert last.error.code == ErrorCode.ERROR_CODE_INTERNAL
        assert "private" not in str(last)
        assert channel.sent.empty()

    asyncio.run(scenario())
