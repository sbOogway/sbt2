import asyncio
import builtins
import os
import sys
from collections.abc import Awaitable
from pathlib import Path

import pytest
from runs_kit import Session
from strategies_kit import STRATEGY, with_params

from sbt2.protocol.v1.config_pb2 import ParameterType
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.runs_pb2 import DescribeStrategy, StrategyModule
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server import strategies


def in_one_loop(scenario: Awaitable[None]) -> None:
    async def bounded() -> None:
        await asyncio.wait_for(scenario, 120)

    asyncio.run(bounded())


def described(
    name: str, source: str, timeout: float = strategies.IMPORT_SECONDS
) -> ServerMessage:
    replies: list[ServerMessage] = []

    async def scenario() -> None:
        session = Session(strategies.routes(timeout))
        module = StrategyModule(name=name, source=source)
        request = ClientMessage(describe_strategy=DescribeStrategy(strategy=module))
        replies.append(await session.ask(request))

    in_one_loop(scenario())
    [reply] = replies
    return reply


def invalid_message(reply: ServerMessage) -> str:
    assert reply.WhichOneof("body") == "error", reply
    assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_ARGUMENT
    return reply.error.message


@pytest.mark.integration
def test_describe_strategy_answers_the_schema_of_its_params() -> None:
    reply = described("cross_mod", STRATEGY)

    schema = reply.strategy_schema
    assert schema.strategy == "cross_mod:Cross"
    assert (schema.description, schema.params_description) == (
        "Buys on a cross.",
        "The averages.",
    )
    slow, fast, step, mode = schema.parameters
    assert (slow.name, slow.type, slow.required) == (
        "slow",
        ParameterType.PARAMETER_TYPE_INTEGER,
        True,
    )
    assert (fast.default.number_value, fast.required) == (10, False)
    assert (step.type, step.default.string_value) == (
        ParameterType.PARAMETER_TYPE_DECIMAL,
        "0.100",
    )
    assert [each.string_value for each in mode.choices] == ["ema", "sma"]


@pytest.mark.integration
def test_the_server_process_never_imports_the_described_module() -> None:
    source = STRATEGY + "\nimport builtins\nbuiltins.DESCRIBED_WAS_IMPORTED = True\n"

    reply = described("imports_a_lot", source)

    assert reply.WhichOneof("body") == "strategy_schema"
    assert not hasattr(builtins, "DESCRIBED_WAS_IMPORTED")
    assert "imports_a_lot" not in sys.modules


@pytest.mark.integration
def test_the_describe_process_runs_without_the_server_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SBT2_SERVER_TOKEN", "s3cret")
    monkeypatch.setenv("SBT2_UNRELATED", "kept")
    fields = (
        'token: str = os.environ.get("SBT2_SERVER_TOKEN", "absent")\n'
        'other: str = os.environ.get("SBT2_UNRELATED", "absent")\n'
    )

    reply = described("sees_environment", with_params(fields))

    token, other = reply.strategy_schema.parameters
    assert (token.default.string_value, other.default.string_value) == (
        "absent",
        "kept",
    )


@pytest.mark.integration
def test_a_module_without_a_strategy_is_invalid_argument() -> None:
    reply = described("no_strategy", "VALUE = 1\n")

    assert "no strategy" in invalid_message(reply)


@pytest.mark.integration
def test_a_module_with_two_strategies_is_invalid_argument_naming_both() -> None:
    source = with_params("size: int = 1\n", "First") + (
        "\n\nclass Second(First):\n    pass\n"
    )

    message = invalid_message(described("two_strategies", source))

    assert "two_strategies:First" in message
    assert "two_strategies:Second" in message


@pytest.mark.integration
def test_an_imported_strategy_does_not_count() -> None:
    source = "from sbt2.strategies.ma_cross import MovingAverageCross\n" + STRATEGY

    reply = described("imports_strategy", source)

    assert reply.strategy_schema.strategy == "imports_strategy:Cross"


@pytest.mark.integration
def test_a_module_that_fails_to_import_is_invalid_argument_with_its_error() -> None:
    message = invalid_message(described("broken", "raise RuntimeError('boom')\n"))

    assert "RuntimeError: boom" in message
    assert "SyntaxError" in invalid_message(described("syntax", "def (:\n"))


@pytest.mark.integration
def test_an_unsupported_parameter_type_is_invalid_argument_naming_the_field() -> None:
    source = "from datetime import timedelta\n" + with_params("span: timedelta\n")

    message = invalid_message(described("odd_params", source))

    assert "span" in message
    assert "timedelta" in message


@pytest.mark.unit
def test_a_module_named_like_an_installed_module_is_invalid_argument() -> None:
    message = invalid_message(described("json", STRATEGY))

    assert "json" in message


@pytest.mark.integration
def test_a_module_that_hangs_on_import_times_out(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    source = (
        "import os, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(300)\n"
    )

    message = invalid_message(described("hangs", source, timeout=8))

    assert "too long" in message
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
