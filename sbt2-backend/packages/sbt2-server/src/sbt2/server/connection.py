import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from google.protobuf.message import DecodeError

from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server.routing import Outbox, Router, error
from sbt2.server.transport import Channel

TRY_AGAIN_LATER = 1013

logger = logging.getLogger("sbt2.server")


class Connection(Outbox):
    """One client's session: it answers each request in a task of its own and
    sends every message through a queue of ``queue_size``, closing the connection
    with 1013 when the client falls that far behind."""

    def __init__(self, channel: Channel, router: Router, queue_size: int) -> None:
        self._channel = channel
        self._router = router
        self._outgoing: asyncio.Queue[ServerMessage] = asyncio.Queue(queue_size)
        self._tasks: set[asyncio.Task[None]] = set()
        self._greeted = False
        self._closing = False

    def push(self, message: ServerMessage) -> None:
        if self._closing:
            return
        try:
            self._outgoing.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning(
                "closing a client that fell %d messages behind", self._outgoing.maxsize
            )
            self._closing = True
            self.spawn(self._channel.close(TRY_AGAIN_LATER))

    async def send(self, message: ServerMessage) -> None:
        if self._closing:
            raise asyncio.CancelledError
        await self._outgoing.put(message)

    async def serve(self) -> None:
        """Handle the connection until it closes."""
        writer = asyncio.create_task(self._write())
        try:
            async for frame in self._channel.frames():
                self._receive(frame)
        finally:
            self._closing = True
            tasks = [writer, *self._tasks]
            for task in tasks:
                task.cancel()
            self._outgoing.shutdown(immediate=True)
            await asyncio.gather(*tasks, return_exceptions=True)

    def _receive(self, frame: bytes | str) -> None:
        request = _decoded(frame)
        if request is None:
            self.push(
                error(ErrorCode.ERROR_CODE_INVALID_MESSAGE, "not a ClientMessage")
            )
            return
        if request.WhichOneof("body") == "hello":
            self._greeted = True
        if not self._greeted:
            self.push(_before_hello(request))
            return
        self.spawn(self._answer(request))

    async def _answer(self, request: ClientMessage) -> None:
        await self.send(await self._router.answer(request, self))

    async def _write(self) -> None:
        while True:
            message = await self._outgoing.get()
            await self._channel.send(message.SerializeToString())

    def spawn(self, work: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task


def _decoded(frame: bytes | str) -> ClientMessage | None:
    if isinstance(frame, str):
        return None
    try:
        return ClientMessage.FromString(frame)
    except DecodeError:
        return None


def _before_hello(request: ClientMessage) -> ServerMessage:
    reply = error(
        ErrorCode.ERROR_CODE_INVALID_MESSAGE, "the first message must be Hello"
    )
    reply.request_id = request.request_id
    return reply
