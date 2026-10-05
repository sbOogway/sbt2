import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import create_autospec

import pytest
from plotted import Plotted, plotted
from results_kit import ask, ask_together, priced, stored

from sbt2.core import results as core
from sbt2.core.config import Root
from sbt2.data import Catalog
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.results_pb2 import (
    BenchmarkKind,
    BenchmarkSelection,
    GetTearsheet,
)
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server.results import routes

ETH = "ETHUSDT-LINEAR.BYBIT"
BENCHMARKED = """
from sbt2.core.results import BuyAndHold
from sbt2.core.strategy import Strategy


class Benchmarked(Strategy):
    benchmark = BuyAndHold()
"""


def request(
    run_id: str,
    kind: BenchmarkKind.ValueType = BenchmarkKind.BENCHMARK_KIND_NONE,
    instrument: str | None = None,
) -> ClientMessage:
    selection = BenchmarkSelection(kind=kind, instrument_id=instrument)
    return ClientMessage(
        request_id=1, get_tearsheet=GetTearsheet(run_id=run_id, benchmark=selection)
    )


def html(replies: list[ServerMessage]) -> str:
    assert replies[-1].tearsheet.last
    return b"".join(reply.tearsheet.data for reply in replies).decode()


def counted_renders(
    monkeypatch: pytest.MonkeyPatch, render: Callable[..., None] = core.tearsheet
) -> list[Any]:
    """The benchmarks core renders with, from now on, in rendering order."""
    benchmarks: list[Any] = []

    def counted(run: Any, path: Path, benchmark: Any = None) -> None:
        benchmarks.append(benchmark)
        render(run, path, benchmark)

    monkeypatch.setattr(core, "tearsheet", counted)
    return benchmarks


def mocked_store(monkeypatch: pytest.MonkeyPatch, folder: Path) -> Any:
    """A store whose one run is in ``folder`` and builds benchmarks as the
    ``(name, argument)`` it is asked for."""
    folder.mkdir()
    run = create_autospec(core.StoredRun, instance=True)
    run.benchmark.side_effect = lambda name=None, argument=None: (name, argument)
    store = create_autospec(core.ResultStore, instance=True)
    store.stored_run.return_value = run
    store.folder.return_value = folder
    monkeypatch.setattr(core, "store_at", lambda _root: store)
    return store


def written(text: str) -> Callable[..., None]:
    def render(_run: Any, path: Path, _benchmark: Any = None) -> None:
        path.write_text(text)

    return render


def outline(figure: Plotted) -> list[Any]:
    return [(each.get("type"), each.get("name")) for each in figure.traces]


def tables(figure: Plotted) -> list[dict[str, list[str]]]:
    """Each table's columns by their first cell; core orders statistics freely."""
    return [
        {
            str(row[0]): list(map(str, row))
            for row in zip(*each["cells"]["values"], strict=True)
        }
        for each in figure.of_type("table")
    ]


@pytest.mark.integration
def test_tearsheet_matches_core_rendering(tmp_path: Path) -> None:
    run = stored(tmp_path)
    priced(run.root)
    loaded = run.store.stored_run(run.run_id)
    target = tmp_path / "core.html"
    core.tearsheet(
        loaded.priced(Catalog(run.root.catalog)),
        target,
        loaded.benchmark("buy-and-hold"),
    )
    replies = ask(
        routes(run.root),
        request(run.run_id, BenchmarkKind.BENCHMARK_KIND_BUY_AND_HOLD),
    )
    assert len(replies) > 1
    assert all(reply.ByteSize() <= 1_048_576 for reply in replies)
    assert [reply.tearsheet.index for reply in replies] == list(range(len(replies)))
    handled, rendered = plotted(html(replies)), plotted(target.read_text())
    assert handled.named("BuyAndHold")
    assert outline(handled) == outline(rendered)
    assert handled.titles == rendered.titles
    assert tables(handled) == tables(rendered)


