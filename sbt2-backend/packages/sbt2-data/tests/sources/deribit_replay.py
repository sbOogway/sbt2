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

CONTRACTS = (
    "BTC-27DEC24",
    "BTC-3JAN25",
    "BTC-10JAN25",
    "BTC-31JAN25",
    "BTC-28FEB25",
    "BTC-28MAR25",
    "BTC-27JUN25",
    "BTC-26SEP25",
    "BTC-26DEC25",
    "BTC-17JAN25",
)

RECORDED: list[dict[str, Any]] = json.loads(
    Path(__file__).with_name("deribit_responses.json").read_text()
)


def deribit_stub() -> DeribitClientStub:
    """A client that holds a day of bars of the BTC perpetual and of each of the
    recorded BTC dated futures, the ones not alive that day too."""
    types = [BTC_PERPETUAL_BARS] + [
        BarType.from_str(f"{each}.DERIBIT-1-MINUTE-LAST-EXTERNAL") for each in CONTRACTS
    ]
    return DeribitClientStub([bar for each in types for bar in synthetic_day(each, 0)])


@contextmanager
def deribit_replay(client: DeribitClientStub | None = None) -> Generator[DeribitSource]:
    """Deribit, answering from the recorded responses and the stand-in client."""
    with replay(RECORDED) as served:
        yield DeribitSource(
            frozenset(),
            Endpoints(api=served.url, live=served.url),
            client or deribit_stub(),
        )
