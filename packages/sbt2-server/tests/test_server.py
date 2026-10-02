import asyncio
import threading
import time
import urllib.request
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from results_kit import priced, stored
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import InvalidStatus
from websockets.typing import Subprotocol

from sbt2.core import results as core
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, Hello, ServerMessage, Welcome
from sbt2.protocol.v1.results_pb2 import GetSeries, GetTearsheet, ListRuns, SeriesKind
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server import Address, Outbox, Server, Settings, offloaded
from sbt2.server.results import routes

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


async def refusal(
    url: str, headers: Mapping[str, str], subprotocols: list[Subprotocol]
) -> int:
    with pytest.raises(InvalidStatus) as refused:
        async with connect(url, subprotocols=subprotocols, additional_headers=headers):
            pass
    return refused.value.response.status_code


@pytest.mark.e2e
def test_hello_is_answered_with_welcome() -> None:
    async def scenario(url: str) -> None:
        async with client(url) as connection:
            reply = await ask(connection, hello(5).SerializeToString())

        assert reply.request_id == 5
        assert reply.welcome == Welcome(server_version=version("sbt2-server"))
        assert list(reply.welcome.capabilities) == []

    run(scenario)


@pytest.mark.e2e
def test_a_handshake_without_a_valid_token_is_refused_with_401() -> None:
    async def scenario(url: str) -> None:
        assert await refusal(url, {}, [SUBPROTOCOL]) == 401
        assert (
            await refusal(url, {"Authorization": "Bearer wrong"}, [SUBPROTOCOL]) == 401
        )

    run(scenario)


@pytest.mark.e2e
def test_a_handshake_without_the_subprotocol_is_refused() -> None:
    async def scenario(url: str) -> None:
        assert await refusal(url, AUTHORIZATION, []) == 400
        assert await refusal(url, AUTHORIZATION, [Subprotocol("sbt2.v2")]) == 400

    run(scenario)


@pytest.mark.e2e
def test_a_message_before_hello_gets_an_error_and_the_connection_stays_open() -> None:
    # Hello is the only body so far: a request without a body stands for any other
    bodiless = ClientMessage(request_id=3).SerializeToString()

    async def scenario(url: str) -> None:
        async with client(url) as connection:
            refused = await ask(connection, bodiless)
            welcomed = await greet(connection)

        assert refused.request_id == 3
        assert refused.error.code == ErrorCode.ERROR_CODE_INVALID_MESSAGE
        assert welcomed.WhichOneof("body") == "welcome"

    run(scenario)


@pytest.mark.e2e
@pytest.mark.parametrize("frame", [b"\xff\xff\xff", "hello"], ids=["garbage", "text"])
def test_a_malformed_frame_gets_an_invalid_message_error(frame: bytes | str) -> None:
    async def scenario(url: str) -> None:
        async with client(url) as connection:
            await greet(connection)
            refused = await ask(connection, frame)
            welcomed = await greet(connection)

        assert refused.request_id == 0
        assert refused.error.code == ErrorCode.ERROR_CODE_INVALID_MESSAGE
        assert welcomed.WhichOneof("body") == "welcome"

    run(scenario)


@pytest.mark.e2e
def test_health_answers_ok_without_a_token() -> None:
    def get(url: str) -> tuple[int, str]:
        with urllib.request.urlopen(
            url.replace("ws://", "http://") + "/health"
        ) as response:
            return response.status, response.read().decode()

    async def scenario(url: str) -> None:
        assert await asyncio.to_thread(get, url) == (200, "OK")

    run(scenario)


@pytest.mark.e2e
def test_a_client_that_does_not_read_is_closed_with_1013() -> None:
    async def flood(_request: ClientMessage, outbox: Outbox) -> ServerMessage:
        for _ in range(100):
            outbox.push(ServerMessage(welcome=Welcome()))
        return ServerMessage(welcome=Welcome())

    async def scenario(url: str) -> None:
        async with client(url) as connection:
            await connection.send(hello(1).SerializeToString())
            await connection.wait_closed()

        assert connection.close_code == 1013

    run(scenario, Server(Settings(TOKEN, queue_size=4), {"hello": flood}))


