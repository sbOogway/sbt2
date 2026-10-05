"""A process of its own that imports an uploaded module and describes its strategy.

``python -m sbt2.server.strategies.describer`` reads the module's name and source
as JSON from stdin and writes one serialized ``ServerMessage`` to stdout: the
``StrategySchema``, or an ``Error``. What the module prints goes to stderr.
"""

import importlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

from sbt2.core.strategy import Strategy
from sbt2.protocol.v1.envelope_pb2 import ServerMessage
from sbt2.protocol.v1.types_pb2 import Error, ErrorCode
from sbt2.server.strategies.encoding import describe


class _Invalid(Exception):
    pass


def main() -> None:
    request = json.load(sys.stdin)
    result = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    reply = _reply(request["name"], request["source"])
    result.write(reply.SerializeToString())
    result.flush()


def _reply(name: str, source: str) -> ServerMessage:
    try:
        module = _imported(name, source)
        return ServerMessage(strategy_schema=describe(_strategy(module)))
    except _Invalid as invalid:
        return _invalid(str(invalid))
    except (TypeError, NameError) as error:
        return _invalid(f"{type(error).__name__}: {error}")


def _invalid(message: str) -> ServerMessage:
    code = ErrorCode.ERROR_CODE_INVALID_ARGUMENT
    return ServerMessage(error=Error(code=code, message=message))


def _imported(name: str, source: str) -> ModuleType:
    with tempfile.TemporaryDirectory(prefix="sbt2-strategy-") as folder:
        Path(folder, f"{name}.py").write_text(source)
        sys.path.insert(0, folder)
        try:
            return importlib.import_module(name)
        except BaseException as error:
            raise _Invalid(
                f"the module {name} fails to import: {type(error).__name__}: {error}"
            ) from error


def _strategy(module: ModuleType) -> type[Strategy[Any]]:
    found = {
        f"{module.__name__}:{each.__qualname__}": each
        for each in vars(module).values()
        if isinstance(each, type)
        and issubclass(each, Strategy)
        and each.__module__ == module.__name__
        and not inspect.isabstract(each)
    }
    if not found:
        raise _Invalid(f"the module {module.__name__} defines no strategy")
    if len(found) > 1:
        raise _Invalid(
            f"the module {module.__name__} defines more than one strategy: "
            f"{', '.join(found)}"
        )
    return next(iter(found.values()))


if __name__ == "__main__":
    main()
