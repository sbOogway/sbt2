from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from google.protobuf import json_format
from lab_kit import CROSS, TOKEN, FakeServer, run, serve_job, summary

from sbt2.lab import Lab, StrategyModuleError

SPEC = {
    "instruments": ["BTCUSDT-PERP.BYBIT"],
    "period": [date(2024, 1, 1), datetime(2024, 7, 1, 12, tzinfo=UTC)],
    "venue": "bybit",
    "capital": "10000 USDT",
    "part": ["train", "validation"],
    "split": {"validation": 0.2, "test": 0.2},
    "params": {"fast": [5, 10], "threshold": "0.5"},
    "risk": {"drawdown_limit": 0.3},
    "seed": 42,
    "study": "cross-sweep",
}


def submitted(server: FakeServer, strategy: str) -> None:
    serve_job(server, [summary("run-1")])

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            await lab.run(SPEC, strategy)

    run(scenario, server)


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_run_submits_the_spec_and_the_strategy_module() -> None:
    server = FakeServer()

    submitted(server, "my_strats:Cross")

    [request] = server.received("submit_run")
    spec = request.submit_run.spec
    assert spec.strategy == "my_strats:Cross"
    assert list(spec.instruments) == ["BTCUSDT-PERP.BYBIT"]
    assert spec.period.start_at.ToDatetime(UTC) == datetime(2024, 1, 1, tzinfo=UTC)
    assert spec.period.end_at.ToDatetime(UTC) == datetime(2024, 7, 1, 12, tzinfo=UTC)
    assert (spec.venue, spec.capital) == ("bybit", "10000 USDT")
    assert list(spec.part) == ["train", "validation"]
    assert json_format.MessageToDict(spec.split) == {"validation": 0.2, "test": 0.2}
    assert json_format.MessageToDict(spec.params) == {
        "fast": [5, 10],
        "threshold": "0.5",
    }
    assert json_format.MessageToDict(spec.risk) == {"drawdown_limit": 0.3}
    assert (spec.seed, spec.study) == (42, "cross-sweep")
    assert not spec.HasField("bars")
    module = request.submit_run.strategy
    assert (module.name, module.source) == ("my_strats", CROSS)


@pytest.mark.integration
def test_a_strategy_in_a_package_is_sent_under_its_module_name(
    strategies: Path,
) -> None:
    (strategies / "pkg").mkdir()
    (strategies / "pkg" / "__init__.py").write_text("")
    (strategies / "pkg" / "sub.py").write_text(CROSS)
    server = FakeServer()

    submitted(server, "pkg.sub:Cross")

    [request] = server.received("submit_run")
    assert request.submit_run.spec.strategy == "sub:Cross"
    assert request.submit_run.strategy.name == "sub"


@pytest.mark.integration
def test_the_strategy_module_is_sent_without_running_it(strategies: Path) -> None:
    source = 'raise RuntimeError("never run")\n'
    (strategies / "explosive.py").write_text(source)
    server = FakeServer()

    submitted(server, "explosive:Cross")

    [request] = server.received("submit_run")
    assert request.submit_run.strategy.source == source


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_an_unknown_strategy_module_raises_before_anything_is_sent() -> None:
    server = FakeServer()

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            with pytest.raises(StrategyModuleError, match="no_such_module"):
                await lab.run(SPEC, "no_such_module:Cross")

    run(scenario, server)

    assert server.received("submit_run") == []


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_a_spec_with_a_strategy_key_is_refused() -> None:
    server = FakeServer()

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            with pytest.raises(ValueError, match="argument"):
                await lab.run({**SPEC, "strategy": "x:Y"}, "my_strats:Cross")

    run(scenario, server)

    assert server.received("submit_run") == []
