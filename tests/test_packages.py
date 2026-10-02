import importlib

import pytest


@pytest.mark.unit
@pytest.mark.parametrize(
    "name",
    ["sbt2.core", "sbt2.strategies", "sbt2.papers", "sbt2.protocol.v1.envelope_pb2"],
)
def test_package_imports(name: str) -> None:
    importlib.import_module(name)
