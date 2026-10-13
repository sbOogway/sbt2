from decimal import Decimal
from pathlib import Path

import pytest
from option_catalog import build_ladder_catalog


@pytest.fixture(scope="module")
def ladder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("ladder_catalog")
    build_ladder_catalog(path)
    return path


@pytest.fixture(scope="module")
def falling(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("falling_catalog")
    build_ladder_catalog(path, mark_step=Decimal("-0.001"))
    return path
