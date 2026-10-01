from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    BarType,
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

START = datetime(2024, 1, 1, tzinfo=UTC)
DAYS = 5
WAVE_MINUTES = 20 * 60
FUNDING_INTERVAL = timedelta(hours=8)
ETH_WAVE_MINUTES = 16 * 60
ETH_SLIDE_START = 4 * 24 * 60 + 6 * 60 + 30
ETH_SLIDE_MINUTES = 4
ETH_SLIDE_CENTS_PER_MINUTE = 20_000
MINUTE_NS = 60_000_000_000
DAY_NS = 86_400_000_000_000


@dataclass(frozen=True)
class Market:
    instrument: CryptoPerpetual
    price_at: Callable[[int], Price]
    funding_rates: Sequence[Decimal]

    @property
    def instrument_id(self) -> InstrumentId:
        return self.instrument.id


def build_catalog(path: Path) -> None:
    """Two perps, BTC and ETH, over five days.

    Each has one trade, one mark price and one flat 1-minute candle a minute,
    at the same price, and funding every 8h on the epoch-aligned boundaries,
    cycling through its funding rates.
    """
    path.mkdir(parents=True, exist_ok=True)
    ParquetDataCatalog(str(path)).write_instruments(
        [market.instrument for market in MARKETS]
    )
    for market in MARKETS:
        for day in range(DAYS):
            _write_day(path, market, day)


def _btc_price_at(ts: int) -> Price:
    """Zigzags every 20h on a slow uptrend."""
    minute = _minute(ts)
    phase = minute % WAVE_MINUTES
    zigzag = min(phase, WAVE_MINUTES - phase)
    return Price.from_str(f"{49_400 + 2 * zigzag + minute // 10}.0")


def _eth_price_at(ts: int) -> Price:
    """Zigzags every 16h on a slow uptrend, then slides 200 USDT a minute for
    four minutes from 06:30 on the last day: the long ``bracket_risk`` holds
    then gaps through its stop-loss and trips the drawdown guard."""
    minute = _minute(ts)
    phase = minute % ETH_WAVE_MINUTES
    zigzag = min(phase, ETH_WAVE_MINUTES - phase)
    slide = min(max(minute - ETH_SLIDE_START, 0), ETH_SLIDE_MINUTES)
    cents = 230_000 + 12 * zigzag + minute - ETH_SLIDE_CENTS_PER_MINUTE * slide
    return Price(cents / 100, 2)


def _minute(ts: int) -> int:
    return (ts - dt_to_unix_nanos(START)) // MINUTE_NS


def _write_day(path: Path, market: Market, day: int) -> None:
    catalog = ParquetDataCatalog(str(path))
    first = dt_to_unix_nanos(START) + day * DAY_NS
    last = first + DAY_NS - 1
    minutes = range(first, last, MINUTE_NS)
    catalog.write_trade_ticks([_trade(market, ts) for ts in minutes], first, last)
    catalog.write_mark_price_updates([_mark(market, ts) for ts in minutes], first, last)
    catalog.write_bars([_candle(market, ts) for ts in minutes], first, last)
    _write_funding(path, _fundings(market, day), (first, last))


def _perpetual(symbol: str, precisions: tuple[int, int]) -> CryptoPerpetual:
    usdt = Currency.from_str("USDT")
    price_precision, size_precision = precisions
    return CryptoPerpetual(
        InstrumentId.from_str(f"{symbol}USDT-LINEAR.BYBIT"),
        Symbol(f"{symbol}USDT"),
        Currency.from_str(symbol),
        usdt,
        usdt,
        False,
        price_precision,
        size_precision,
        Price(10**-price_precision, price_precision),
        Quantity(10**-size_precision, size_precision),
        0,
        0,
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
    )


def _trade(market: Market, ts: int) -> TradeTick:
    side = AggressorSide.BUY if ts // MINUTE_NS % 2 else AggressorSide.SELL
    return TradeTick(
        market.instrument_id,
        market.price_at(ts),
        _volume(market),
        side,
        TradeId(str(ts)),
        ts,
        ts,
    )


def _candle(market: Market, minute_start: int) -> Bar:
    """The minute's trade as a candle, stamped 1 ns before its close as ingest does."""
    price = market.price_at(minute_start)
    ts = minute_start + MINUTE_NS - 1
    bar_type = BarType.from_str(f"{market.instrument_id}-1-MINUTE-LAST-EXTERNAL")
    return Bar(bar_type, price, price, price, price, _volume(market), ts, ts)


def _volume(market: Market) -> Quantity:
    return market.instrument.make_qty(10)


def _mark(market: Market, ts: int) -> MarkPriceUpdate:
    return MarkPriceUpdate(market.instrument_id, market.price_at(ts), ts, ts)


def _fundings(market: Market, day: int) -> list[FundingRateUpdate]:
    interval = int(FUNDING_INTERVAL.total_seconds()) // 60
    per_day = timedelta(days=1) // FUNDING_INTERVAL
    rates = market.funding_rates
    return [
        FundingRateUpdate(
            market.instrument_id,
            rates[(day * per_day + k) % len(rates)],
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
    directory = path / "data" / "funding_rates" / str(fundings[0].instrument_id)
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


MARKETS = (
    Market(
        _perpetual("BTC", (1, 3)),
        _btc_price_at,
        (Decimal("0.0001"), Decimal("-0.00005"), Decimal("0.0002")),
    ),
    Market(
        _perpetual("ETH", (2, 2)),
        _eth_price_at,
        (Decimal("0.00015"), Decimal("0.0001"), Decimal("-0.0001")),
    ),
)
