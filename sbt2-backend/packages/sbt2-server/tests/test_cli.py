from pathlib import Path

import pytest
from results_kit import stored
from server_kit import TOKEN, ask, client, greet, run
from typer.testing import CliRunner

from sbt2.core import spec
from sbt2.protocol.v1.config_pb2 import ListVenueProfiles
from sbt2.protocol.v1.envelope_pb2 import Capability, ClientMessage, Welcome
from sbt2.protocol.v1.results_pb2 import ListRuns
from sbt2.server import Address, Server
from sbt2.server.cli import app

runner = CliRunner()
PROFILE = {
    "name": "BYBIT",
    "source": "bybit",
    "asset_class": "CRYPTOCURRENCY",
    "instrument_class": "SWAP",
}


@pytest.fixture(autouse=True)
def config_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The config folder SBT2_CONFIG names for every command."""
    folder = tmp_path / "config"
    monkeypatch.setenv("SBT2_CONFIG", str(folder))
    return folder


def served(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> tuple[Server, Address]:
    """The server the command starts with ``args``, and the address it serves."""
    started: list[tuple[Server, Address]] = []

    async def serve(server: Server, address: Address) -> None:
        started.append((server, address))

    monkeypatch.setattr(Server, "serve", serve)
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    [each] = started
    return each


def served_address(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> Address:
    return served(monkeypatch, args)[1]


def browsed(server: Server) -> tuple[Welcome, list[str]]:
    """The server's welcome, and the run ids it lists."""
    seen: list[tuple[Welcome, list[str]]] = []

    async def scenario(url: str) -> None:
        async with client(url) as connection:
            welcome = (await greet(connection)).welcome
            listing = ClientMessage(request_id=2, list_runs=ListRuns())
            listed = await ask(connection, listing.SerializeToString())
        seen.append((welcome, [each.run_id for each in listed.run_list.runs]))

    run(scenario, server)
    [each] = seen
    return each


@pytest.mark.e2e
def test_the_server_needs_a_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SBT2_SERVER_TOKEN", raising=False)
    monkeypatch.setenv("SBT2_DATA", str(tmp_path))

    result = runner.invoke(app, [])

    assert result.exit_code == 2
    assert "SBT2_SERVER_TOKEN" in result.output


@pytest.mark.unit
def test_host_and_port_come_from_options_or_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SBT2_SERVER_TOKEN", "s3cret-token")
    monkeypatch.setenv("SBT2_DATA", str(tmp_path))
    monkeypatch.delenv("SBT2_SERVER_HOST", raising=False)
    monkeypatch.delenv("SBT2_SERVER_PORT", raising=False)
    assert served_address(monkeypatch, []) == Address("127.0.0.1", 8765)

    monkeypatch.setenv("SBT2_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("SBT2_SERVER_PORT", "9000")
    assert served_address(monkeypatch, []) == Address("0.0.0.0", 9000)

    options = ["--host", "::1", "--port", "9001"]
    assert served_address(monkeypatch, options) == Address("::1", 9001)


@pytest.mark.e2e
def test_server_requires_a_data_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SBT2_SERVER_TOKEN", TOKEN)
    monkeypatch.delenv("SBT2_DATA", raising=False)

    result = runner.invoke(app, [])

    assert result.exit_code == 2
    assert "--data" in result.output


@pytest.mark.unit
def test_data_option_overrides_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chosen = stored(tmp_path / "chosen")
    stored(tmp_path / "environment")
    monkeypatch.setenv("SBT2_SERVER_TOKEN", TOKEN)
    monkeypatch.setenv("SBT2_DATA", str(tmp_path / "environment"))

    server, _ = served(monkeypatch, ["--data", str(tmp_path / "chosen")])

    assert browsed(server)[1] == [chosen.run_id]


@pytest.mark.e2e
def test_server_command_exposes_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored_run = stored(tmp_path)
    monkeypatch.setenv("SBT2_SERVER_TOKEN", TOKEN)
    monkeypatch.setenv("SBT2_DATA", str(tmp_path))

    server, _ = served(monkeypatch, [])
    welcome, run_ids = browsed(server)

    assert Capability.CAPABILITY_RESULTS in welcome.capabilities
    assert run_ids == [stored_run.run_id]


def profile_names(server: Server) -> list[str]:
    """The names of the venue profiles the server lists."""
    seen: list[list[str]] = []

    async def scenario(url: str) -> None:
        async with client(url) as connection:
            await greet(connection)
            listing = ClientMessage(
                request_id=2, list_venue_profiles=ListVenueProfiles()
            )
            listed = await ask(connection, listing.SerializeToString())
        seen.append([each.name for each in listed.venue_profiles.profiles])

    run(scenario, server)
    [each] = seen
    return each


@pytest.mark.unit
def test_the_server_reads_its_config_folder_from_sbt2_config(
    tmp_path: Path, config_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec.put_venue_profile(config_folder / "venues.toml", "linear", PROFILE)
    monkeypatch.setenv("SBT2_SERVER_TOKEN", TOKEN)
    monkeypatch.setenv("SBT2_DATA", str(tmp_path / "data"))

    server, _ = served(monkeypatch, [])

    assert profile_names(server) == ["linear"]


@pytest.mark.integration
def test_welcome_announces_the_config_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SBT2_SERVER_TOKEN", TOKEN)
    monkeypatch.setenv("SBT2_DATA", str(tmp_path / "data"))

    server, _ = served(monkeypatch, [])

    assert Capability.CAPABILITY_CONFIG in browsed(server)[0].capabilities
