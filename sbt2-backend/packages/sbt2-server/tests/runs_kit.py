"""Requests that start runs, a session to send them in, and fake workers."""

import asyncio
import itertools
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, override

from google.protobuf.struct_pb2 import Struct
from results_kit import KeptReplies
from synthetic_catalog import build_catalog

from sbt2.core.config import ConfigFolder, Root
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.runs_pb2 import (
    Job,
    JobState,
    JobUpdate,
    SpecFile,
    StrategyModule,
    SubmitRun,
)
from sbt2.server import Handler, Router
from sbt2.server.runs.jobs import Jobs, Submission, Subscription
from sbt2.server.runs.wire import Event, Exited
from sbt2.server.runs.workers import Worker, Workers

_PLAIN = (
    "strategy",
    "instruments",
    "venue",
    "capital",
    "seed",
    "equity_interval",
    "liquidation",
    "bars",
    "study",
)
MODULE = "uploaded_trend"
STRATEGY = """\
import builtins
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from nautilus_trader.model import Bar, BarSpecification, OrderSide, Quantity

from sbt2.core.strategy import Strategy

builtins.UPLOADED_MODULE_WAS_IMPORTED = True


@dataclass(frozen=True)
class Params:
    hold_bars: int = 3
    mode: str = "trade"
    out: str = ""


class Uploaded(Strategy[Params]):
    Params = Params

    @classmethod
    def warmup(cls, params: Params) -> timedelta:
        return timedelta(hours=2)

    @classmethod
    def inputs(cls, params: Params) -> Sequence[BarSpecification]:
        return (BarSpecification.from_str("1-HOUR-LAST"),)

    def on_start(self) -> None:
        super().on_start()
        self.bars = 0
        self._misbehave(self.params.mode)

    def _misbehave(self, mode: str) -> None:
        if mode == "fail":
            raise RuntimeError("boom")
        if mode == "sleep":
            Path(self.params.out).write_text(str(os.getpid()))
            time.sleep(300)
        if mode == "print":
            print("hello from the strategy", flush=True)
        if mode == "environment":
            Path(self.params.out).write_text(json.dumps(sorted(os.environ)))

    def on_bar(self, bar: Bar) -> None:
        if self.warming_up:
            return
        self.bars += 1
        side = {1: OrderSide.BUY, 1 + self.params.hold_bars: OrderSide.SELL}.get(
            self.bars
        )
        if side is not None:
            quantity = Quantity.from_str("1.000")
            self.submit_order(
                self.order_factory.market(bar.bar_type.instrument_id, side, quantity)
            )
"""
VENUES = """
[linear]
name = "BYBIT"
source = "bybit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
default_leverage = "10"
fee_model = { kind = "maker_taker", config = { maker_rate = "0.0002", taker_rate = "0.00055" } }
"""
OVER = (
    JobState.JOB_STATE_FINISHED,
    JobState.JOB_STATE_FAILED,
    JobState.JOB_STATE_CANCELLED,
)


def struct(values: Mapping[str, Any]) -> Struct:
    message = Struct()
    message.update(_jsonable(values))
    return message


def spec_message(table: Mapping[str, Any]) -> SpecFile:
    """The ``SpecFile`` that carries a spec file's ``table``."""
    message = SpecFile(
        **{key: table[key] for key in _PLAIN if key in table},
        part=_parts(table.get("part", [])),
        split=struct(table.get("split", {})),
        params=struct(table.get("params", {})),
        risk=struct(table.get("risk", {})),
    )
    if "period" in table:
        start, end = table["period"]
        message.period.start_at.FromDatetime(_utc(start))
        message.period.end_at.FromDatetime(_utc(end))
    return message


