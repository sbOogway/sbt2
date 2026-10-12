import asyncio
import itertools
from collections import defaultdict
from typing import Self

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import InvalidHandshake
from websockets.typing import Subprotocol

from sbt2.lab.errors import ConnectError, ServerError
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage

_SUBPROTOCOL = Subprotocol("sbt2.v1")

type _Inbox = asyncio.Queue[ServerMessage | None]


class Session:
    """One connection to the server: it pairs each reply with its request, and
    queues the pushes of each subscription."""

    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection
        self._ids = itertools.count(1)
        self._replies: dict[int, _Inbox] = {}
        self._pushes: defaultdict[int, _Inbox] = defaultdict(asyncio.Queue)
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def open(cls, url: str, token: str) -> Self:
        try:
            connection = await connect(
                url,
                subprotocols=[_SUBPROTOCOL],
                additional_headers={"Authorization": f"Bearer {token}"},
            )
        except (InvalidHandshake, OSError) as error:
            raise ConnectError(f"cannot connect to {url}: {error}") from error
        return cls(connection)

    async def ask(self, request: ClientMessage) -> list[ServerMessage]:
        """Every chunk of the reply to ``request``, in order."""
        request.request_id = next(self._ids)
        inbox = self._replies[request.request_id] = asyncio.Queue()
        try:
            await self._connection.send(request.SerializeToString())
            return await _chunks(inbox)
        finally:
            del self._replies[request.request_id]

    async def push(self, subscription_id: int) -> ServerMessage:
        """The next push of ``subscription_id``."""
        return _delivered(await self._pushes[subscription_id].get())

    def forget(self, subscription_id: int) -> None:
        self._pushes.pop(subscription_id, None)

    async def close(self) -> None:
        await self._connection.close()
        await self._reader

    async def _read(self) -> None:
        try:
            async for frame in self._connection:
                if isinstance(frame, bytes):
                    self._route(ServerMessage.FromString(frame))
        finally:
            for inbox in [*self._replies.values(), *self._pushes.values()]:
                inbox.put_nowait(None)

    def _route(self, message: ServerMessage) -> None:
        if message.request_id:
            inbox = self._replies.get(message.request_id)
            if inbox is not None:
                inbox.put_nowait(message)
        else:
            self._pushes[message.subscription_id].put_nowait(message)


async def _chunks(inbox: _Inbox) -> list[ServerMessage]:
    chunks = [_delivered(await inbox.get())]
    while not _is_last(chunks[-1]):
        chunks.append(_delivered(await inbox.get()))
    return chunks


def _delivered(message: ServerMessage | None) -> ServerMessage:
    if message is None:
        raise ConnectError("the server closed the connection")
    if message.HasField("error"):
        raise ServerError(message.error)
    return message


def _is_last(message: ServerMessage) -> bool:
    """A chunked body says whether it is the last; any other body is a whole reply."""
    body = getattr(message, message.WhichOneof("body") or "")
    return "last" not in body.DESCRIPTOR.fields_by_name or body.last