@pytest.mark.unit
def test_tearsheet_benchmark_choices_reach_core(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mocked_store(monkeypatch, tmp_path / "run")
    rendered = counted_renders(monkeypatch, written("<html></html>"))
    handlers = routes(Root(tmp_path))
    unspecified = ClientMessage(request_id=1, get_tearsheet=GetTearsheet(run_id="r"))
    selections = [
        unspecified,
        request("r", BenchmarkKind.BENCHMARK_KIND_DEFAULT),
        request("r", BenchmarkKind.BENCHMARK_KIND_NONE),
        request("r", BenchmarkKind.BENCHMARK_KIND_BUY_AND_HOLD),
        request("r", BenchmarkKind.BENCHMARK_KIND_BUY_AND_HOLD, ETH),
        request("r", BenchmarkKind.BENCHMARK_KIND_EQUAL_WEIGHT),
    ]
    for selection in selections:
        assert html(ask(handlers, selection)) == "<html></html>"
    assert rendered == [
        (None, None),
        ("none", None),
        ("buy-and-hold", None),
        ("buy-and-hold", ETH),
        ("equal-weight", None),
    ]


@pytest.mark.integration
def test_tearsheets_cache_each_variant_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = stored(tmp_path)
    priced(run.root)
    rendered = counted_renders(monkeypatch)
    handlers = routes(run.root)
    kinds = [
        BenchmarkKind.BENCHMARK_KIND_NONE,
        BenchmarkKind.BENCHMARK_KIND_NONE,
        BenchmarkKind.BENCHMARK_KIND_BUY_AND_HOLD,
        BenchmarkKind.BENCHMARK_KIND_NONE,
    ]
    sheets = [html(ask(handlers, request(run.run_id, kind))) for kind in kinds]
    assert len(rendered) == 2
    assert sheets[0] == sheets[1] == sheets[3]
    assert not plotted(sheets[0]).named("BuyAndHold")
    assert plotted(sheets[2]).named("BuyAndHold")


@pytest.mark.integration
def test_concurrent_tearsheets_publish_one_complete_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = stored(tmp_path)
    priced(run.root)

    render = core.tearsheet

    def slow(run: Any, path: Path, benchmark: Any = None) -> None:
        time.sleep(0.3)
        render(run, path, benchmark)

    rendered = counted_renders(monkeypatch, slow)
    replies = ask_together(routes(run.root), [request(run.run_id)] * 2)
    first, second = (html(each) for each in replies)
    assert len(rendered) == 1
    assert first == second
    assert first.rstrip().endswith("</html>")


@pytest.mark.unit
def test_failed_rendering_leaves_no_valid_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "run"
    mocked_store(monkeypatch, folder)

    def failing(_run: Any, path: Path, _benchmark: Any = None) -> None:
        path.write_text("<html>partial")
        raise RuntimeError("rendering failed")

    monkeypatch.setattr(core, "tearsheet", failing)
    handlers = routes(Root(tmp_path))
    [reply] = ask(handlers, request("r"))
    assert reply.HasField("error")
    assert not [each for each in folder.rglob("*") if each.is_file()]
    monkeypatch.setattr(core, "tearsheet", written("<html>ok</html>"))
    assert html(ask(handlers, request("r"))) == "<html>ok</html>"


@pytest.mark.integration
def test_missing_default_benchmark_dependencies_return_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "server_benchmarked.py").write_text(BENCHMARKED)
    monkeypatch.syspath_prepend(tmp_path)
    unpriced = stored(tmp_path / "unpriced", "server_benchmarked:Benchmarked")
    unpriced.root.catalog.mkdir()
    gone = stored(tmp_path / "gone", "gone_module:Gone")
    rendered = counted_renders(monkeypatch)
    default = BenchmarkKind.BENCHMARK_KIND_DEFAULT
    [missing_prices] = ask(routes(unpriced.root), request(unpriced.run_id, default))
    [missing_strategy] = ask(routes(gone.root), request(gone.run_id, default))
    assert missing_prices.error.code == ErrorCode.ERROR_CODE_NOT_FOUND
    assert missing_strategy.HasField("error")
    assert rendered == [core.BuyAndHold()]
