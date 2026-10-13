from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    AggressorSide,
    CryptoOption,
    Currency,
    IndexInstrument,
    IndexPriceUpdate,
    InstrumentId,
    MarkPriceUpdate,
    OptionGreeks,
    OptionKind,
    Price,
    Quantity,
    Symbol,
    TradeId,
    TradeTick,
)
from nautilus_trader.persistence import ParquetDataCatalog

OPTION_ID = InstrumentId.from_str("BTC-1FEB24-50000-C.DERIBIT")
START = datetime(2024, 1, 1, tzinfo=UTC)
HOURS = 48
TRADE_PRICE = "0.0500"
INDEX_ID = InstrumentId.from_str("BTC_USD.DERIBIT")
INDEX_PRICE = 45000.0
MARK_IV = 0.6
FIRST_MARK = Decimal("0.0500")
MARK_STEP = Decimal("0.0010")
BTC = Currency.from_str("BTC")
EXPIRING_CALL = InstrumentId.from_str("BTC-2JAN24-50000-C.DERIBIT")
EXPIRING_PUT = InstrumentId.from_str("BTC-2JAN24-50000-P.DERIBIT")
DELIVERY_ID = InstrumentId.from_str("BTC_USD_DELIVERY.DERIBIT")
DVOL_ID = InstrumentId.from_str("BTC_DVOL.DERIBIT")
EXPIRY_HOUR = 32
EXPIRY = START + timedelta(hours=EXPIRY_HOUR)


def mark_at(hour: int, step: Decimal = MARK_STEP) -> Decimal:
    return FIRST_MARK + step * hour


def build_option_catalog(path: Path, trade_price: str = TRADE_PRICE) -> None:
    """Two days of one BTC option: a trade every minute at a flat price, and every
    hour a mark price rising by ``MARK_STEP``, its IV record and the BTC index."""
    path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([option()])
    first = _nanos(0)
    last = _nanos(HOURS) - 1
    minutes = range(first, last, 60_000_000_000)
    catalog.write_trade_ticks([_trade(ts, trade_price) for ts in minutes], first, last)
    marks = [_mark(hour) for hour in range(HOURS)]
    catalog.write_mark_price_updates(marks, first, last)
    catalog.write_option_greeks([_greeks(hour) for hour in range(HOURS)], first, last)
    catalog.write_index_price_updates(
        [_index(hour) for hour in range(HOURS)], first, last
    )


@dataclass(frozen=True)
class Terms:
    kind: OptionKind
    expiry: datetime
    strike: str
    coin: Currency = BTC


def option(
    instrument_id: InstrumentId = OPTION_ID,
    kind: OptionKind = OptionKind.CALL,
    expiry: datetime = datetime(2024, 2, 1, tzinfo=UTC),
) -> CryptoOption:
    return listed_option(instrument_id, Terms(kind, expiry, "50000"))


def listed_option(instrument_id: InstrumentId, terms: Terms) -> CryptoOption:
    return CryptoOption(
        instrument_id,
        Symbol(instrument_id.symbol.value),
        terms.coin,
        terms.coin,
        terms.coin,
        True,
        terms.kind,
        Price.from_str(terms.strike),
        _nanos(0),
        dt_to_unix_nanos(terms.expiry),
        4,
        1,
        Price.from_str("0.0001"),
        Quantity.from_str("0.1"),
        0,
        0,
        multiplier=Quantity.from_str("1"),
        margin_init=Decimal(0),
        margin_maint=Decimal(0),
    )


def _nanos(hour: int) -> int:
    return dt_to_unix_nanos(START + timedelta(hours=hour))


def _trade(ts: int, price: str) -> TradeTick:
    return TradeTick(
        OPTION_ID,
        Price.from_str(price),
        Quantity.from_str("10.0"),
        AggressorSide.BUY,
        TradeId(str(ts)),
        ts,
        ts,
    )


