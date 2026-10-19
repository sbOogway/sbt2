"""A local HTTP server answering with OKX responses recorded in ``okx_responses.json``."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from replay import replay
from synthetic_klines import okx_pages

from sbt2.data.sources.okx import Endpoints, OkxSource

RECORDED: list[dict[str, Any]] = [
    *json.loads(Path(__file__).with_name("okx_responses.json").read_text()),
    *okx_pages("BTC-USDT-SWAP"),
]


@contextmanager
def okx_replay() -> Generator[OkxSource]:
    """OKX, answering from the recorded responses, without pacing."""
    with replay(RECORDED) as served:
        yield OkxSource(frozenset(), Endpoints(api=served.url, pause=0.0))
