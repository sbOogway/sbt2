import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping

from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.types_pb2 import Error, ErrorCode

logger = logging.getLogger("sbt2.server")


class Outbox(ABC):
    """Where a handler pushes the messages a request causes besides its reply."""

    @abstractmethod
    def push(self, message: ServerMessage) -> None:
        """Queue ``message`` for the client without waiting for it to be sent."""

    @abstractmethod
    async def send(self, message: ServerMessage) -> None:
        """Queue a response chunk, waiting for capacity; disconnect cancels it."""


type Handler = Callable[[ClientMessage, Outbox], Awaitable[ServerMessage]]
"""Answers a request; the router sets the reply's ``request_id``."""


class UnknownBodyError(ValueError):
    pass


def offloaded[**P, R](fn: Callable[P, R]) -> Callable[P, Awaitable[R]]:
    """``fn`` run in a worker thread, so that a handler's file, store or CPU-heavy
    work leaves the event loop free for the other connections."""

    async def run(*args: P.args, **kwargs: P.kwargs) -> R:
        return await asyncio.to_thread(fn, *args, **kwargs)

    return run


def error(code: ErrorCode.ValueType, message: str) -> ServerMessage:
    """A reply carrying an ``Error``."""
    return ServerMessage(error=Error(code=code, message=message))


class Router:
    """Sends each request to the handler registered for its body, by the body's
    field name in ``ClientMessage``."""

    def __init__(self, routes: Mapping[str, Handler]) -> None:
        _check_bodies(routes)
        self._routes = dict(routes)

    async def answer(self, request: ClientMessage, outbox: Outbox) -> ServerMessage:
        """The reply to ``request``, an ``Error`` when it cannot be answered."""
        reply = await self._reply(request, outbox)
        reply.request_id = request.request_id
        return reply

    async def _reply(self, request: ClientMessage, outbox: Outbox) -> ServerMessage:
        body = request.WhichOneof("body")
        if body is None:
            return error(ErrorCode.ERROR_CODE_INVALID_MESSAGE, "the body is unset")
        if request.request_id == 0:
            return error(ErrorCode.ERROR_CODE_INVALID_ARGUMENT, "request_id is 0")
        handler = self._routes.get(body)
        if handler is None:
            return error(ErrorCode.ERROR_CODE_UNIMPLEMENTED, f"no handler for {body}")
        return await _handled(handler, request, outbox)


async def _handled(
    handler: Handler, request: ClientMessage, outbox: Outbox
) -> ServerMessage:
    try:
        return await handler(request, outbox)
    except Exception:
        logger.exception("the handler of request %d failed", request.request_id)
        return error(ErrorCode.ERROR_CODE_INTERNAL, "the server failed to answer")


def _check_bodies(routes: Mapping[str, Handler]) -> None:
    bodies = {
        field.name for field in ClientMessage.DESCRIPTOR.oneofs_by_name["body"].fields
    }
    unknown = sorted(set(routes) - bodies)
    if unknown:
        raise UnknownBodyError(f"ClientMessage has no body {', '.join(unknown)}")
