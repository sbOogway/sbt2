import asyncio
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path

from sbt2 import data
from sbt2.core import spec
from sbt2.core.config import Root
from sbt2.protocol.v1.config_pb2 import ConfigWritten, KnownGaps
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.types_pb2 import Error, ErrorCode
from sbt2.server import Handler, Outbox, offloaded
from sbt2.server.handlers.config.encoding import (
    InvalidArgumentError,
    gap_message,
    listed_gap,
    model_kinds,
)


def routes(root: Root) -> dict[str, Handler]:
    """Handlers for reading the model kinds and editing the known gaps in
    ``root``, through core's public API. Each read goes to the files; writes to
    one file run one at a time."""
    edits = _Config(root.known_gaps)
    return {
        "list_known_gaps": _guard(edits.list_known_gaps),
        "add_known_gaps": _guard(edits.add_known_gaps),
        "remove_known_gaps": _guard(edits.remove_known_gaps),
        "list_model_kinds": _list_model_kinds,
    }


@dataclass
class _Config:
    known_gaps: Path
    known_gaps_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def list_known_gaps(
        self, _request: ClientMessage, _outbox: Outbox
    ) -> ServerMessage:
        listed = await offloaded(data.listed_gaps)(self.known_gaps)
        gaps = [gap_message(each) for each in listed]
        return ServerMessage(known_gaps=KnownGaps(gaps=gaps))

    async def add_known_gaps(
        self, request: ClientMessage, _outbox: Outbox
    ) -> ServerMessage:
        gaps = [listed_gap(each) for each in request.add_known_gaps.gaps]
        async with self.known_gaps_lock:
            await offloaded(data.add_known_gaps)(self.known_gaps, gaps)
        return _written()

    async def remove_known_gaps(
        self, request: ClientMessage, _outbox: Outbox
    ) -> ServerMessage:
        gaps = [listed_gap(each) for each in request.remove_known_gaps.gaps]
        async with self.known_gaps_lock:
            await offloaded(data.remove_known_gaps)(self.known_gaps, gaps)
        return _written()


async def _list_model_kinds(_request: ClientMessage, _outbox: Outbox) -> ServerMessage:
    return ServerMessage(model_kinds=model_kinds(spec.model_kinds()))


def _written() -> ServerMessage:
    return ServerMessage(config_written=ConfigWritten())


def _guard(handler: Handler) -> Handler:
    @wraps(handler)
    async def answer(request: ClientMessage, outbox: Outbox) -> ServerMessage:
        try:
            return await handler(request, outbox)
        except (
            spec.SpecError,
            data.UnknownSourceError,
            data.UnsupportedDataTypeError,
            InvalidArgumentError,
        ) as error:
            return _error(ErrorCode.ERROR_CODE_INVALID_ARGUMENT, error)

    return answer


def _error(code: ErrorCode.ValueType, error: Exception) -> ServerMessage:
    return ServerMessage(error=Error(code=code, message=str(error)))


__all__ = ["routes"]
