from collections.abc import Iterator
from pathlib import Path

import pytest
from bybit_replay import bybit_replay
from deribit_replay import RECORDED as DERIBIT_RECORDED
from replay import Replay, replay

from sbt2.data.sources import Source, source
from sbt2.data.sources.bybit import BybitSource, Endpoints
from sbt2.data.sources.deribit import DeribitSource
from sbt2.data.sources.deribit import Endpoints as DeribitEndpoints


@pytest.fixture
def bybit(tmp_path: Path) -> Source:
    """Bybit, without known gaps."""
    return source("bybit", tmp_path / "known_gaps.toml")


@pytest.fixture
def replayed() -> Iterator[Source]:
    """Bybit, answering from recorded responses."""
    with bybit_replay() as api:
        yield BybitSource(frozenset(), Endpoints(api=api))


@pytest.fixture
def deribit(tmp_path: Path) -> Source:
    """Deribit, without known gaps."""
    return source("deribit", tmp_path / "known_gaps.toml")


@pytest.fixture
def replayed_deribit() -> Iterator[tuple[Source, Replay]]:
    """Deribit, answering from recorded responses, and the requests it made."""
    with replay(DERIBIT_RECORDED) as served:
        yield DeribitSource(frozenset(), DeribitEndpoints(api=served.url)), served
