import asyncio
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_run import START, RunOutput, round_trip_with_funding, spec
from price_catalog import BTC, FEE_MODEL, PriceCatalog

from sbt2.core.config import Root
from sbt2.core.results import ParquetResultStore, ResultStore, RunIds
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.server import Handler, Outbox, Router

BASE_STRATEGY = "sbt2.core.strategy:Strategy"


class KeptReplies(Outbox):
    def __init__(self) -> None:
        self.messages: list[ServerMessage] = []

    def push(self, message: ServerMessage) -> None:
        self.messages.append(message)

    async def send(self, message: ServerMessage) -> None:
        self.messages.append(message)


def ask(routes: dict[str, Handler], request: ClientMessage) -> list[ServerMessage]:
    [replies] = ask_together(routes, [request])
    return replies


def ask_together(
    routes: dict[str, Handler], requests: list[ClientMessage]
) -> list[list[ServerMessage]]:
    """The replies to ``requests`` answered concurrently, in request order."""

    async def answer_all() -> list[list[ServerMessage]]:
        router = Router(routes)
        return await asyncio.gather(*(_answered(router, each) for each in requests))

    return asyncio.run(answer_all())


async def _answered(router: Router, request: ClientMessage) -> list[ServerMessage]:
    replies = KeptReplies()
    replies.messages.append(await router.answer(request, replies))
    return replies.messages


@dataclass(frozen=True)
class StoredResults:
    root: Root
    store: ResultStore
    run_id: str


def stored(path: Path, strategy: str = BASE_STRATEGY) -> StoredResults:
    output = round_trip_with_funding()
    return _stored(path, output, strategy)


def stored_without_fills(path: Path) -> StoredResults:
    output = round_trip_with_funding()
    reports = replace(output.reports, fills=output.reports.fills.iloc[0:0])
    return _stored(path, replace(output, reports=reports), BASE_STRATEGY)


def _stored(path: Path, output: RunOutput, strategy: str) -> StoredResults:
    root = Root(path)
    store = ParquetResultStore(root.results)
    run = spec()
    run = replace(
        run,
        strategy=replace(run.strategy, strategy=strategy, params={}),
        venue={**run.venue, "fee_model": FEE_MODEL},
    )
    sink = store.new_run(run, ids=RunIds(batch_id="batch-1"))
    sink.write_equity(output.snapshots)
    sink.write_carry(output.carry)
    sink.write_reports(output.reports)
    sink.finalize()
    return StoredResults(root, store, sink.run_id)


def priced(root: Root) -> None:
    """Hourly BTC marks in ``root``'s catalog over the stored run."""
    root.catalog.mkdir(parents=True, exist_ok=True)
    marks = {START + timedelta(hours=hour): 50_000.0 + 40 * hour for hour in range(25)}
    PriceCatalog(root.catalog).add_marks(BTC, marks)


def summary_record() -> dict[str, Any]:
    return {
        "run_id": "0198cc00-0000-7000-8000-000000000001",
        "batch_id": None,
        "study": None,
        "spec_hash": "hash",
        "strategy": "example:Trend",
        "params": "{}",
        "instruments": ["BTCUSDT-LINEAR.BYBIT"],
        "start": pd.Timestamp("2024-01-01T00:00:00.123456789Z"),
        "end": pd.Timestamp("2024-01-02T00:00:00Z"),
        "split": "{}",
        "part": "train",
        "known_gaps": [],
        "currency": "USDT",
        "net_return": 0.0,
        "annualized_return": None,
        "sharpe": float("nan"),
        "max_drawdown": -0.1,
        "trade_count": 0,
        "total_fees": 0.000001,
        "total_carry": -5.25,
        "drawdown_tripped_at": pd.NaT,
    }
