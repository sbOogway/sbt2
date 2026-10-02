from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from results_kit import ask, stored, stored_without_fills

from sbt2.core import results as core
from sbt2.core.config import Root
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.results_pb2 import GetSeries, SeriesKind
from sbt2.server.results import routes


def series(
    path: Path, run_id: str, kind: SeriesKind.ValueType, request_id: int = 1
) -> list[ServerMessage]:
    return ask(
        routes(Root(path)),
        ClientMessage(
            request_id=request_id, get_series=GetSeries(run_id=run_id, kind=kind)
        ),
    )


def decoded(replies: list[ServerMessage]) -> pd.DataFrame:
    data = b"".join(reply.series.data for reply in replies)
    return pa.ipc.open_stream(data).read_all().to_pandas()


@pytest.mark.integration
def test_equity_stream_matches_core_curve(tmp_path: Path) -> None:
    run = stored(tmp_path)
    loaded = run.store.stored_run(run.run_id)
    curve = core.equity_curve(
        loaded.tables.equity, loaded.tables.currency, core.Segment.of_run(loaded.spec)
    )
    replies = series(tmp_path, run.run_id, SeriesKind.SERIES_KIND_EQUITY)
    frame = decoded(replies)
    assert replies[-1].series.last
    assert list(frame.columns) == ["ts_event", "currency", "total_equity"]
    assert (frame["currency"] == "USDT").all()
    assert list(frame["ts_event"]) == list(curve.index)
    np.testing.assert_array_equal(frame["total_equity"], curve.to_numpy())


@pytest.mark.integration
def test_fills_stream_preserves_stored_rows(tmp_path: Path) -> None:
    run = stored(tmp_path)
    fills = run.store.load(run.run_id, "fills")
    replies = series(tmp_path, run.run_id, SeriesKind.SERIES_KIND_FILLS)
    pd.testing.assert_frame_equal(decoded(replies), fills)


@pytest.mark.integration
def test_empty_fills_produce_a_valid_arrow_stream(tmp_path: Path) -> None:
    run = stored_without_fills(tmp_path)
    replies = series(tmp_path, run.run_id, SeriesKind.SERIES_KIND_FILLS)
    [reply] = replies
    assert reply.series.last
    frame = decoded(replies)
    assert frame.empty
    assert "instrument_id" in frame.columns


@pytest.mark.integration
def test_series_chunks_reassemble_within_the_envelope_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = stored(tmp_path)
    grid = pd.date_range("2024-01-01", periods=300_000, freq="s", tz="UTC")
    curve = pd.Series(np.random.default_rng(1).random(len(grid)), index=grid)
    monkeypatch.setattr(core, "equity_curve", lambda _equity, _currency, _seg: curve)
    replies = series(tmp_path, run.run_id, SeriesKind.SERIES_KIND_EQUITY, 2**64 - 1)
    assert len(replies) > 1
    assert all(reply.ByteSize() <= 1_048_576 for reply in replies)
    assert {reply.request_id for reply in replies} == {2**64 - 1}
    assert [reply.series.index for reply in replies] == list(range(len(replies)))
    assert [reply.series.last for reply in replies] == [False] * (len(replies) - 1) + [
        True
    ]
    np.testing.assert_array_equal(decoded(replies)["total_equity"], curve.to_numpy())
