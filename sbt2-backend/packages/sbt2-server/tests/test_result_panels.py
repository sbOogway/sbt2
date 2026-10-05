import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from results_kit import ask, priced, stored

from sbt2.core import results as core
from sbt2.core.config import Root
from sbt2.core.data import Catalog
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.results_pb2 import (
    BenchmarkKind,
    BenchmarkSelection,
    GetPanel,
    PanelKind,
)
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server.results import routes

FIELDS = {
    PanelKind.PANEL_KIND_RETURNS: "returns",
    PanelKind.PANEL_KIND_BENCHMARK_RETURNS: "benchmark_returns",
    PanelKind.PANEL_KIND_DRAWDOWN: "drawdown",
    PanelKind.PANEL_KIND_MONTHLY_RETURNS: "monthly_returns",
    PanelKind.PANEL_KIND_YEARLY_RETURNS: "yearly_returns",
    PanelKind.PANEL_KIND_ROLLING_SHARPE: "rolling_sharpe",
}
BUY_AND_HOLD = BenchmarkSelection(kind=BenchmarkKind.BENCHMARK_KIND_BUY_AND_HOLD)
NO_BENCHMARK = BenchmarkSelection(kind=BenchmarkKind.BENCHMARK_KIND_NONE)


def panel(
    path: Path,
    run_id: str,
    kind: PanelKind.ValueType,
    benchmark: BenchmarkSelection = BUY_AND_HOLD,
    request_id: int = 1,
) -> list[ServerMessage]:
    return ask(
        routes(Root(path)),
        ClientMessage(
            request_id=request_id,
            get_panel=GetPanel(run_id=run_id, kind=kind, benchmark=benchmark),
        ),
    )


def decoded(replies: list[ServerMessage]) -> pd.DataFrame:
    data = b"".join(reply.panel.data for reply in replies)
    return pa.ipc.open_stream(data).read_all().to_pandas()


def core_panels(run_root: Root, run_id: str) -> core.TearsheetPanels:
    store = core.store_at(run_root)
    loaded = store.stored_run(run_id)
    return core.tearsheet_panels(
        loaded.priced(Catalog(run_root.catalog)), loaded.benchmark("buy-and-hold")
    )


def assert_is_series(frame: pd.DataFrame, expected: pd.Series) -> None:
    assert list(frame.columns) == ["ts", "value"]
    assert frame["value"].dtype == np.float64
    assert list(frame["ts"]) == list(expected.index)
    np.testing.assert_array_equal(frame["value"], expected.to_numpy())


@pytest.mark.integration
@pytest.mark.parametrize("kind", list(FIELDS))
def test_each_panel_kind_streams_cores_series(
    tmp_path: Path, kind: PanelKind.ValueType
) -> None:
    run = stored(tmp_path)
    priced(run.root)
    expected = getattr(core_panels(run.root, run.run_id), FIELDS[kind])

    replies = panel(tmp_path, run.run_id, kind)

    assert replies[-1].panel.last
    assert_is_series(decoded(replies), expected)


@pytest.mark.integration
def test_benchmark_returns_follow_the_selection(tmp_path: Path) -> None:
    run = stored(tmp_path)
    priced(run.root)
    kind = PanelKind.PANEL_KIND_BENCHMARK_RETURNS
    instrument = BenchmarkSelection(
        kind=BenchmarkKind.BENCHMARK_KIND_BUY_AND_HOLD,
        instrument_id="BTCUSDT-LINEAR.BYBIT",
    )
    expected = core_panels(run.root, run.run_id).benchmark_returns

    chosen = decoded(panel(tmp_path, run.run_id, kind, instrument))
    none = decoded(panel(tmp_path, run.run_id, kind, NO_BENCHMARK))

    assert not expected.empty
    assert_is_series(chosen, expected)
    assert none.empty
    assert list(none.columns) == ["ts", "value"]


@pytest.mark.integration
def test_an_unspecified_panel_kind_is_an_invalid_argument(tmp_path: Path) -> None:
    run = stored(tmp_path)
    priced(run.root)

    [reply] = panel(tmp_path, run.run_id, PanelKind.PANEL_KIND_UNSPECIFIED)

    assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_ARGUMENT


@pytest.mark.integration
def test_an_unknown_run_is_not_found(tmp_path: Path) -> None:
    stored(tmp_path)

    [reply] = panel(tmp_path, str(uuid.uuid7()), PanelKind.PANEL_KIND_RETURNS)

    assert reply.error.code == ErrorCode.ERROR_CODE_NOT_FOUND


@pytest.mark.integration
def test_panel_chunks_reassemble_within_the_envelope_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = stored(tmp_path)
    priced(run.root)
    grid = pd.date_range("2024-01-01", periods=300_000, freq="s", tz="UTC")
    long = pd.Series(np.random.default_rng(1).random(len(grid)), index=grid)
    empty = long.iloc[:0]
    panels = core.TearsheetPanels(long, empty, empty, empty, empty, empty)
    monkeypatch.setattr(core, "tearsheet_panels", lambda _run, _benchmark=None: panels)

    replies = panel(
        tmp_path, run.run_id, PanelKind.PANEL_KIND_RETURNS, request_id=2**64 - 1
    )

    assert len(replies) > 1
    assert all(reply.ByteSize() <= 1_048_576 for reply in replies)
    assert {reply.request_id for reply in replies} == {2**64 - 1}
    assert [reply.panel.index for reply in replies] == list(range(len(replies)))
    assert [reply.panel.last for reply in replies] == [False] * (len(replies) - 1) + [
        True
    ]
    assert_is_series(decoded(replies), long)


@pytest.mark.integration
def test_benchmark_returns_without_prices_are_not_found(tmp_path: Path) -> None:
    run = stored(tmp_path)

    [reply] = panel(tmp_path, run.run_id, PanelKind.PANEL_KIND_BENCHMARK_RETURNS)

    assert reply.error.code == ErrorCode.ERROR_CODE_NOT_FOUND