@pytest.mark.e2e
def test_a_blocking_handler_does_not_hold_up_other_connections() -> None:
    async def welcome(request: ClientMessage, _outbox: Outbox) -> ServerMessage:
        if request.hello.client_version == "slow":
            await offloaded(time.sleep)(1)
        return ServerMessage(welcome=Welcome())

    async def scenario(url: str) -> None:
        async with client(url) as slow, client(url) as quick:
            await slow.send(hello(1, "slow").SerializeToString())
            started = time.monotonic()
            await greet(quick)
            waited = time.monotonic() - started
            await slow.recv()

        assert waited < 0.5

    run(scenario, Server(Settings(TOKEN), {"hello": welcome}))


@pytest.mark.unit
def test_an_outgoing_queue_of_no_messages_is_refused() -> None:
    with pytest.raises(ValueError, match="queue_size"):
        Settings(TOKEN, queue_size=0)


async def collected(
    connection: ClientConnection, pending: set[int]
) -> dict[int, list[ServerMessage]]:
    """The replies to the ``pending`` request ids, until each one's last chunk."""
    replies: dict[int, list[ServerMessage]] = {each: [] for each in pending}
    while pending:
        frame = await connection.recv()
        assert isinstance(frame, bytes)
        reply = ServerMessage.FromString(frame)
        replies[reply.request_id].append(reply)
        body = reply.WhichOneof("body")
        assert body is not None
        if getattr(getattr(reply, body), "last", True):
            pending.discard(reply.request_id)
    return replies


@pytest.mark.e2e
def test_interleaved_result_streams_keep_their_request_ids(tmp_path: Path) -> None:
    stored_run = stored(tmp_path)
    priced(stored_run.root)
    tearsheet = GetTearsheet(run_id=stored_run.run_id)
    requests = [
        ClientMessage(
            request_id=2,
            get_series=GetSeries(
                run_id=stored_run.run_id, kind=SeriesKind.SERIES_KIND_FILLS
            ),
        ),
        ClientMessage(request_id=3, get_tearsheet=tearsheet),
        ClientMessage(request_id=4, list_runs=ListRuns()),
    ]

    async def scenario(url: str) -> None:
        async with client(url) as connection:
            await greet(connection)
            for request in requests:
                await connection.send(request.SerializeToString())
            replies = await collected(connection, {2, 3, 4})

        fills = b"".join(reply.series.data for reply in replies[2])
        assert len(pa.ipc.open_stream(fills).read_all()) == 2
        assert [reply.tearsheet.index for reply in replies[3]] == list(
            range(len(replies[3]))
        )
        sheet = b"".join(reply.tearsheet.data for reply in replies[3]).decode()
        assert sheet.rstrip().endswith("</html>")
        [listed] = replies[4]
        assert [each.run_id for each in listed.run_list.runs] == [stored_run.run_id]

    run(scenario, Server(Settings(TOKEN), routes(stored_run.root)))


@pytest.mark.e2e
def test_result_work_does_not_block_other_connections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored_run = stored(tmp_path)
    released = threading.Event()

    def held(_run: Any, path: Path, _benchmark: Any = None) -> None:
        released.wait(5)
        path.write_text("<html></html>")

    monkeypatch.setattr(core, "tearsheet", held)
    tearsheet = ClientMessage(
        request_id=2, get_tearsheet=GetTearsheet(run_id=stored_run.run_id)
    )
    listing = ClientMessage(request_id=2, list_runs=ListRuns())

    async def scenario(url: str) -> None:
        async with client(url) as rendering, client(url) as browsing:
            await greet(rendering)
            await rendering.send(tearsheet.SerializeToString())
            await greet(browsing)
            listed = await ask(browsing, listing.SerializeToString())
            answered_while_held = not released.is_set()
            released.set()
            [sheet] = (await collected(rendering, {2}))[2]

        assert answered_while_held
        assert listed.run_list.runs[0].run_id == stored_run.run_id
        assert sheet.tearsheet.data == b"<html></html>"

    run(scenario, Server(Settings(TOKEN), routes(stored_run.root)))
