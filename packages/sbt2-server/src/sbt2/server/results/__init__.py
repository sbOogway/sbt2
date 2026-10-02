import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from functools import wraps
from typing import BinaryIO

import pandas as pd

from sbt2.core import results as core
from sbt2.core.config import Root
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.results_pb2 import (
    GetSeries,
    Metrics,
    RunList,
    Series,
    SeriesKind,
)
from sbt2.protocol.v1.types_pb2 import Error, ErrorCode
from sbt2.server import Handler, Outbox, offloaded
from sbt2.server.results.encoding import (
    equity,
    metrics,
    run_filter,
    summary,
    write_arrow,
)
from sbt2.server.results.streaming import (
    TooLargeError,
    checked,
    deliver,
    pieces,
    records,
)


def routes(root: Root) -> dict[str, Handler]:
    """Handlers for browsing the results under ``root`` through core's public API."""
    results = _Results(core.store_at(root))
    return {
        "list_runs": _guard(results.list_runs),
        "get_run": _guard(results.get_run),
        "get_metrics": _guard(results.get_metrics),
        "get_series": _guard(results.get_series),
    }


class _InvalidArgumentError(ValueError):
    pass


@dataclass
class _Results:
    store: core.ResultStore

    async def list_runs(self, request: ClientMessage, outbox: Outbox) -> ServerMessage:
        replies = await offloaded(self._listed)(request)
        return await deliver(replies, outbox)

    def _listed(self, request: ClientMessage) -> Iterator[ServerMessage]:
        frame = self.store.runs(run_filter(request.list_runs.filter))
        items = (summary(row) for row in frame.to_dict("records"))
        template = ServerMessage(request_id=request.request_id, run_list=RunList())
        return records(template, "runs", items)

    async def get_run(self, request: ClientMessage, _outbox: Outbox) -> ServerMessage:
        return await offloaded(self._summary)(request)

    def _summary(self, request: ClientMessage) -> ServerMessage:
        [row] = self.store.load(request.get_run.run_id, "summary").to_dict("records")
        return checked(
            ServerMessage(request_id=request.request_id, run_summary=summary(row))
        )

    async def get_metrics(
        self, request: ClientMessage, outbox: Outbox
    ) -> ServerMessage:
        replies = await offloaded(self._metrics)(request)
        return await deliver(replies, outbox)

    def _metrics(self, request: ClientMessage) -> Iterator[ServerMessage]:
        run = self.store.stored_run(request.get_metrics.run_id)
        measured = core.full_metrics(run.tables, core.Segment.of_run(run.spec))
        template = ServerMessage(
            request_id=request.request_id, metrics=Metrics(currency=run.tables.currency)
        )
        return records(template, "entries", metrics(measured))

    async def get_series(self, request: ClientMessage, outbox: Outbox) -> ServerMessage:
        """Equity has the columns ts_event, currency and total_equity; fills are
        the stored rows, indexed by client_order_id."""
        with tempfile.TemporaryFile() as staged:
            await offloaded(self._stage_series)(request.get_series, staged)
            template = ServerMessage(request_id=request.request_id, series=Series())
            return await deliver(pieces(template, staged), outbox)

    def _stage_series(self, selected: GetSeries, staged: BinaryIO) -> None:
        write_arrow(self._series(selected), staged)
        staged.seek(0)

    def _series(self, selected: GetSeries) -> pd.DataFrame:
        match selected.kind:
            case SeriesKind.SERIES_KIND_EQUITY:
                run = self.store.stored_run(selected.run_id)
                segment = core.Segment.of_run(run.spec)
                curve = core.equity_curve(
                    run.tables.equity, run.tables.currency, segment
                )
                return equity(curve, run.tables.currency)
            case SeriesKind.SERIES_KIND_FILLS:
                return self.store.load(selected.run_id, "fills")
            case _:
                raise _InvalidArgumentError


def _guard(handler: Handler) -> Handler:
    @wraps(handler)
    async def answer(request: ClientMessage, outbox: Outbox) -> ServerMessage:
        try:
            return await handler(request, outbox)
        except core.UnknownRunError, core.MissingTableError:
            return _error(
                ErrorCode.ERROR_CODE_NOT_FOUND,
                "The run or required data was not found.",
            )
        except _InvalidArgumentError:
            return _error(
                ErrorCode.ERROR_CODE_INVALID_ARGUMENT, "The selection is not valid."
            )
        except TooLargeError:
            return _error(
                ErrorCode.ERROR_CODE_RESOURCE_EXHAUSTED,
                "A result record exceeds the 1 MiB envelope limit.",
            )

    return answer


def _error(code: ErrorCode.ValueType, message: str) -> ServerMessage:
    return ServerMessage(error=Error(code=code, message=message))


__all__ = ["routes"]
