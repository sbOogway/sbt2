from collections.abc import Iterable, Iterator

from google.protobuf.message import Message

from sbt2.protocol.v1.envelope_pb2 import ServerMessage
from sbt2.server import Outbox, offloaded

MAX_ENVELOPE = 1_048_576


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


async def deliver(replies: Iterator[ServerMessage], outbox: Outbox) -> ServerMessage:
    current = await offloaded(next)(replies, None)
    if current is None:
        raise ValueError("a response needs a terminal message")
    while following := await offloaded(next)(replies, None):
        await outbox.send(current)
        current = following
    return current
