from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from math import sqrt

from nautilus_trader.model import Bar, CryptoPerpetual, InstrumentId

_MINUTE_NS = 60_000_000_000
_MINUTE = timedelta(minutes=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class Anchor(Enum):
    """When a VWAP starts over: at each UTC midnight, at each Monday's UTC
    midnight, or only when the strategy calls ``reset``."""

    SESSION = "session"
    WEEK = "week"
    STRATEGY = "strategy"

    def period(self, opened: datetime) -> date | None:
        """The period a minute that opens at ``opened`` falls in; ``None`` when
        the strategy sets the anchor."""
        day = opened.date()
        match self:
            case Anchor.SESSION:
                return day
            case Anchor.WEEK:
                return day - timedelta(days=day.weekday())
            case Anchor.STRATEGY:
                return None


class MultiVenueVwap:
    """The VWAP of the 1-minute candles of several exchanges since an anchor.

    The strategy hands every candle of its feeds to ``update``. A minute counts
    once every feed has reported it, or a candle of a later minute has come; a
    feed without a candle in a minute is left out of it, never filled. The
    typical price of a candle is the mean of its high, low and close, and its
    volume counts in the base coin: the candle's volume times the instrument's
    multiplier, or for an inverse instrument, whose volume is in the quote
    currency, divided by the typical price. A candle that has come before
    ``reset`` counts if its minute is not yet complete.
    """

    def __init__(
        self, instruments: Iterable[CryptoPerpetual], anchor: Anchor = Anchor.SESSION
    ) -> None:
        self._instruments = {each.id: each for each in instruments}
        self._anchor = anchor
        self._pending: dict[int, dict[InstrumentId, Bar]] = {}
        self._published = -1
        self._period: date | None = None
        self._volume = 0.0
        self._weighted_price = 0.0
        self._weighted_square = 0.0
        self._by_feed: dict[InstrumentId, float] = {}

    def update(self, bar: Bar) -> None:
        """Take in one candle of a feed."""
        minute = (bar.ts_event + 1) // _MINUTE_NS - 1
        if minute <= self._published:
            return
        self._pending.setdefault(minute, {})[bar.bar_type.instrument_id] = bar
        self._publish_due()

    def reset(self) -> None:
        """Start the VWAP over from the next minute."""
        self._volume = 0.0
        self._weighted_price = 0.0
        self._weighted_square = 0.0
        self._by_feed = {}

    @property
    def vwap(self) -> float | None:
        """The VWAP since the anchor; ``None`` before the first minute."""
        if self._volume == 0:
            return None
        return self._weighted_price / self._volume

    def bands(self, deviations: float) -> tuple[float, float] | None:
        """The VWAP minus and plus ``deviations`` volume-weighted standard
        deviations of the typical price around it; ``None`` before the first
        minute."""
        vwap = self.vwap
        if vwap is None:
            return None
        variance = max(self._weighted_square / self._volume - vwap**2, 0.0)
        spread = deviations * sqrt(variance)
        return vwap - spread, vwap + spread

    def shares(self) -> Mapping[InstrumentId, float]:
        """The share of each feed that has volume in the total volume since the
        anchor; none before the first minute."""
        if self._volume == 0:
            return {}
        return {key: each / self._volume for key, each in self._by_feed.items()}

    def _publish_due(self) -> None:
        latest = max(self._pending)
        for minute in sorted(self._pending):
            complete = len(self._pending[minute]) == len(self._instruments)
            if minute < latest or complete:
                self._publish(minute, self._pending.pop(minute).values())

    def _publish(self, minute: int, bars: Iterable[Bar]) -> None:
        self._published = minute
        self._enter_period(_EPOCH + minute * _MINUTE)
        for bar in bars:
            self._add(bar)

    def _enter_period(self, opened: datetime) -> None:
        period = self._anchor.period(opened)
        if period != self._period:
            self._period = period
            self.reset()

    def _add(self, bar: Bar) -> None:
        instrument = self._instruments[bar.bar_type.instrument_id]
        price = (bar.high.as_double() + bar.low.as_double() + bar.close.as_double()) / 3
        volume = _base_volume(bar.volume.as_double(), price, instrument)
        self._volume += volume
        self._weighted_price += volume * price
        self._weighted_square += volume * price**2
        self._by_feed[instrument.id] = self._by_feed.get(instrument.id, 0.0) + volume


def _base_volume(volume: float, price: float, instrument: CryptoPerpetual) -> float:
    if instrument.is_inverse:
        return volume / price
    return volume * instrument.multiplier.as_double()
