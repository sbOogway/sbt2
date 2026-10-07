"""A local HTTP server answering with Bybit responses recorded in ``bybit_responses.json``."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from replay import replay

RECORDED = Path(__file__).with_name("bybit_responses.json")


@contextmanager
def bybit_replay() -> Generator[str]:
    """Serve the recorded responses; yields the base URL to use as Bybit's API."""
    with replay(RECORDED) as served:
        yield served.url
