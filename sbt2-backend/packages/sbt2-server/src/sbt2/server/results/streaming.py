from collections.abc import Iterable, Iterator
from typing import BinaryIO

from google.protobuf.message import Message

from sbt2.protocol.v1.envelope_pb2 import ServerMessage
from sbt2.server import Outbox, offloaded

MAX_ENVELOPE = 1_048_576
# room for the chunk's index, last flag and the length prefixes its bytes add
_CHUNK_OVERHEAD = 32


class TooLargeError(ValueError):
    pass


def checked(message: ServerMessage) -> ServerMessage:
    if message.ByteSize() > MAX_ENVELOPE:
        raise TooLargeError
    return message


def records(
    template: ServerMessage, field: str, items: Iterable[Message]
) -> Iterator[ServerMessage]:
    body = template.WhichOneof("body")
    if body is None:
        raise ValueError("a response needs a body")
    chunk = getattr(template, body)
    chunk.last = True
    entries = getattr(chunk, field)
    for item in items:
        entries.append(item)
        if template.ByteSize() <= MAX_ENVELOPE:
            continue
        del entries[-1]
        if not entries:
            raise TooLargeError
        chunk.last = False
        yield template
        template = ServerMessage.FromString(template.SerializeToString())
        chunk = getattr(template, body)
        chunk.index += 1
        chunk.last = True
        entries = getattr(chunk, field)
        del entries[:]
        entries.append(item)
        checked(template)
    yield template


def pieces(template: ServerMessage, source: BinaryIO) -> Iterator[ServerMessage]:
    body = template.WhichOneof("body")
    if body is None:
        raise ValueError("a response needs a body")
    size = MAX_ENVELOPE - template.ByteSize() - _CHUNK_OVERHEAD
    index, current = 0, source.read(size)
    while True:
        following = source.read(size)
        message = ServerMessage()
        message.CopyFrom(template)
        chunk = getattr(message, body)
        chunk.index, chunk.data, chunk.last = index, current, not following
        yield checked(message)
        if not following:
            return
        index, current = index + 1, following


async def deliver(replies: Iterator[ServerMessage], outbox: Outbox) -> ServerMessage:
    current = await offloaded(next)(replies, None)
    if current is None:
        raise ValueError("a response needs a terminal message")
    while following := await offloaded(next)(replies, None):
        await outbox.send(current)
        current = following
    return current
