from pathlib import Path
from typing import Any

import pytest
import yaml

COMPOSE = Path(__file__).parents[2] / "compose.yaml"


def services() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text())["services"]


def mount_points(server: dict[str, Any]) -> dict[str, str]:
    mounts = (volume.split(":") for volume in server["volumes"])
    return {target: source for source, target in mounts}


@pytest.mark.unit
def test_compose_runs_the_server_with_its_data_and_config_volumes() -> None:
    declared = services()
    server = declared["server"]
    environment = server["environment"]

    assert list(declared) == ["server"]
    assert server["build"]["dockerfile"] == "Containerfile"
    assert mount_points(server) == {
        environment["SBT2_DATA"]: "data",
        environment["SBT2_CONFIG"]: "config",
    }
    assert server["ports"] == ["8765:8765"]
    assert environment["SBT2_SERVER_TOKEN"].startswith("${SBT2_SERVER_TOKEN")
    assert "/health" in server["healthcheck"]["test"][-1]
