from importlib.metadata import version

import pytest
from lab_kit import TOKEN, FakeServer, run

from sbt2.lab import ConnectError, Lab, MissingCapabilityError
from sbt2.protocol.v1.envelope_pb2 import Capability


@pytest.mark.integration
def test_connect_greets_the_server_with_the_lab_version() -> None:
    server = FakeServer()

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN):
            pass

    run(scenario, server)

    [hello] = server.received("hello")
    assert hello.hello.client_version == version("sbt2-lab")


@pytest.mark.integration
def test_a_wrong_token_fails_to_connect() -> None:
    async def scenario(url: str) -> None:
        with pytest.raises(ConnectError, match="401"):
            await Lab.connect(url, "wrong-token")

    run(scenario, FakeServer())


@pytest.mark.integration
def test_a_server_without_runs_and_results_is_refused() -> None:
    server = FakeServer(capabilities=[Capability.CAPABILITY_RESULTS])

    async def scenario(url: str) -> None:
        with pytest.raises(MissingCapabilityError, match="runs"):
            await Lab.connect(url, TOKEN)

    run(scenario, server)
