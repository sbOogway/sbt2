from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest
from results_kit import ask, stored

from sbt2.core import results as core
from sbt2.core.config import Root
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.results_pb2 import GetSeries, SeriesKind
from sbt2.server.results import routes


def series(path: Path, run_id: str, kind: SeriesKind.ValueType) -> list[ServerMessage]:
    return ask(
        routes(Root(path)),
        ClientMessage(request_id=1, get_series=GetSeries(run_id=run_id, kind=kind)),
    )


def decoded(replies: list[ServerMessage]) -> pd.DataFrame:
    data = b"".join(reply.series.data for reply in replies)
    return pa.ipc.open_stream(data).read_all().to_pandas()


@pytest.mark.integration
def test_trades_stream_preserves_the_stored_rows(tmp_path: Path) -> None:
    run = stored(tmp_path)
    trades = run.store.load(run.run_id, "trades")

    replies = series(tmp_path, run.run_id, SeriesKind.SERIES_KIND_TRADES)

    assert replies[-1].series.last
    pd.testing.assert_frame_equal(decoded(replies), trades)


@pytest.mark.integration
def test_trade_statistics_stream_matches_core(tmp_path: Path) -> None:
    run = stored(tmp_path)
    tables = run.store.stored_run(run.run_id).tables
    expected = core.trade_statistics(tables.trades, tables.margin, tables.currency)

    frame = decoded(
        series(tmp_path, run.run_id, SeriesKind.SERIES_KIND_TRADE_STATISTICS)
    )

    assert list(frame.columns) == ["name", "value"]
    assert dict(zip(frame["name"], frame["value"], strict=True)) == pytest.approx(
        {
            name: float("nan") if value is None else value
            for name, value in expected.items()
        },
        nan_ok=True,
    )


@pytest.mark.integration
def test_the_server_serves_the_portfolio_greeks_of_a_run(tmp_path: Path) -> None:
    run = stored(tmp_path)
    times = pd.to_datetime(["2024-01-01 03:00", "2024-01-01 04:00"], utc=True)
    greeks = pd.DataFrame(
        {
            "ts_event": times,
            "theta": [0.0, 0.002],
            "theta_ratio": [0.0, 0.0021],
            "beta_weighted_delta": [0.0, -0.04],
        }
    )
    greeks.to_parquet(run.store.folder(run.run_id) / "portfolio_greeks.parquet")

    replies = series(tmp_path, run.run_id, SeriesKind.SERIES_KIND_PORTFOLIO_GREEKS)

    assert replies[-1].series.last
    pd.testing.assert_frame_equal(decoded(replies), greeks)
