from collections.abc import Iterator
from pathlib import Path

import pytest
from bybit_replay import bybit_replay

from sbt2.data.sources import Source, source
from sbt2.data.sources.bybit import BybitSource, Endpoints


@pytest.fixture
def bybit(tmp_path: Path) -> Source:
    """Bybit, without known gaps."""
    return source("bybit", tmp_path / "known_gaps.toml")


@pytest.fixture
def replayed() -> Iterator[Source]:
    """Bybit, answering from recorded responses."""
    with bybit_replay() as api:
        yield BybitSource(frozenset(), Endpoints(api=api))
