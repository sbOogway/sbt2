import asyncio
import contextlib
import json
import os
import signal
import sys

from google.protobuf.message import DecodeError

from sbt2.protocol.v1.envelope_pb2 import ServerMessage
from sbt2.protocol.v1.runs_pb2 import StrategyModule
from sbt2.server.modules import clean_environment
from sbt2.server.strategies.encoding import InvalidArgumentError

DESCRIBER_MODULE = "sbt2.server.strategies.describer"


async def describe_in_process(module: StrategyModule, timeout: float) -> ServerMessage:
    """The reply of a process of its own that imports ``module`` with the clean
    environment of a job process. The process is killed after ``timeout`` seconds."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        DESCRIBER_MODULE,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=clean_environment(os.environ),
        start_new_session=True,
    )
    request = json.dumps({"name": module.name, "source": module.source})
    try:
        output, _ = await asyncio.wait_for(
            process.communicate(request.encode()), timeout
        )
    except TimeoutError:
        raise InvalidArgumentError(
            f"importing the module {module.name} took too long (over {timeout:g} s)"
        ) from None
    finally:
        await _kill(process)
    return _reply(output, module.name, process.returncode)


async def _kill(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    await process.wait()


def _reply(output: bytes, name: str, code: int | None) -> ServerMessage:
    try:
        return ServerMessage.FromString(output)
    except DecodeError:
        raise InvalidArgumentError(
            f"importing the module {name} ended its process with code {code}"
        ) from None