def _mark(
    hour: int, instrument_id: InstrumentId = OPTION_ID, step: Decimal = MARK_STEP
) -> MarkPriceUpdate:
    ts = _nanos(hour)
    return MarkPriceUpdate(instrument_id, Price(float(mark_at(hour, step)), 4), ts, ts)


def _greeks(
    hour: int, instrument_id: InstrumentId = OPTION_ID, price: float = INDEX_PRICE
) -> OptionGreeks:
    ts = _nanos(hour)
    return OptionGreeks(
        instrument_id,
        0.3,
        0.0001,
        10.0,
        -50.0,
        mark_iv=MARK_IV,
        underlying_price=price,
        ts_event=ts,
        ts_init=ts,
    )


def _index(
    hour: int, price: float = INDEX_PRICE, series: InstrumentId = INDEX_ID
) -> IndexPriceUpdate:
    ts = _nanos(hour)
    return IndexPriceUpdate(series, Price(price, 2), ts, ts)


def build_expiring_catalog(path: Path, delivery: float | None) -> None:
    """Two days of an expiring call and put: marks and IV records every hour until
    the expiry, the BTC index every hour, and the delivery price of the expiry day
    unless ``delivery`` is ``None``."""
    path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(path))
    contracts = [
        option(EXPIRING_CALL, OptionKind.CALL, EXPIRY),
        option(EXPIRING_PUT, OptionKind.PUT, EXPIRY),
    ]
    catalog.write_instruments(contracts)
    first, last = _nanos(0), _nanos(HOURS) - 1
    for each in contracts:
        marks = [_mark(hour, each.id) for hour in range(EXPIRY_HOUR)]
        catalog.write_mark_price_updates(marks, first, last)
        greeks = [_greeks(hour, each.id) for hour in range(EXPIRY_HOUR)]
        catalog.write_option_greeks(greeks, first, last)
    indexes = [_index(hour) for hour in range(HOURS)]
    catalog.write_index_price_updates(indexes, first, last)
    if delivery is not None:
        expiry = _nanos(EXPIRY_HOUR)
        update = IndexPriceUpdate(DELIVERY_ID, Price(delivery, 2), expiry, expiry)
        catalog.write_index_price_updates([update], expiry, expiry)


CHAIN_ID = InstrumentId.from_str("BTC-OPTIONS.DERIBIT")
CHAIN_DELIVERY = 40_000.0
# label: (expiry, strikes); each strike has a call and a put
CHAIN_LISTING = {
    "31DEC23": (datetime(2023, 12, 31, 8, tzinfo=UTC), (45000,)),
    "2JAN24": (datetime(2024, 1, 2, 8, tzinfo=UTC), (40000, 45000, 50000)),
    "12JAN24": (datetime(2024, 1, 12, 8, tzinfo=UTC), (45000, 90000)),
    "15FEB24": (datetime(2024, 2, 15, 8, tzinfo=UTC), (45000,)),
    "28JUN24": (datetime(2024, 6, 28, 8, tzinfo=UTC), (45000,)),
}


LADDER_LISTING = {
    "12JAN24": (datetime(2024, 1, 12, 8, tzinfo=UTC), (40000, 45000, 50000)),
    "15FEB24": (
        datetime(2024, 2, 15, 8, tzinfo=UTC),
        (30000, 35000, 40000, 45000, 50000, 55000, 60000),
    ),
}


DENSE_LISTING = {
    "12JAN24": LADDER_LISTING["12JAN24"],
    "15FEB24": (datetime(2024, 2, 15, 8, tzinfo=UTC), tuple(range(20000, 70001, 2500))),
}


STAGGERED_LISTING = {
    label: (datetime(2024, 1, day, 8, tzinfo=UTC), tuple(range(35000, 55001, 500)))
    for day, label in ((3, "3JAN24"), (4, "4JAN24"), (5, "5JAN24"), (6, "6JAN24"))
}


