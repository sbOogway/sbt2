import asyncio
import subprocess
import time
import urllib.request
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from urllib.error import URLError

import pytest
from websockets.asyncio.client import connect
from websockets.typing import Subprotocol

from sbt2.protocol.v1.envelope_pb2 import ClientMessage, Hello, ServerMessage

pytestmark = [pytest.mark.e2e, pytest.mark.container]

BACKEND = Path(__file__).parents[2]
TAG = "localhost/sbt2-server:test"
PORT = 8765
TOKEN = "s3cret-token"
WITH_TOKEN = ("--env", f"SBT2_SERVER_TOKEN={TOKEN}")
# the image's HEALTHCHECK start period
START_PERIOD_SECONDS = 30
POLL_SECONDS = 0.2


def podman(*arguments: str) -> str:
    return subprocess.run(
        ["podman", *arguments], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(scope="session")
def image() -> str:
    podman(
        "build",
        # the OCI format drops HEALTHCHECK
        "--format=docker",
        f"--build-arg=SBT2_VERSION={version('sbt2-server')}",
        f"--tag={TAG}",
        f"--file={BACKEND / 'Containerfile'}",
        str(BACKEND),
    )
    return TAG


@contextmanager
def container(image: str, options: Sequence[str]) -> Generator[str]:
    name = podman("run", "--detach", f"--publish=127.0.0.1::{PORT}", *options, image)
    try:
        yield name
    finally:
        podman("rm", "--force", "--volumes", "--time=0", name)


def logs(name: str) -> str:
    return subprocess.run(
        ["podman", "logs", name],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout


def published(name: str) -> str:
    return podman("port", name, str(PORT)).splitlines()[0]


def health(address: str) -> int:
    with urllib.request.urlopen(f"http://{address}/health", timeout=1) as response:
        return response.status


def wait_for_health(address: str) -> int:
    deadline = time.monotonic() + START_PERIOD_SECONDS
    while True:
        try:
            return health(address)
        except URLError, ConnectionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(POLL_SECONDS)


def server_uid(name: str) -> int:
    status = podman("exec", name, "cat", "/proc/1/status")
    uids = next(line for line in status.splitlines() if line.startswith("Uid:"))
    return int(uids.split()[1])


async def greet(address: str) -> ServerMessage:
    async with connect(
        f"ws://{address}",
        subprotocols=[Subprotocol("sbt2.v1")],
        additional_headers={"Authorization": f"Bearer {TOKEN}"},
    ) as connection:
        hello = ClientMessage(request_id=1, hello=Hello(client_version="test"))
        await connection.send(hello.SerializeToString())
        reply = await connection.recv()
    assert isinstance(reply, bytes)
    return ServerMessage.FromString(reply)


def health_status(name: str) -> str:
    return podman("inspect", "--format={{.State.Health.Status}}", name)


def wait_for_healthy(name: str) -> str:
    deadline = time.monotonic() + START_PERIOD_SECONDS
    while (status := health_status(name)) != "healthy" and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
    return status


def test_the_image_serves_health_as_a_non_root_user(image: str) -> None:
    with container(image, [*WITH_TOKEN, "--volume=/data"]) as name:
        assert wait_for_health(published(name)) == 200
        assert server_uid(name) != 0


def test_the_image_answers_hello_with_the_token(image: str, tmp_path: Path) -> None:
    tmp_path.chmod(0o755)
    options = [*WITH_TOKEN, f"--volume={tmp_path}:/data:ro,Z"]
    with container(image, options) as name:
        address = published(name)
        wait_for_health(address)
        reply = asyncio.run(asyncio.wait_for(greet(address), timeout=10))

    assert reply.welcome.server_version == version("sbt2-server")


def test_the_container_without_a_token_exits_naming_it(image: str) -> None:
    with container(image, []) as name:
        status = podman("wait", name)
        log = logs(name)

    assert status == "2"
    assert "SBT2_SERVER_TOKEN" in log


def test_the_health_check_marks_the_container_healthy(image: str) -> None:
    with container(image, WITH_TOKEN) as name:
        assert wait_for_healthy(name) == "healthy"
