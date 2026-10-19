"""A local HTTP server answering with Deribit responses recorded in
``deribit_responses.json``, and a stand-in for the nautilus client, which serves
a synthetic day of perpetual candles."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from nautilus_stubs import DeribitClientStub, synthetic_day
from nautilus_trader.model import BarType
from replay import replay

from sbt2.data.sources.deribit import DeribitSource, Endpoints

BTC_PERPETUAL_BARS = BarType.from_str("BTC-PERPETUAL.DERIBIT-1-MINUTE-LAST-EXTERNAL")

RECORDED: list[dict[str, Any]] = json.loads(
    Path(__file__).with_name("deribit_responses.json").read_text()
)


def deribit_stub() -> DeribitClientStub:
    """A client that holds a day of the BTC perpetual's bars."""
    return DeribitClientStub(synthetic_day(BTC_PERPETUAL_BARS, 0))


@contextmanager
def deribit_replay(client: DeribitClientStub | None = None) -> Generator[DeribitSource]:
    """Deribit, answering from the recorded responses and the stand-in client."""
    with replay(RECORDED) as served:
        yield DeribitSource(
            frozenset(),
            Endpoints(api=served.url, live=served.url),
            client or deribit_stub(),
        )
