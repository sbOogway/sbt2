from collections import defaultdict
from pathlib import Path

import pytest

QUADLET = Path(__file__).parents[2] / "sbt2-server.container"


def sections() -> dict[str, dict[str, list[str]]]:
    parsed: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    section = ""
    for line in QUADLET.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]")
            continue
        key, value = line.split("=", 1)
        parsed[section][key].append(value)
    return parsed


def container() -> dict[str, list[str]]:
    return sections()["Container"]


@pytest.mark.unit
def test_quadlet_runs_the_published_image_with_auto_update() -> None:
    unit = container()

    assert unit["Image"] == ["ghcr.io/sboogway/sbt2-server:latest"]
    assert unit["AutoUpdate"] == ["registry"]
    assert sections()["Install"]["WantedBy"] == ["default.target"]


@pytest.mark.unit
def test_quadlet_rolls_back_unless_healthy_and_binds_to_localhost() -> None:
    unit = container()

    assert unit["Notify"] == ["healthy"]
    assert "/health" in unit["HealthCmd"][0]
    assert unit["PublishPort"] == ["127.0.0.1:8765:8765"]


@pytest.mark.unit
def test_quadlet_keeps_data_and_config_in_volumes_and_reads_the_token_from_a_file() -> (
    None
):
    unit = container()

    assert unit["Volume"] == ["sbt2-data:/data", "sbt2-config:/config"]
    assert unit["EnvironmentFile"] == ["%h/.config/sbt2/server.env"]
