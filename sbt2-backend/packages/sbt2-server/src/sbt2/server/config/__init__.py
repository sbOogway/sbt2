import asyncio
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path

from sbt2.core import spec
from sbt2.core.config import ConfigFolder, Root
from sbt2.protocol.v1.config_pb2 import ConfigWritten, VenueProfiles
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.types_pb2 import Error, ErrorCode
from sbt2.server import Handler, Outbox, offloaded
from sbt2.server.config.encoding import (
    InvalidArgumentError,
    profile_message,
    profile_table,
)


def routes(config: ConfigFolder, root: Root) -> dict[str, Handler]:
    """Handlers for reading and editing the config in ``config``, and the known
    gaps in ``root``, through core's public API. Each read goes to the files;
    writes to one file run one at a time."""
    edits = _Config(config.venues, root.known_gaps)
    return {
        "list_venue_profiles": _guard(edits.list_venue_profiles),
        "put_venue_profile": _guard(edits.put_venue_profile),
        "delete_venue_profile": _guard(edits.delete_venue_profile),
    }


@dataclass
class _Config:
    venues: Path
    known_gaps: Path
    venues_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def list_venue_profiles(
        self, _request: ClientMessage, _outbox: Outbox
    ) -> ServerMessage:
        stored = await offloaded(spec.venue_profiles)(self.venues)
        profiles = [profile_message(name, table) for name, table in stored.items()]
        return ServerMessage(venue_profiles=VenueProfiles(profiles=profiles))

    async def put_venue_profile(
        self, request: ClientMessage, _outbox: Outbox
    ) -> ServerMessage:
        profile = request.put_venue_profile.profile
        table = profile_table(profile)
        async with self.venues_lock:
            await offloaded(spec.put_venue_profile)(self.venues, profile.name, table)
        return _written()

    async def delete_venue_profile(
        self, request: ClientMessage, _outbox: Outbox
    ) -> ServerMessage:
        name = request.delete_venue_profile.name
        async with self.venues_lock:
            await offloaded(spec.delete_venue_profile)(self.venues, name)
        return _written()


def _written() -> ServerMessage:
    return ServerMessage(config_written=ConfigWritten())


def _guard(handler: Handler) -> Handler:
    @wraps(handler)
    async def answer(request: ClientMessage, outbox: Outbox) -> ServerMessage:
        try:
            return await handler(request, outbox)
        except spec.UnknownVenueProfileError as error:
            return _error(ErrorCode.ERROR_CODE_NOT_FOUND, error)
        except (spec.SpecError, InvalidArgumentError) as error:
            return _error(ErrorCode.ERROR_CODE_INVALID_ARGUMENT, error)

    return answer


def _error(code: ErrorCode.ValueType, error: Exception) -> ServerMessage:
    return ServerMessage(error=Error(code=code, message=str(error)))


__all__ = ["routes"]
