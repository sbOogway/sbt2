import json
from collections.abc import Iterator, Sequence
from typing import Any, overload

from sbt2.lab.session import Session
from sbt2.protocol.v1.envelope_pb2 import ClientMessage
from sbt2.protocol.v1.results_pb2 import (
    HeadlineMetrics,
    ListRuns,
    RunFilter,
    RunIds,
    RunSummary,
)


class Run:
    """A run the server stored; its results are fetched when asked for."""

    def __init__(self, session: Session, summary: RunSummary) -> None:
        self._session = session
        self._summary = summary

    @property
    def run_id(self) -> str:
        return self._summary.run_id

    @property
    def strategy(self) -> str:
        return self._summary.strategy

    @property
    def part(self) -> str:
        return self._summary.part

    @property
    def params(self) -> dict[str, Any]:
        return json.loads(self._summary.params_json or "{}")

    @property
    def headline(self) -> dict[str, str | int | None]:
        """The headline metrics; ``None`` is undefined, not zero."""
        return _headline(self._summary.headline)

    def __repr__(self) -> str:
        return f"Run({self.run_id!r}, {self.strategy!r}, {self.part!r})"


class Runs(Sequence[Run]):
    """The runs of a job, in the order the spec expands into them."""

    def __init__(self, runs: Sequence[Run]) -> None:
        self._runs = tuple(runs)

    @overload
    def __getitem__(self, index: int) -> Run: ...

    @overload
    def __getitem__(self, index: slice) -> Runs: ...

    def __getitem__(self, index: int | slice) -> Run | Runs:
        if isinstance(index, slice):
            return Runs(self._runs[index])
        return self._runs[index]

    def __len__(self) -> int:
        return len(self._runs)

    def __iter__(self) -> Iterator[Run]:
        return iter(self._runs)


async def stored_runs(session: Session, run_ids: Sequence[str]) -> Runs:
    selected = RunFilter(run_ids=RunIds(values=run_ids))
    chunks = await session.ask(ClientMessage(list_runs=ListRuns(filter=selected)))
    summaries = {each.run_id: each for chunk in chunks for each in chunk.run_list.runs}
    return Runs([Run(session, summaries[each]) for each in run_ids])


def _headline(headline: HeadlineMetrics) -> dict[str, str | int | None]:
    return {
        "net_return": headline.net_return if headline.HasField("net_return") else None,
        "annualized_return": headline.annualized_return
        if headline.HasField("annualized_return")
        else None,
        "sharpe": headline.sharpe if headline.HasField("sharpe") else None,
        "max_drawdown": headline.max_drawdown
        if headline.HasField("max_drawdown")
        else None,
        "trade_count": headline.trade_count,
        "total_fees": headline.total_fees,
        "total_carry": headline.total_carry,
    }
