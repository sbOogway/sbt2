import pytest
from typer.testing import CliRunner

from sbt2.server import Address, Server
from sbt2.server.cli import app

runner = CliRunner()


def served_address(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> Address:
    served: list[Address] = []

    async def serve(_server: Server, address: Address) -> None:
        served.append(address)

    monkeypatch.setattr(Server, "serve", serve)
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    [address] = served
    return address


@pytest.mark.e2e
def test_the_server_needs_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SBT2_SERVER_TOKEN", raising=False)

    result = runner.invoke(app, [])

    assert result.exit_code == 2
    assert "SBT2_SERVER_TOKEN" in result.output


@pytest.mark.unit
def test_host_and_port_come_from_options_or_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SBT2_SERVER_TOKEN", "s3cret-token")
    monkeypatch.delenv("SBT2_SERVER_HOST", raising=False)
    monkeypatch.delenv("SBT2_SERVER_PORT", raising=False)
    assert served_address(monkeypatch, []) == Address("127.0.0.1", 8765)

    monkeypatch.setenv("SBT2_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("SBT2_SERVER_PORT", "9000")
    assert served_address(monkeypatch, []) == Address("0.0.0.0", 9000)

    options = ["--host", "::1", "--port", "9001"]
    assert served_address(monkeypatch, options) == Address("::1", 9001)
