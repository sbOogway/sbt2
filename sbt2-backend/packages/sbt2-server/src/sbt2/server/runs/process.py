import asyncio
import contextlib
import os
import socket
import sys
from collections.abc import AsyncIterator, Mapping
from typing import Self, override

from sbt2.core.config import ConfigFolder, Root
from sbt2.server.modules import clean_environment
from sbt2.server.runs.jobs import Submission
from sbt2.server.runs.lines import Lines
from sbt2.server.runs.wire import (
    GO,
    Event,
    Exited,
    JobRequest,
    LogLines,
    decode,
)
from sbt2.server.runs.workers import Worker, Workers

WORKER_MODULE = "sbt2.server.runs.worker"
STOP_SECONDS = 15
STREAM_GRACE_SECONDS = 2
_CHUNK = 65_536
_REPORT_LIMIT = 2**22


class ProcessWorkers(Workers):
    """Runs each job in a Python process of its own, which gets the environment
    of the server without its ``SBT2_SERVER_*`` variables, the API token among
    them."""

    def __init__(self, root: Root, config: ConfigFolder) -> None:
        self._root = root
        self._config = config

    @override
    async def launch(self, submission: Submission) -> Worker:
        request = JobRequest(
            data_root=str(self._root.path),
            venues=str(self._config.venues),
            module_name=submission.module.name,
            module_source=submission.module.source,
            spec=dict(submission.spec),
        )
        return await _ProcessWorker.launch(request)


class _ProcessWorker(Worker):
    """The process's reports and its output reach ``events`` through one queue;
    the process's channel is a socket pair, apart from its output."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        reports: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._process = process
        self._writer = writer
        self._queue = asyncio.Queue[Event]()
        readers = [
            asyncio.create_task(self._read_reports(reports)),
            asyncio.create_task(self._read_output(_stdout(process))),
        ]
        self._finishing = asyncio.create_task(self._finish(readers))

    @classmethod
    async def launch(cls, request: JobRequest) -> Self:
        ours, theirs = socket.socketpair()
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                WORKER_MODULE,
                str(theirs.fileno()),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=_environment(os.environ),
                pass_fds=[theirs.fileno()],
                start_new_session=True,
            )
        except BaseException:
            ours.close()
            raise
        finally:
            theirs.close()
        reports, writer = await asyncio.open_connection(sock=ours, limit=_REPORT_LIMIT)
        writer.write(f"{request.to_line()}\n".encode())
        return cls(process, reports, writer)

    @override
    async def events(self) -> AsyncIterator[Event]:
        while True:
            event = await self._queue.get()
            yield event
            if isinstance(event, Exited):
                return

    @override
    def start(self) -> None:
        self._writer.write(f"{GO}\n".encode())

    @override
    async def stop(self) -> None:
        if self._process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), STOP_SECONDS)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                self._process.kill()
            await self._process.wait()

    async def _read_reports(self, reports: asyncio.StreamReader) -> None:
        async for line in reports:
            self._queue.put_nowait(decode(line.decode()))

    async def _read_output(self, output: asyncio.StreamReader) -> None:
        lines = Lines()
        while chunk := await output.read(_CHUNK):
            if complete := lines.feed(chunk):
                self._queue.put_nowait(LogLines(tuple(complete)))
        if last := lines.flush():
            self._queue.put_nowait(LogLines(tuple(last)))

    async def _finish(self, readers: list[asyncio.Task[None]]) -> None:
        code = await self._process.wait()
        # a process the job left running can hold the output open
        _, lingering = await asyncio.wait(readers, timeout=STREAM_GRACE_SECONDS)
        for reader in lingering:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        self._writer.close()
        with contextlib.suppress(ConnectionError):
            await self._writer.wait_closed()
        self._queue.put_nowait(Exited(code))


def _environment(server: Mapping[str, str]) -> dict[str, str]:
    return {**clean_environment(server), "PYTHONUNBUFFERED": "1"}


def _stdout(process: asyncio.subprocess.Process) -> asyncio.StreamReader:
    if process.stdout is None:
        raise RuntimeError("the job process has no output pipe")
    return process.stdout
