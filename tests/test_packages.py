import importlib

import pytest


@pytest.mark.parametrize("name", ["sbt2", "strategies"])
def test_package_imports(name: str) -> None:
    importlib.import_module(name)
