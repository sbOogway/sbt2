from pathlib import Path

import pytest
import yaml

BACKEND = Path(__file__).parents[2]
LOOPBACK = "127.0.0.1"


def binds_only_loopback(publish: str) -> bool:
    parts = publish.split(":")
    return len(parts) == 3 and parts[0] == LOOPBACK


@pytest.mark.unit
def test_compose_publishes_the_server_port_only_on_loopback() -> None:
    compose = yaml.safe_load((BACKEND / "compose.yaml").read_text())

    ports = [p for s in compose["services"].values() for p in s.get("ports", [])]

    assert ports
    assert [p for p in ports if not binds_only_loopback(str(p))] == []


@pytest.mark.unit
def test_the_quadlet_publishes_the_server_port_only_on_loopback() -> None:
    lines = (BACKEND / "sbt2-server.container").read_text().splitlines()

    ports = [x.partition("=")[2] for x in lines if x.startswith("PublishPort=")]

    assert ports
    assert [p for p in ports if not binds_only_loopback(p)] == []


@pytest.mark.unit
def test_a_port_on_every_interface_is_caught() -> None:
    assert not binds_only_loopback("8765:8765")
    assert not binds_only_loopback("0.0.0.0:8765:8765")
    assert binds_only_loopback("127.0.0.1:8765:8765")
