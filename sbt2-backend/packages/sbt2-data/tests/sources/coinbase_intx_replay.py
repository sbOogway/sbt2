"""A local HTTP server answering with Coinbase International responses recorded in
``coinbase_intx_responses.json``."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from replay import replay

from sbt2.data.sources.coinbase_intx import CoinbaseIntxSource, Endpoints

RECORDED = Path(__file__).with_name("coinbase_intx_responses.json")


@contextmanager
def coinbase_intx_replay() -> Generator[CoinbaseIntxSource]:
    """Coinbase International, answering from the recorded responses, without pacing."""
    with replay(RECORDED) as served:
        yield CoinbaseIntxSource(frozenset(), Endpoints(api=served.url, pause=0.0))
