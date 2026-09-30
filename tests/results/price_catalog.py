"""A catalog of perps with mark prices and funding at chosen times, and a run on it."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_run import spec
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    CryptoPerpetual,
    Currency,
    FundingRateUpdate,
    InstrumentId,
    MarkPriceUpdate,
    Price,
    Quantity,
    Symbol,
)

from sbt2.data import Catalog
from sbt2.data.catalog import CatalogWriter, DayFile
from sbt2.spec import ResolvedRunSpec

BTC = InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT")
ETH = InstrumentId.from_str("ETHUSDT-LINEAR.BYBIT")
TAKER_RATE = Decimal("0.00055")
FEE_MODEL = {
    "path": "nautilus_trader.execution:MakerTakerFeeModel",
    "config": {"maker_rate": "0.0002", "taker_rate": str(TAKER_RATE)},
}
DAY_NS = 86_400_000_000_000

type Prices = Mapping[datetime, float]


def run_on(
    instruments: Sequence[InstrumentId], start: datetime, end: datetime
) -> ResolvedRunSpec:
    """A run over ``[start, end]`` on an hourly equity grid, fees by ``FEE_MODEL``."""
    run = spec(end)
    return replace(
        run,
        strategy=replace(run.strategy, instruments=list(instruments)),
        venue={**run.venue, "fee_model": FEE_MODEL},
        start=start,
        end=end,
    )


class PriceCatalog:
    def __init__(self, path: Path) -> None:
        self._writer = CatalogWriter(path)
        self._instruments: dict[InstrumentId, Any] = {}
        self.catalog = Catalog(path)

    def add_instrument(self, instrument: Any) -> None:
        """Price ``instrument`` instead of a linear perpetual of its id."""
        self._instruments[instrument.id] = instrument

    def add_marks(self, instrument_id: InstrumentId, prices: Prices) -> None:
        records = [
            MarkPriceUpdate(instrument_id, Price(value, 2), ts, ts)
            for ts, value in _nanos(prices)
        ]
        self._write_days(MarkPriceUpdate, instrument_id, records)

    def add_funding(
        self, instrument_id: InstrumentId, rates: Mapping[datetime, Decimal]
    ) -> None:
        records = [
            FundingRateUpdate(instrument_id, rate, ts, ts, interval=480)
            for ts, rate in _nanos(rates)
        ]
        self._write_days(FundingRateUpdate, instrument_id, records)

    def _write_days(
        self, data_type: type, instrument_id: InstrumentId, records: Sequence[Any]
    ) -> None:
        instrument = self._instruments.get(instrument_id) or perpetual(instrument_id)
        self._writer.write_instrument(instrument)
        for day in sorted({each.ts_event // DAY_NS for each in records}):
            within = [each for each in records if each.ts_event // DAY_NS == day]
            bounds = (day * DAY_NS, (day + 1) * DAY_NS - 1)
            self._writer.write(DayFile(data_type, instrument, bounds), within)


def perpetual(instrument_id: InstrumentId) -> CryptoPerpetual:
    usdt = Currency.from_str("USDT")
    return CryptoPerpetual(
        instrument_id,
        Symbol(instrument_id.symbol.value),
        Currency.from_str(instrument_id.symbol.value.removesuffix("USDT-LINEAR")),
        usdt,
        usdt,
        False,
        2,
        3,
        Price.from_str("0.01"),
        Quantity.from_str("0.001"),
        0,
        0,
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
    )


def perpetual_with(instrument_id: InstrumentId, **changes: Any) -> CryptoPerpetual:
    """A perpetual of ``instrument_id`` with some of its fields changed."""
    fields = CryptoPerpetual.to_dict(perpetual(instrument_id))
    return CryptoPerpetual.from_dict({**fields, **changes})


def _nanos[T](values: Mapping[datetime, T]) -> list[tuple[int, T]]:
    return sorted((dt_to_unix_nanos(moment), value) for moment, value in values.items())
