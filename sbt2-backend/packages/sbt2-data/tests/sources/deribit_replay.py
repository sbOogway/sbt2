"""A local HTTP server answering with Deribit responses recorded in
``deribit_responses.json``, and a synthetic day of perpetual candles."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from replay import replay
from synthetic_klines import deribit_chart

from sbt2.data.sources.deribit import DeribitSource, Endpoints

NO_DATA = {
    "request": (
        "/api/v2/public/get_tradingview_chart_data?instrument_name=BTC-PERPETUAL"
        "&start_timestamp=1451606400000&end_timestamp=1451692799999&resolution=1"
    ),
    "response": {
        "result": {"ticks": [], "status": "no_data", "open": [], "volume": []}
    },
}
RECORDED: list[dict[str, Any]] = [
    *json.loads(Path(__file__).with_name("deribit_responses.json").read_text()),
    deribit_chart("BTC-PERPETUAL"),
    NO_DATA,
]


@contextmanager
def deribit_replay() -> Generator[DeribitSource]:
    """Deribit, answering from the recorded responses."""
    with replay(RECORDED) as served:
        yield DeribitSource(frozenset(), Endpoints(api=served.url, live=served.url))
