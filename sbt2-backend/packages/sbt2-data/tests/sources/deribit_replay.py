"""A local HTTP server answering with Deribit responses recorded in ``deribit_responses.json``."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from replay import replay

from sbt2.data.sources.deribit import DeribitSource, Endpoints

RECORDED = Path(__file__).with_name("deribit_responses.json")


@contextmanager
def deribit_replay() -> Generator[DeribitSource]:
    """Deribit, answering from the recorded responses."""
    with replay(RECORDED) as served:
        yield DeribitSource(frozenset(), Endpoints(api=served.url))
