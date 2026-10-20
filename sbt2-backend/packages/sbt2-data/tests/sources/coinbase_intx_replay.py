"""A local HTTP server answering with Coinbase International responses recorded in
``coinbase_intx_responses.json``."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from replay import replay
from synthetic_klines import coinbase_pages

from sbt2.data.sources.coinbase_intx import CoinbaseIntxSource, Endpoints

RECORDED: list[dict[str, Any]] = [
    *json.loads(Path(__file__).with_name("coinbase_intx_responses.json").read_text()),
    *coinbase_pages("BTC-PERP"),
]


@contextmanager
def coinbase_intx_replay() -> Generator[CoinbaseIntxSource]:
    """Coinbase International, answering from the recorded responses, without pacing."""
    with replay(RECORDED) as served:
        yield CoinbaseIntxSource(frozenset(), Endpoints(api=served.url, pause=0.0))
