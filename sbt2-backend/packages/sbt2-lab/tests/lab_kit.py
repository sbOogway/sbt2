import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Sequence
from contextlib import asynccontextmanager

from sbt2.protocol.v1.envelope_pb2 import (
    Capability,
    ClientMessage,
    ServerMessage,
    Welcome,
)
from sbt2.protocol.v1.results_pb2 import HeadlineMetrics, RunList, RunSummary
from sbt2.protocol.v1.runs_pb2 import (
    Job,
    JobState,
    JobSubmitted,
    JobSubscribed,
    JobUpdate,
    RunState,
    RunStatus,
)
from sbt2.server import Address, Handler, Outbox, Server, Settings

TOKEN = "lab-token"
SERVED = (Capability.CAPABILITY_RUNS, Capability.CAPABILITY_RESULTS)

type Scenario = Callable[[str], Awaitable[None]]


class FakeServer:
    """The real server transport with handlers a test registers; it records
    every request it receives."""

    def __init__(self, capabilities: Iterable[Capability.ValueType] = SERVED) -> None:
        self.requests: list[ClientMessage] = []
        self._welcome = Welcome(server_version="fake", capabilities=capabilities)
        self._routes: dict[str, Handler] = {"hello": self._hello}

    def answer(self, body: str, handler: Handler) -> None:
        self._routes[body] = handler

    def received(self, body: str) -> list[ClientMessage]:
        return [each for each in self.requests if each.WhichOneof("body") == body]

    @asynccontextmanager
    async def serving(self) -> AsyncGenerator[str]:
        routes = {body: self._recorded(each) for body, each in self._routes.items()}
        server = Server(Settings(TOKEN), routes)
        async with server.listening(Address("127.0.0.1", 0)) as bound:
            yield f"ws://{bound.host}:{bound.port}"

    def _recorded(self, handler: Handler) -> Handler:
        async def recorded(request: ClientMessage, outbox: Outbox) -> ServerMessage:
            self.requests.append(request)
            return await handler(request, outbox)

        return recorded

    async def _hello(self, _request: ClientMessage, _outbox: Outbox) -> ServerMessage:
        return ServerMessage(welcome=self._welcome)


def run(scenario: Scenario, server: FakeServer) -> None:
    async def main() -> None:
        async with server.serving() as url:
            await asyncio.wait_for(scenario(url), timeout=10)

    asyncio.run(main())


def replying(message: ServerMessage) -> Handler:
    async def reply(_request: ClientMessage, _outbox: Outbox) -> ServerMessage:
        return message

    return reply


JOB_ID = "job-1"
SUBSCRIPTION_ID = 7
CROSS = """from sbt2.core.strategy import Strategy


class Cross(Strategy):
    pass
"""


def summary(run_id: str, sharpe: str = "1.5") -> RunSummary:
    return RunSummary(
        run_id=run_id,
        strategy="my_strats:Cross",
        part="train",
        params_json='{"fast": 10}',
        currency="USDT",
        headline=HeadlineMetrics(sharpe=sharpe, trade_count=3, total_fees="1.2"),
    )


def serve_job(
    server: FakeServer, runs: Sequence[RunSummary], updates: Sequence[JobUpdate] = ()
) -> None:
    """A job of ``runs``; it is over when subscribed unless ``updates`` follow."""
    run_ids = [each.run_id for each in runs]
    state = JobState.JOB_STATE_RUNNING if updates else JobState.JOB_STATE_FINISHED
    server.answer(
        "submit_run",
        replying(
            ServerMessage(job_submitted=JobSubmitted(job_id=JOB_ID, run_ids=run_ids))
        ),
    )
    server.answer(
        "subscribe_job", _subscriber(Job(job_id=JOB_ID, state=state), updates)
    )
    server.answer(
        "list_runs", replying(ServerMessage(run_list=RunList(last=True, runs=runs)))
    )


def _subscriber(job: Job, updates: Sequence[JobUpdate]) -> Handler:
    async def push(outbox: Outbox) -> None:
        for update in updates:
            await asyncio.sleep(0)
            outbox.push(
                ServerMessage(subscription_id=SUBSCRIPTION_ID, job_update=update)
            )

    async def subscribe(_request: ClientMessage, outbox: Outbox) -> ServerMessage:
        outbox.spawn(push(outbox))
        subscribed = JobSubscribed(subscription_id=SUBSCRIPTION_ID, job=job)
        return ServerMessage(job_subscribed=subscribed)

    return subscribe


def finished(*run_ids: str) -> JobUpdate:
    return JobUpdate(
        state=JobState.JOB_STATE_FINISHED,
        runs=[
            RunState(run_id=each, state=RunStatus.RUN_STATUS_FINISHED)
            for each in run_ids
        ],
    )
