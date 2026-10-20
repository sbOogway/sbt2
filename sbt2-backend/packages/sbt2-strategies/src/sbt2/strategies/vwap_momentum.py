from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from statistics import mean, stdev
from typing import override

from nautilus_trader.model import Bar

from sbt2.core.strategy import MultiVenueVwap, RunConfig
from sbt2.strategies.vwap_session import VwapParams, VwapSession

_MIN_RETURNS = 2


@dataclass(frozen=True)
class MomentumParams(VwapParams):
    """``days`` is how far back the noise bands and the daily volatility look.
    The bands are ``noise_multiplier`` times the noise around the open. The
    position is ``target_volatility`` over the daily volatility, in multiples
    of the equity, at most ``max_leverage``."""

    days: int = 14
    noise_multiplier: float = 1.0
    target_volatility: float = 0.02
    max_leverage: float = 1.0


class NoiseBand:
    """The mean absolute move from the open of the last ``days`` sessions, at
    each time of the day."""

    def __init__(self, days: int) -> None:
        self._days = days
        self._moves: dict[int, deque[float]] = {}

    def record(self, minute: int, move: float) -> None:
        self._moves.setdefault(minute, deque(maxlen=self._days)).append(move)

    def sigma(self, minute: int) -> float | None:
        """``None`` until ``days`` sessions have recorded ``minute``."""
        moves = self._moves.get(minute, ())
        return mean(moves) if len(moves) == self._days else None


def volatility_weight(returns: list[float], target: float, cap: float) -> float:
    """``target`` over the standard deviation of ``returns``, at most ``cap``;
    ``cap`` when the returns do not vary."""
    spread = stdev(returns) if len(returns) >= _MIN_RETURNS else 0.0
    return cap if spread == 0 else min(cap, target / spread)


class VwapMomentum(VwapSession[MomentumParams]):
    """Intraday momentum in the noise area, with the VWAP as a trailing stop.

    Long when the close is above the upper noise band and the session VWAP,
    short when it is below the lower band and the VWAP, else flat. So a long
    stops out below the higher of the upper band and the VWAP, a short above
    the lower of the lower band and the VWAP. The bands are the open times one
    plus or minus the noise of that time of the day; a session that the run
    joined after its open does not trade.
    """

    Params = MomentumParams

    @classmethod
    @override
    def warmup(cls, params: MomentumParams, /) -> timedelta:
        return timedelta(days=params.days + 1)

    def __init__(self, config: RunConfig) -> None:
        super().__init__(config)
        self._noise = NoiseBand(self.params.days)
        self._daily: deque[float] = deque(maxlen=self.params.days)
        self._open: float | None = None

    @override
    def observe(self, bar: Bar) -> None:
        if self.closing_minute(bar) == 1:
            self._open = bar.open.as_double()

    @override
    def end_session(self, bar: Bar) -> None:
        if self._open is not None:
            self._daily.append(bar.close.as_double() / self._open - 1)
        self._open = None

    @override
    def decide(self, bar: Bar, vwap: MultiVenueVwap) -> float | None:
        opened, level = self._open, vwap.vwap
        if opened is None or level is None:
            return None
        close = bar.close.as_double()
        minute = self.closing_minute(bar)
        sigma = self._noise.sigma(minute)
        self._noise.record(minute, abs(close / opened - 1))
        if sigma is None or len(self._daily) < self.params.days:
            return None
        spread = self.params.noise_multiplier * sigma
        side = _side(close, level, (opened * (1 - spread), opened * (1 + spread)))
        return side * volatility_weight(
            list(self._daily), self.params.target_volatility, self.params.max_leverage
        )


def _side(close: float, level: float, band: tuple[float, float]) -> int:
    if close > max(band[1], level):
        return 1
    return -1 if close < min(band[0], level) else 0