def chain_contract_id(label: str, strike: int, kind: str) -> InstrumentId:
    return contract_id_of("BTC", f"{label}-{strike}-{kind}")


def contract_id_of(code: str, terms: str) -> InstrumentId:
    return InstrumentId.from_str(f"{code}-{terms}.DERIBIT")


def build_chain_catalog(
    path: Path,
    index_prices: Sequence[float] | None = None,
    delivery: float | None = CHAIN_DELIVERY,
) -> None:
    """Two days of the ``CHAIN_LISTING`` contracts, calls and puts: marks and IV
    records every hour while they live, an hourly BTC index of ``index_prices``
    (``INDEX_PRICE`` by default), and the delivery price of 2 January unless
    ``delivery`` is ``None``."""
    catalog = _new_catalog(path)
    _write_contracts(catalog, _chain_contracts(CHAIN_LISTING))
    _write_index(catalog, index_prices or [INDEX_PRICE] * HOURS, delivery)


def build_ladder_catalog(path: Path, mark_step: Decimal = MARK_STEP) -> None:
    """Two days of the ``LADDER_LISTING`` contracts, calls and puts, like
    ``build_chain_catalog`` with a flat index and the default delivery; the marks
    move by ``mark_step`` an hour."""
    catalog = _new_catalog(path)
    _write_contracts(catalog, _chain_contracts(LADDER_LISTING), mark_step)
    _write_index(catalog, [INDEX_PRICE] * HOURS, CHAIN_DELIVERY)


def build_dense_ladder_catalog(path: Path, mark_step: Decimal = MARK_STEP) -> None:
    """Like ``build_ladder_catalog`` with a strike every 2500 for 15 February, so
    the wings of a condor are not the short legs."""
    catalog = _new_catalog(path)
    _write_contracts(catalog, _chain_contracts(DENSE_LISTING), mark_step)
    _write_index(catalog, [INDEX_PRICE] * HOURS, CHAIN_DELIVERY)


def build_staggered_catalog(path: Path) -> None:
    """Like ``build_dense_ladder_catalog`` for four daily expiries, 3 to 6 January,
    each with a strike every 500."""
    catalog = _new_catalog(path)
    _write_contracts(catalog, _chain_contracts(STAGGERED_LISTING))
    _write_index(catalog, [INDEX_PRICE] * HOURS, CHAIN_DELIVERY)


def _new_catalog(path: Path) -> ParquetDataCatalog:
    path.mkdir(parents=True, exist_ok=True)
    return ParquetDataCatalog(str(path))


def _write_contracts(
    catalog: ParquetDataCatalog,
    contracts: list[CryptoOption],
    mark_step: Decimal = MARK_STEP,
) -> None:
    catalog.write_instruments(
        [*contracts, _index_instrument(INDEX_ID), _index_instrument(DVOL_ID)]
    )
    first, last = _nanos(0), _nanos(HOURS) - 1
    for each in contracts:
        alive = min(HOURS, max(0, _hours_until(each)))
        if alive:
            catalog.write_mark_price_updates(
                [_mark(hour, each.id, mark_step) for hour in range(alive)],
                first,
                last,
            )
            catalog.write_option_greeks(
                [_greeks(hour, each.id) for hour in range(alive)], first, last
            )


def _write_index(
    catalog: ParquetDataCatalog, prices: Sequence[float], delivery: float | None
) -> None:
    first, last = _nanos(0), _nanos(HOURS) - 1
    catalog.write_index_price_updates(
        [_index(hour, price) for hour, price in enumerate(prices)], first, last
    )
    if delivery is not None:
        expiry = _nanos(EXPIRY_HOUR)
        update = IndexPriceUpdate(DELIVERY_ID, Price(delivery, 2), expiry, expiry)
        catalog.write_index_price_updates([update], expiry, expiry)


def _index_instrument(instrument_id: InstrumentId) -> IndexInstrument:
    return IndexInstrument(
        instrument_id,
        instrument_id.symbol,
        Currency.from_str("USD"),
        2,
        0,
        Price(0.01, 2),
        Quantity.from_int(1),
        0,
        0,
    )


