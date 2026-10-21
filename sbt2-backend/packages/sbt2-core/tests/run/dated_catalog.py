from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    Bar,
    CryptoFuture,
    CryptoPerpetual,
    Currency,
    CurrencyPair,
    IndexPriceUpdate,
    InstrumentId,
    Price,
    Quantity,
    Symbol,
)
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.data import candle_type

START = datetime(2024, 1, 1, tzinfo=UTC)
EXPIRY = START + timedelta(days=1, hours=8)


def future(coin: str = "BTC", expiry: datetime = EXPIRY) -> CryptoFuture:
    name = f"{coin}-{expiry.strftime('%-d%b%y').upper()}"
    currency = Currency.from_str(coin)
    return CryptoFuture(
        InstrumentId.from_str(f"{name}.DERIBIT"),
        Symbol(name),
        currency,
        Currency.from_str("USD"),
        currency,
        True,
        0,
        dt_to_unix_nanos(expiry),
        1,
        0,
        Price.from_str("0.5"),
        Quantity.from_str("10"),
        0,
        0,
        margin_init=Decimal("0.02"),
        margin_maint=Decimal("0.0133"),
    )


def perpetual(coin: str = "BTC") -> CryptoPerpetual:
    """The coin's perpetual, with the margin rates of ``future``."""
    currency = Currency.from_str(coin)
    return CryptoPerpetual(
        InstrumentId.from_str(f"{coin}-PERPETUAL.DERIBIT"),
        Symbol(f"{coin}-PERPETUAL"),
        currency,
        Currency.from_str("USD"),
        currency,
        True,
        1,
        0,
        Price.from_str("0.5"),
        Quantity.from_str("10"),
        0,
        0,
        margin_init=Decimal("0.02"),
        margin_maint=Decimal("0.0133"),
    )


def spot() -> CurrencyPair:
    return CurrencyPair(
        InstrumentId.from_str("BTC_USDC.DERIBIT"),
        Symbol("BTC_USDC"),
        Currency.from_str("BTC"),
        Currency.from_str("USDC"),
        1,
        3,
        Price.from_str("0.1"),
        Quantity.from_str("0.001"),
        0,
        0,
    )


def build_bars(
    path: Path, instrument: CryptoFuture | CryptoPerpetual | CurrencyPair
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([instrument])
    bars = []
    for minute in range(48 * 60):
        ts = dt_to_unix_nanos(START + timedelta(minutes=minute + 1)) - 1
        if isinstance(instrument, CryptoFuture) and ts >= instrument.expiration_ns:
            break
        price = Price.from_str(f"{50_000 + 100 * (minute // 60)}.0")
        bars.append(
            Bar(
                candle_type(instrument.id),
                price,
                price,
                price,
                price,
                Quantity(1_000_000_000, instrument.size_precision),
                ts,
                ts,
            )
        )
    catalog.write_bars(bars)


def write_delivery(path: Path, coin: str, prices: dict[datetime, float]) -> None:
    """The coin's delivery price at each of the times of ``prices``."""
    path.mkdir(parents=True, exist_ok=True)
    series = InstrumentId.from_str(f"{coin}_USD_DELIVERY.DERIBIT")
    updates = [
        IndexPriceUpdate(series, Price(price, 2), ts, ts)
        for ts, price in sorted(
            (dt_to_unix_nanos(moment), price) for moment, price in prices.items()
        )
    ]
    ParquetDataCatalog(str(path)).write_index_price_updates(
        updates, updates[0].ts_event, updates[-1].ts_event
    )
