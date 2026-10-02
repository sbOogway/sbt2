from collections.abc import Iterator
from dataclasses import dataclass
from functools import wraps

from sbt2.core import results as core
from sbt2.core.config import Root
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.results_pb2 import Metrics, RunList
from sbt2.protocol.v1.types_pb2 import Error, ErrorCode
from sbt2.server import Handler, Outbox, offloaded
from sbt2.server.results.encoding import metrics, run_filter, summary
from sbt2.server.results.streaming import TooLargeError, checked, deliver, records


def routes(root: Root) -> dict[str, Handler]:
    """Handlers for browsing the results under ``root`` through core's public API."""
    results = _Results(core.store_at(root))
    return {
        "list_runs": _guard(results.list_runs),
        "get_run": _guard(results.get_run),
        "get_metrics": _guard(results.get_metrics),
    }


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
        except TooLargeError:
            return _error(
                ErrorCode.ERROR_CODE_RESOURCE_EXHAUSTED,
                "A result record exceeds the 1 MiB envelope limit.",
            )

    return answer


def _error(code: ErrorCode.ValueType, message: str) -> ServerMessage:
    return ServerMessage(error=Error(code=code, message=message))


__all__ = ["routes"]
