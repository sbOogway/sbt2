import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    CryptoPerpetual,
    FundingRateUpdate,
    MarkPriceUpdate,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)
from pyarrow import csv

from sbt2.data.sources.base import FundingOffGridError

_NANOS_PER_MINUTE = 60_000_000_000
_NANOS_PER_MILLI = 1_000_000
_AGGRESSOR_SIDES = {"Buy": AggressorSide.BUY, "Sell": AggressorSide.SELL}
# Decimal epoch seconds, so nanoseconds stay exact to the last digit given.
_TRADE_COLUMNS = {
    "timestamp": pa.decimal128(20, 9),
    "side": pa.string(),
    "size": pa.float64(),
    "price": pa.float64(),
    "trdMatchID": pa.string(),
}
_TRADE_FIELDS = ("ts", "side", "size", "price", "trdMatchID")
_NANOS_PER_SECOND = pa.scalar(1_000_000_000, pa.decimal128(10, 0))
_BATCH_ROWS = 100_000


def instrument(path: Path) -> Any:
    """The snapshot's instrument, initialised at the start of the day it was taken on."""
    spec = json.loads(path.read_text())
    return CryptoPerpetual.from_dict({**spec, "ts_init": _snapshot_day_nanos(path)})


def trades(path: Path, instrument: Any) -> Iterator[TradeTick]:
    for batch in _trade_rows(path).to_batches(_BATCH_ROWS):
        yield from _ticks(batch, instrument)


def funding(path: Path, instrument: Any) -> Iterator[FundingRateUpdate]:
    """The day's funding records, each with an interval on nautilus's settlement grid."""
    records = sorted(json.loads(path.read_text()), key=lambda each: each["ts_event"])
    default_interval = instrument.info["fundingInterval"]
    for record in records:
        yield _on_grid(record, record.get("interval") or default_interval)


def mark_prices(path: Path, instrument: Any) -> Iterator[MarkPriceUpdate]:
    """Each 1-minute kline's close, 1 ns before the end of its minute.

    The last close then stays inside the day's catalog file bounds, which end
    1 ns before midnight, so each day's file comes from that day's raw file
    alone. Mark prices fall between ticks, so they keep the price precision rather
    than being rounded to the tick as ``make_price`` does.
    """
    klines = sorted(
        (int(kline[0]), kline[4])
        for page in json.loads(path.read_text())
        for kline in page["result"]["list"]
    )
    for start_ms, close in klines:
        ts = start_ms * _NANOS_PER_MILLI + _NANOS_PER_MINUTE - 1
        price = Price(float(close), instrument.price_precision)
        yield MarkPriceUpdate(instrument.id, price, ts, ts)


def candles(path: Path, instrument: Any) -> Iterator[Bar]:
    """Each candle 1 ns before its close, as mark prices are, so a day's last
    candle stays inside the day's catalog file bounds."""
    for record in sorted(
        json.loads(path.read_text()), key=lambda each: each["ts_event"]
    ):
        ts = record["ts_event"] - 1
        yield Bar.from_dict({**record, "ts_event": ts, "ts_init": ts})


def _snapshot_day_nanos(path: Path) -> int:
    taken_on = date.fromisoformat(path.stem[-len("YYYY-MM-DD") :])
    return pd.Timestamp(taken_on, tz="UTC").value


def _ticks(batch: pa.RecordBatch, instrument: Any) -> Iterator[TradeTick]:
    columns = (batch[each].to_pylist() for each in _TRADE_FIELDS)
    for ts, side, size, price, match_id in zip(*columns, strict=True):
        yield TradeTick(
            instrument.id,
            Price(price, instrument.price_precision),
            Quantity(size, instrument.size_precision),
            _AGGRESSOR_SIDES[side],
            TradeId(match_id),
            ts,
            ts,
        )


def _trade_rows(path: Path) -> pa.Table:
    """The dump's rows in time order; older dumps run newest-first."""
    table = csv.read_csv(
        path,
        convert_options=csv.ConvertOptions(
            include_columns=list(_TRADE_COLUMNS), column_types=_TRADE_COLUMNS
        ),
    )
    nanos = pc.call_function("multiply", [table["timestamp"], _NANOS_PER_SECOND])
    rows = table.drop_columns("timestamp").append_column("ts", nanos.cast(pa.int64()))
    return rows.sort_by("ts")


def _on_grid(record: dict[str, Any], interval: int) -> FundingRateUpdate:
    if record["ts_event"] % (interval * _NANOS_PER_MINUTE):
        raise FundingOffGridError(
            f"{record['instrument_id']} funding at ts_event {record['ts_event']} "
            f"is not a multiple of its {interval}-minute interval"
        )
    return FundingRateUpdate.from_dict({**record, "interval": interval})