def write_index_history(
    path: Path, prices: Mapping[int, float], series: InstrumentId
) -> None:
    """Add index prices of ``series`` to the catalog at ``path``; ``prices`` maps an
    hour, counted from the start and negative before it, to its price."""
    write_dvol(path, prices, series)


def write_dvol(
    path: Path, dvol: Mapping[int, float], series: InstrumentId = DVOL_ID
) -> None:
    """Add the DVOL values to the catalog at ``path``; ``dvol`` maps an hour,
    counted from the start and negative before it, to its value. ``series`` is
    the volatility index, the BTC one by default."""
    updates = [
        IndexPriceUpdate(series, Price(value, 2), _nanos(hour), _nanos(hour))
        for hour, value in sorted(dvol.items())
    ]
    ParquetDataCatalog(str(path)).write_index_price_updates(
        updates, updates[0].ts_event, updates[-1].ts_event
    )


def _chain_contracts(
    listing: Mapping[str, tuple[datetime, tuple[int, ...]]],
    coin: Currency = BTC,
) -> list[CryptoOption]:
    return [
        listed_option(
            contract_id_of(coin.code, f"{label}-{strike}-{suffix}"),
            Terms(kind, expiry, str(strike), coin),
        )
        for label, (expiry, strikes) in listing.items()
        for strike in strikes
        for suffix, kind in (("C", OptionKind.CALL), ("P", OptionKind.PUT))
    ]


def _hours_until(contract: CryptoOption) -> int:
    return (contract.expiration_ns - _nanos(0)) // 3_600_000_000_000


ETH = Currency.from_str("ETH")
ETH_PRICE = 2500.0
ETH_INDEX_ID = InstrumentId.from_str("ETH_USD.DERIBIT")
ETH_DVOL_ID = InstrumentId.from_str("ETH_DVOL.DERIBIT")
ETH_CHAIN_ID = InstrumentId.from_str("ETH-OPTIONS.DERIBIT")
ETH_LISTING = {"12JAN24": (datetime(2024, 1, 12, 8, tzinfo=UTC), (2000, 2500, 3000))}


def eth_contract_id(label: str, strike: int, kind: str) -> InstrumentId:
    return contract_id_of("ETH", f"{label}-{strike}-{kind}")


def build_two_chain_catalog(
    path: Path,
    eth_prices: Sequence[float] | None = None,
    btc_prices: Sequence[float] | None = None,
) -> None:
    """Two days of the BTC contracts of ``build_ladder_catalog`` and of the ETH
    contracts of ``ETH_LISTING``, calls and puts with marks and IV records every
    hour, and an hourly index for each underlying: ``eth_prices`` (``ETH_PRICE``
    by default) and ``btc_prices`` (``INDEX_PRICE`` by default)."""
    catalog = _new_catalog(path)
    _write_contracts(catalog, _chain_contracts(LADDER_LISTING))
    _write_index(catalog, btc_prices or [INDEX_PRICE] * HOURS, None)
    contracts = _chain_contracts(ETH_LISTING, ETH)
    catalog.write_instruments(
        [*contracts, _index_instrument(ETH_INDEX_ID), _index_instrument(ETH_DVOL_ID)]
    )
    first, last = _nanos(0), _nanos(HOURS) - 1
    for each in contracts:
        catalog.write_mark_price_updates(
            [_mark(hour, each.id) for hour in range(HOURS)], first, last
        )
        catalog.write_option_greeks(
            [_greeks(hour, each.id, ETH_PRICE) for hour in range(HOURS)], first, last
        )
    prices = eth_prices or [ETH_PRICE] * HOURS
    catalog.write_index_price_updates(
        [_index(hour, price, ETH_INDEX_ID) for hour, price in enumerate(prices)],
        first,
        last,
    )
