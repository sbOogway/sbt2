import importlib
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from google.protobuf import json_format
from lab_kit import CROSS, TOKEN, FakeServer, cross, run, serve_job, summary

from sbt2.core.strategy import Strategy
from sbt2.lab import Lab, StrategyModuleError
from sbt2.protocol.v1.envelope_pb2 import ClientMessage

SPEC = {
    "instruments": ["BTCUSDT-PERP.BYBIT"],
    "period": [date(2024, 1, 1), datetime(2024, 7, 1, 12, tzinfo=UTC)],
    "execution": {
        "fee_model": {
            "kind": "maker_taker",
            "config": {"maker_rate": "0.0002", "taker_rate": "0.00055"},
        }
    },
    "capital": "10000 USDT",
    "part": ["train", "validation"],
    "split": {"validation": 0.2, "test": 0.2},
    "params": {"fast": [5, 10], "threshold": "0.5"},
    "risk": {"drawdown_limit": 0.3},
    "chain": {"min_dte": 7, "max_dte": 45, "strike_band": "0.2"},
    "seed": 42,
    "study": "cross-sweep",
}


def submitted(
    server: FakeServer, strategy: type[Strategy[Any]], spec: dict = SPEC
) -> None:
    serve_job(server, [summary("run-1")])

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            await lab.run(spec, strategy)

    run(scenario, server)


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_run_submits_the_spec_and_the_strategy_module() -> None:
    server = FakeServer()

    submitted(server, cross())

    [request] = server.received("submit_run")
    spec = request.submit_run.spec
    assert spec.strategy == "my_strats:Cross"
    assert list(spec.instruments) == ["BTCUSDT-PERP.BYBIT"]
    assert spec.period.start_at.ToDatetime(UTC) == datetime(2024, 1, 1, tzinfo=UTC)
    assert spec.period.end_at.ToDatetime(UTC) == datetime(2024, 7, 1, 12, tzinfo=UTC)
    assert spec.capital == "10000 USDT"
    assert json_format.MessageToDict(spec.execution) == {
        "fee_model": {
            "kind": "maker_taker",
            "config": {"maker_rate": "0.0002", "taker_rate": "0.00055"},
        }
    }
    assert list(spec.part) == ["train", "validation"]
    assert json_format.MessageToDict(spec.split) == {"validation": 0.2, "test": 0.2}
    assert json_format.MessageToDict(spec.params) == {
        "fast": [5, 10],
        "threshold": "0.5",
    }
    assert json_format.MessageToDict(spec.risk) == {"drawdown_limit": 0.3}
    assert json_format.MessageToDict(spec.chain) == {
        "min_dte": 7,
        "max_dte": 45,
        "strike_band": "0.2",
    }
    assert (spec.seed, spec.study) == (42, "cross-sweep")
    assert not spec.HasField("bars")
    module = request.submit_run.strategy
    assert (module.name, module.source) == ("my_strats", CROSS)


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_the_lab_sends_a_capital_list() -> None:
    server = FakeServer()

    submitted(server, cross(), {**SPEC, "capital": ["1 BTC", "20 ETH"]})

    [request] = server.received("submit_run")
    spec = request.submit_run.spec
    assert list(spec.capitals) == ["1 BTC", "20 ETH"]
    assert spec.capital == ""


@pytest.mark.integration
def test_a_strategy_in_a_package_is_sent_under_its_module_name(
    strategies: Path,
) -> None:
    (strategies / "pkg").mkdir()
    (strategies / "pkg" / "__init__.py").write_text("")
    (strategies / "pkg" / "sub.py").write_text(CROSS)
    server = FakeServer()

    submitted(server, importlib.import_module("pkg.sub").Cross)

    [request] = server.received("submit_run")
    assert request.submit_run.spec.strategy == "sub:Cross"
    assert request.submit_run.strategy.name == "sub"


@pytest.mark.integration
def test_the_strategy_module_is_sent_without_running_it(strategies: Path) -> None:
    source = 'raise RuntimeError("never run")\n'
    (strategies / "explosive.py").write_text(source)
    server = FakeServer()

    submitted(server, strategy_in("explosive"))

    [request] = server.received("submit_run")
    assert request.submit_run.strategy.source == source


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_a_spec_with_a_strategy_key_is_refused() -> None:
    server = FakeServer()

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            with pytest.raises(ValueError, match="argument"):
                await lab.run({**SPEC, "strategy": "x:Y"}, cross())

    run(scenario, server)

    assert server.received("submit_run") == []


@pytest.mark.integration
def test_run_accepts_an_imported_strategy_class(strategies: Path) -> None:
    server = FakeServer()
    serve_job(server, [summary("run-1")])
    ids: list[str] = []

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            ids.extend(each.run_id for each in await lab.run(SPEC, cross()))

    run(scenario, server)

    [request] = server.received("submit_run")
    assert ids == ["run-1"]
    assert request.submit_run.spec.strategy == "my_strats:Cross"
    assert (
        request.submit_run.strategy.source == (strategies / "my_strats.py").read_text()
    )


@pytest.mark.integration
def test_a_strategy_class_uses_its_defining_module(strategies: Path) -> None:
    (strategies / "pkg").mkdir()
    (strategies / "pkg" / "__init__.py").write_text("")
    (strategies / "pkg" / "sub.py").write_text(CROSS)
    (strategies / "reexport.py").write_text("from pkg.sub import Cross\n")
    server = FakeServer()

    submitted(server, importlib.import_module("reexport").Cross)

    [request] = server.received("submit_run")
    assert request.submit_run.spec.strategy == "sub:Cross"
    assert request.submit_run.strategy.source == CROSS


def strategy_in(module: str) -> type[Strategy[Any]]:
    return type("Cross", (Strategy,), {"__module__": module})


def refused(strategy: type[Strategy[Any]], match: str) -> list[ClientMessage]:
    server = FakeServer()

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            with pytest.raises(StrategyModuleError, match=match):
                await lab.run(SPEC, strategy)

    run(scenario, server)
    return server.received("submit_run")


@pytest.mark.integration
def test_a_main_module_class_is_refused_before_submission() -> None:
    strategy = strategy_in("__main__")

    assert refused(strategy, r"Cross.*__main__.*importable module") == []


@pytest.mark.integration
def test_a_local_strategy_class_is_refused_before_submission() -> None:
    class Local(Strategy):
        pass

    assert refused(Local, r"Local.*local scope.*importable module") == []


@pytest.mark.integration
def test_a_nested_strategy_class_is_refused_before_submission(strategies: Path) -> None:
    (strategies / "nested.py").write_text(
        "from sbt2.core.strategy import Strategy\n\n\n"
        "class Family:\n    class Cross(Strategy):\n        pass\n"
    )
    strategy = importlib.import_module("nested").Family.Cross

    assert refused(strategy, r"Family\.Cross.*nested in another class") == []


@pytest.mark.integration
@pytest.mark.parametrize(
    "module", ["no_such_module", "<ipython-input-3-9f2c>", "sys", "specless"]
)
def test_a_class_without_importable_source_is_refused_before_submission(
    monkeypatch: pytest.MonkeyPatch, module: str
) -> None:
    monkeypatch.setitem(sys.modules, "specless", ModuleType("specless"))
    strategy = strategy_in(module)

    assert refused(strategy, re.escape(module)) == []


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_a_string_strategy_is_refused_before_submission() -> None:
    server = FakeServer()

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            with pytest.raises(TypeError, match="pass the imported class"):
                await lab.run(SPEC, "my_strats:Cross")  # type: ignore[arg-type]

    run(scenario, server)

    assert server.received("submit_run") == []
