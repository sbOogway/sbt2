import json
from collections.abc import Hashable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model import (
    AggressorSide,
    CryptoPerpetual,
    FundingRateUpdate,
    MarkPriceUpdate,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)

from sbt2.sources.base import FundingOffGridError

_NANOS_PER_MINUTE = 60_000_000_000
_NANOS_PER_MILLI = 1_000_000
_AGGRESSOR_SIDES = {"Buy": AggressorSide.BUY, "Sell": AggressorSide.SELL}
_TRADE_COLUMNS: dict[Hashable, str] = {
    "timestamp": "string",
    "side": "string",
    "size": "float64",
    "price": "float64",
    "trdMatchID": "string",
}


def instrument(path: Path) -> Any:
    """The snapshot's instrument, initialised at the start of the day it was taken on."""
    spec = json.loads(path.read_text())
    return CryptoPerpetual.from_dict({**spec, "ts_init": _snapshot_day_nanos(path)})


def trades(path: Path, instrument: Any) -> Iterator[TradeTick]:
    rows = _trade_rows(path)
    columns = ("ts", "side", "size", "price", "trdMatchID")
    for ts, side, size, price, match_id in zip(
        *(rows[each].tolist() for each in columns), strict=True
    ):
        yield TradeTick(
            instrument.id,
            Price(price, instrument.price_precision),
            Quantity(size, instrument.size_precision),
            _AGGRESSOR_SIDES[side],
            TradeId(match_id),
            ts,
            ts,
        )


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


def _snapshot_day_nanos(path: Path) -> int:
    taken_on = date.fromisoformat(path.stem[-len("YYYY-MM-DD") :])
    return pd.Timestamp(taken_on, tz="UTC").value


def _trade_rows(path: Path) -> pd.DataFrame:
    """The dump's rows in time order; older dumps run newest-first."""
    rows = pd.read_csv(path, usecols=list(_TRADE_COLUMNS), dtype=_TRADE_COLUMNS)
    rows["ts"] = _epoch_nanos(rows.pop("timestamp"))
    return rows.sort_values("ts", kind="stable")


def _epoch_nanos(seconds: pd.Series) -> pd.Series:
    """Decimal epoch seconds as integer nanoseconds, exact to the last digit given."""
    parts = seconds.str.split(".", n=1, expand=True).reindex(columns=[0, 1])
    whole = parts[0].astype("int64")
    fraction = parts[1].fillna("").str.ljust(9, "0").astype("int64")
    return whole * 1_000_000_000 + fraction


def _on_grid(record: dict[str, Any], interval: int) -> FundingRateUpdate:
    if record["ts_event"] % (interval * _NANOS_PER_MINUTE):
        raise FundingOffGridError(
            f"{record['instrument_id']} funding at ts_event {record['ts_event']} "
            f"is not a multiple of its {interval}-minute interval"
        )
    return FundingRateUpdate.from_dict({**record, "interval": interval})
