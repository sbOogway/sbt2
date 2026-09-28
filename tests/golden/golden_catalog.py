from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    AggressorSide,
    CryptoPerpetual,
    Currency,
    FundingRateUpdate,
    InstrumentId,
    MarkPriceUpdate,
    Price,
    Quantity,
    Symbol,
    TradeId,
    TradeTick,
)
from nautilus_trader.persistence import ParquetDataCatalog
from nautilus_trader.serialization import get_arrow_schema_bytes

INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT")
START = datetime(2024, 1, 1, tzinfo=UTC)
DAYS = 5
WAVE_MINUTES = 20 * 60
FUNDING_RATES = (Decimal("0.0001"), Decimal("-0.00005"), Decimal("0.0002"))
FUNDING_INTERVAL = timedelta(hours=8)
MINUTE_NS = 60_000_000_000
DAY_NS = 86_400_000_000_000


def build_catalog(path: Path) -> None:
    """A perp whose price zigzags every 20h on a slow uptrend.

    One trade and one mark price a minute, at the same price; funding every 8h
    on the epoch-aligned boundaries, cycling through ``FUNDING_RATES``.
    """
    path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([_perpetual()])
    for day in range(DAYS):
        first = dt_to_unix_nanos(START) + day * DAY_NS
        last = first + DAY_NS - 1
        minutes = range(first, last, MINUTE_NS)
        catalog.write_trade_ticks([_trade(ts) for ts in minutes], first, last)
        catalog.write_mark_price_updates([_mark(ts) for ts in minutes], first, last)
        _write_funding(path, _fundings(day), (first, last))


def price_at(ts: int) -> Price:
    minute = (ts - dt_to_unix_nanos(START)) // MINUTE_NS
    phase = minute % WAVE_MINUTES
    zigzag = min(phase, WAVE_MINUTES - phase)
    return Price.from_str(f"{49_400 + 2 * zigzag + minute // 10}.0")


def _perpetual() -> CryptoPerpetual:
    usdt = Currency.from_str("USDT")
    return CryptoPerpetual(
        INSTRUMENT_ID,
        Symbol("BTCUSDT"),
        Currency.from_str("BTC"),
        usdt,
        usdt,
        False,
        1,
        3,
        Price.from_str("0.1"),
        Quantity.from_str("0.001"),
        0,
        0,
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
    )


def _trade(ts: int) -> TradeTick:
    side = AggressorSide.BUY if ts // MINUTE_NS % 2 else AggressorSide.SELL
    return TradeTick(
        INSTRUMENT_ID,
        price_at(ts),
        Quantity.from_str("10.000"),
        side,
        TradeId(str(ts)),
        ts,
        ts,
    )


def _mark(ts: int) -> MarkPriceUpdate:
    return MarkPriceUpdate(INSTRUMENT_ID, price_at(ts), ts, ts)


def _fundings(day: int) -> list[FundingRateUpdate]:
    interval = int(FUNDING_INTERVAL.total_seconds()) // 60
    per_day = timedelta(days=1) // FUNDING_INTERVAL
    return [
        FundingRateUpdate(
            INSTRUMENT_ID,
            FUNDING_RATES[(day * per_day + k) % len(FUNDING_RATES)],
            ts,
            ts,
            interval=interval,
        )
        for k in range(per_day)
        for ts in [
            dt_to_unix_nanos(START + day * timedelta(days=1) + k * FUNDING_INTERVAL)
        ]
    ]


def _write_funding(
    path: Path, fundings: Sequence[FundingRateUpdate], bounds: tuple[int, int]
) -> None:
    """Nautilus's catalog has no Python writer for funding rates."""
    directory = path / "data" / "funding_rates" / str(INSTRUMENT_ID)
    directory.mkdir(parents=True, exist_ok=True)
    name = "_".join(_file_timestamp(ts) for ts in bounds) + ".parquet"
    pq.write_table(_funding_table(fundings), directory / name)


def _file_timestamp(ts: int) -> str:
    seconds, nanos = divmod(ts, 1_000_000_000)
    return f"{datetime.fromtimestamp(seconds, UTC):%Y-%m-%dT%H-%M-%S}-{nanos:09d}Z"


def _funding_table(fundings: Sequence[FundingRateUpdate]) -> pa.Table:
    schema = pa.ipc.read_schema(pa.py_buffer(get_arrow_schema_bytes(FundingRateUpdate)))
    columns = {
        "instrument_id": [str(each.instrument_id) for each in fundings],
        "rate": [str(each.rate) for each in fundings],
        "interval": [each.interval for each in fundings],
        "next_funding_ns": [each.next_funding_ns for each in fundings],
        "ts_event": [each.ts_event for each in fundings],
        "ts_init": [each.ts_init for each in fundings],
        "identifier": [str(each.instrument_id) for each in fundings],
    }
    return pa.table(columns, schema=schema)
