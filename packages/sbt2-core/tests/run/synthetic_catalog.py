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
DAYS = 2
PRICE = "50000.0"
FUNDING_RATE = Decimal("0.0001")
FUNDING_INTERVAL = timedelta(hours=8)
USDT = Currency.from_str("USDT")


def build_catalog(path: Path) -> None:
    """Two days of one perp: a trade and a mark price every minute, funding every 8h."""
    path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([perpetual()])
    for day in range(DAYS):
        first, last = _day_bounds(day)
        minutes = range(first, last, 60_000_000_000)
        catalog.write_trade_ticks([_trade(ts) for ts in minutes], first, last)
        catalog.write_mark_price_updates([_mark(ts) for ts in minutes], first, last)
        _write_funding(path, _fundings(day), (first, last))


def perpetual() -> CryptoPerpetual:
    return CryptoPerpetual(
        INSTRUMENT_ID,
        Symbol("BTCUSDT"),
        Currency.from_str("BTC"),
        USDT,
        USDT,
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


def _day_bounds(day: int) -> tuple[int, int]:
    first = dt_to_unix_nanos(START + timedelta(days=day))
    return first, first + 86_400_000_000_000 - 1


def _trade(ts: int) -> TradeTick:
    return TradeTick(
        INSTRUMENT_ID,
        Price.from_str(PRICE),
        Quantity.from_str("10.000"),
        AggressorSide.BUY,
        TradeId(str(ts)),
        ts,
        ts,
    )


def _mark(ts: int) -> MarkPriceUpdate:
    return MarkPriceUpdate(INSTRUMENT_ID, Price.from_str(PRICE), ts, ts)


def _fundings(day: int) -> list[FundingRateUpdate]:
    day_start = START + timedelta(days=day)
    interval = int(FUNDING_INTERVAL.total_seconds()) // 60
    return [
        FundingRateUpdate(INSTRUMENT_ID, FUNDING_RATE, ts, ts, interval=interval)
        for k in range(3)
        for ts in [dt_to_unix_nanos(day_start + k * FUNDING_INTERVAL)]
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
        "rate": [str(each.rate) for each in fundings],
        "interval": [each.interval for each in fundings],
        "next_funding_ns": [each.next_funding_ns for each in fundings],
        "ts_event": [each.ts_event for each in fundings],
        "ts_init": [each.ts_init for each in fundings],
        "identifier": [str(each.instrument_id) for each in fundings],
    }
    metadata = {
        **(schema.metadata or {}),
        "instrument_id": str(fundings[0].instrument_id),
    }
    return pa.table(columns, schema=schema.with_metadata(metadata))