def run_table(**overrides: Any) -> dict[str, Any]:
    """A spec of one run, over the two days the synthetic catalog holds."""
    return {
        "strategy": f"{MODULE}:Uploaded",
        "instruments": ["BTCUSDT-LINEAR.BYBIT"],
        "period": [
            datetime(2024, 1, 1, 2, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
        ],
        "venue": "linear",
        "capital": "10000 USDT",
        "part": ["train"],
        "split": {"validation_start": "2024-01-03", "test_start": "2024-01-04"},
        **overrides,
    }


def submit_run(table: Mapping[str, Any], source: str = STRATEGY) -> ClientMessage:
    name = table["strategy"].partition(":")[0]
    module = StrategyModule(name=name, source=source)
    return ClientMessage(
        submit_run=SubmitRun(spec=spec_message(table), strategy=module)
    )


def deployed(path: Path) -> tuple[Root, ConfigFolder]:
    """A data root with two days of data, and a config folder with one venue."""
    root, config = Root(path / "data"), ConfigFolder(path / "config")
    build_catalog(root.catalog)
    config.path.mkdir()
    config.venues.write_text(VENUES)
    return root, config


class Session:
    """One connection to the routes: it sends requests, and keeps the pushes."""

    def __init__(self, routes: dict[str, Handler]) -> None:
        self._router = Router(routes)
        self._ids = itertools.count(1)
        self.outbox = KeptReplies()

    async def ask(self, request: ClientMessage) -> ServerMessage:
        request.request_id = next(self._ids)
        reply = await self._router.answer(request, self.outbox)
        assert reply.request_id == request.request_id
        return reply

    @property
    def pushes(self) -> list[ServerMessage]:
        return list(self.outbox.messages)

    async def close(self) -> None:
        for task in self.outbox.tasks:
            task.cancel()
        await asyncio.gather(*self.outbox.tasks, return_exceptions=True)


async def until[T](found: Callable[[], T | None], timeout: float = 90) -> T:
    """What ``found`` returns once it is not None."""

    async def poll() -> T:
        while (result := found()) is None:
            await asyncio.sleep(0.05)
        return result

    return await asyncio.wait_for(poll(), timeout)


async def finished(jobs: Jobs, job_id: str) -> Job:
    """The job once it is over."""

    def over() -> Job | None:
        [job] = [each for each in jobs.list_jobs() if each.job_id == job_id]
        return job if job.state in OVER else None

    return await until(over)


class FakeWorker(Worker):
    """A job process the test drives: it reports what ``emit`` is given."""

    def __init__(self) -> None:
        self._queue = asyncio.Queue[Event]()
        self.started = False
        self.stopped = False

    def emit(self, *events: Event) -> None:
        for event in events:
            self._queue.put_nowait(event)

    @override
    async def events(self) -> AsyncIterator[Event]:
        while True:
            event = await self._queue.get()
            yield event
            if isinstance(event, Exited):
                return

    @override
    def start(self) -> None:
        self.started = True

    @override
    async def stop(self) -> None:
        self.stopped = True
        self.emit(Exited(143))


class FakeWorkers(Workers):
    """Launches a ``FakeWorker`` for each submission, which ``script`` sets going."""

    def __init__(self, script: Callable[[FakeWorker], None] = lambda _: None) -> None:
        self._script = script
        self.launched: list[tuple[Submission, FakeWorker]] = []

    @override
    async def launch(self, submission: Submission) -> Worker:
        worker = FakeWorker()
        self.launched.append((submission, worker))
        self._script(worker)
        return worker


class ScriptedSubscription(Subscription):
    def __init__(
        self, updates: list[JobUpdate], log_lines: list[str] | None = None
    ) -> None:
        super().__init__(
            Job(job_id="job", state=JobState.JOB_STATE_RUNNING), log_lines or []
        )
        self._updates = updates
        self.closed = False

    @override
    async def updates(self) -> AsyncIterator[JobUpdate]:
        for update in self._updates:
            yield update
            await asyncio.sleep(0)

    @override
    def close(self) -> None:
        self.closed = True


def _parts(part: str | list[str]) -> list[str]:
    return [part] if isinstance(part, str) else part


def _utc(moment: date | datetime) -> datetime:
    if isinstance(moment, datetime):
        return moment.replace(tzinfo=moment.tzinfo or UTC)
    return datetime.combine(moment, time(), tzinfo=UTC)


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: _jsonable(each) for key, each in value.items()}
    if isinstance(value, list):
        return [_jsonable(each) for each in value]
    return value
