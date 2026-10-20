from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, override

from nautilus_trader.model import (
    AggregationSource,
    Bar,
    BarSpecification,
    InstrumentId,
    OrderSide,
)

from sbt2.core.strategy import Anchor, MultiVenueVwap, Strategy

BTC_PERPETUALS = (
    "BTCUSDT-PERP.BINANCE",
    "BTC-USDT-SWAP.OKX",
    "BTC-PERP.COINBASE_INTX",
    "BTCUSDT-LINEAR.BYBIT",
    "BTC-PERPETUAL.DERIBIT",
)
ETH_PERPETUALS = (
    "ETHUSDT-PERP.BINANCE",
    "ETH-USDT-SWAP.OKX",
    "ETH-PERP.COINBASE_INTX",
    "ETHUSDT-LINEAR.BYBIT",
    "ETH-PERPETUAL.DERIBIT",
)

_MINUTE_NS = 60_000_000_000
_DAY_MINUTES = 1440
_MINUTES = BarSpecification.from_str("1-MINUTE-LAST")


@dataclass(frozen=True)
class VwapParams:
    """``feeds`` are the instruments whose candles make the VWAP, one session
    a UTC day; the strategy decides every ``decision_minutes`` minutes."""

    feeds: tuple[str, ...] = BTC_PERPETUALS
    decision_minutes: int = 30


class VwapSession[P: VwapParams](Strategy[P], ABC):
    """A strategy that decides at fixed times of the UTC day, on the session VWAP
    of several exchanges, and is flat at the end of the session.

    The bar of the traded instrument that closes at a decision time calls
    ``decide`` with the VWAP; its answer is the position to hold, in multiples of
    the equity, or ``None`` to keep the one held. A position is never resized
    while it keeps its direction. ``observe`` hears every bar of the traded
    instrument and ``end_session`` the last one of each session.
    """

    @classmethod
    @override
    def inputs(cls, params: P) -> Sequence[BarSpecification]:
        return (_MINUTES,)

    @classmethod
    @override
    def feeds(cls, params: P, /) -> Sequence[InstrumentId]:
        return tuple(InstrumentId.from_str(each) for each in params.feeds)

    @abstractmethod
    def decide(self, bar: Bar, vwap: MultiVenueVwap) -> float | None: ...

    def observe(self, bar: Bar) -> None:
        """Hear a bar of the traded instrument, before any decision."""

    def end_session(self, bar: Bar) -> None:
        """Hear the last bar of a session, whose close ends it."""

    @override
    def on_start(self) -> None:
        super().on_start()
        self._vwap = MultiVenueVwap(self._feed_instruments(), Anchor.SESSION)

    @override
    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type.aggregation_source == AggregationSource.EXTERNAL:
            self._vwap.update(bar)
        elif bar.bar_type.instrument_id == self.instrument_ids[0]:
            self._hear(bar)

    def _hear(self, bar: Bar) -> None:
        self.observe(bar)
        closes_at = ((bar.ts_event + 1) // _MINUTE_NS) % _DAY_MINUTES
        if closes_at == 0:
            self.end_session(bar)
            self._move_to(0.0, bar)
        elif closes_at % self.params.decision_minutes == 0:
            weight = self.decide(bar, self._vwap)
            if weight is not None:
                self._move_to(weight, bar)

    def _feed_instruments(self) -> list[Any]:
        found = [self.cache.instrument(each) for each in self.feeds(self.params)]
        if None in found:
            raise LookupError("a feed of the VWAP is not in the cache")
        return found

    def _move_to(self, weight: float, bar: Bar) -> None:
        instrument_id = bar.bar_type.instrument_id
        held = Decimal(self.portfolio.net_position(instrument_id))
        if weight != 0 and held * Decimal(weight) > 0:
            return
        change = self._quantity_of(weight, bar) - held
        if change != 0:
            side = OrderSide.BUY if change > 0 else OrderSide.SELL
            quantity = self._instrument(instrument_id).make_qty(abs(change))
            self.submit_order(self.order_factory.market(instrument_id, side, quantity))

    def _quantity_of(self, weight: float, bar: Bar) -> Decimal:
        """The signed quantity worth ``weight`` times the equity at the close."""
        instrument = self._instrument(bar.bar_type.instrument_id)
        price = Decimal(bar.close.as_double())
        equity = self._total_equity(instrument.id)
        if instrument.is_inverse:
            return Decimal(weight) * equity * price
        return Decimal(weight) * equity / (price * instrument.multiplier.as_decimal())

    def _instrument(self, instrument_id: InstrumentId) -> Any:
        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            raise LookupError(f"instrument {instrument_id} is not in the cache")
        return instrument
