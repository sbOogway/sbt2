import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from sbt2.protocol.v1.envelope_pb2 import ClientMessage, Hello, ServerMessage, Welcome
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server import Handler, Outbox, Router, UnknownBodyError


class KeptOutbox(Outbox):
    def __init__(self) -> None:
        self.pushed: list[ServerMessage] = []

    def push(self, message: ServerMessage) -> None:
        self.pushed.append(message)

    async def send(self, message: ServerMessage) -> None:
        self.pushed.append(message)

    def spawn(self, work: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        return asyncio.create_task(work)


def hello(request_id: int) -> ClientMessage:
    return ClientMessage(request_id=request_id, hello=Hello(client_version="test"))


def answer(routes: dict[str, Handler], request: ClientMessage) -> ServerMessage:
    return asyncio.run(Router(routes).answer(request, KeptOutbox()))


@pytest.mark.unit
def test_a_body_goes_to_its_handler_and_the_reply_carries_the_request_id() -> None:
    received: list[ClientMessage] = []

    async def welcome(request: ClientMessage, _outbox: Outbox) -> ServerMessage:
        received.append(request)
        return ServerMessage(welcome=Welcome(server_version="1"))

    reply = answer({"hello": welcome}, hello(7))

    assert received == [hello(7)]
    assert reply.request_id == 7
    assert reply.WhichOneof("body") == "welcome"


@pytest.mark.unit
def test_a_body_without_a_handler_is_unimplemented() -> None:
    reply = answer({}, hello(7))

    assert reply.request_id == 7
    assert reply.error.code == ErrorCode.ERROR_CODE_UNIMPLEMENTED


@pytest.mark.unit
def test_a_failing_handler_becomes_an_internal_error() -> None:
    async def failing(_request: ClientMessage, _outbox: Outbox) -> ServerMessage:
        raise RuntimeError("the secret path /srv/x")

    reply = answer({"hello": failing}, hello(7))

    assert reply.request_id == 7
    assert reply.error.code == ErrorCode.ERROR_CODE_INTERNAL
    assert "secret" not in str(reply)


@pytest.mark.unit
def test_a_request_id_of_zero_is_an_invalid_argument() -> None:
    async def welcome(_request: ClientMessage, _outbox: Outbox) -> ServerMessage:
        return ServerMessage(welcome=Welcome())

    reply = answer({"hello": welcome}, hello(0))

    assert reply.request_id == 0
    assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_ARGUMENT


@pytest.mark.unit
def test_a_request_without_a_body_is_an_invalid_message() -> None:
    reply = answer({}, ClientMessage(request_id=7))

    assert reply.request_id == 7
    assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_MESSAGE


@pytest.mark.unit
def test_a_route_for_no_body_of_client_message_is_refused() -> None:
    async def welcome(_request: ClientMessage, _outbox: Outbox) -> ServerMessage:
        return ServerMessage(welcome=Welcome())

    with pytest.raises(UnknownBodyError, match="helo"):
        Router({"helo": welcome})
