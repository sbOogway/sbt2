from collections.abc import Iterator
from pathlib import Path

import pytest
from bybit_replay import bybit_replay

from sbt2.sources import Source, source
from sbt2.sources.bybit import BybitSource, Endpoints

REPO_CONFIG = Path(__file__).parents[2] / "config" / "sources.toml"


@pytest.fixture
def bybit() -> Source:
    """Bybit as configured in the repo."""
    return source("bybit", REPO_CONFIG)


@pytest.fixture
def replayed() -> Iterator[Source]:
    """Bybit, answering from recorded responses."""
    with bybit_replay() as api:
        yield BybitSource(frozenset(), Endpoints(api=api))
