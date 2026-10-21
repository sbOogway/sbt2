from dataclasses import dataclass
from typing import override

from nautilus_trader.model import Bar

from sbt2.core.strategy import MultiVenueVwap, RunConfig
from sbt2.strategies.vwap.session import VwapParams, VwapSession


@dataclass(frozen=True)
class BandFadeParams(VwapParams):
    """``entry_deviations`` and ``stop_deviations`` are the distances of the
    entry and of the stop from the VWAP, in volume-weighted standard
    deviations; ``size`` is the position in multiples of the equity."""

    entry_deviations: float = 2.0
    stop_deviations: float = 3.0
    size: float = 1.0


class VwapBandFade(VwapSession[BandFadeParams]):
    """Fades the VWAP bands: short when the close crosses above the VWAP plus
    ``entry_deviations`` deviations, long when it crosses below the VWAP minus
    as many.

    The position closes at the VWAP, at ``stop_deviations`` deviations from it
    or at the end of the session. A close that is still outside the bands from
    the last decision, such as after a stop, does not enter again.
    """

    Params = BandFadeParams

    def __init__(self, config: RunConfig) -> None:
        super().__init__(config)
        self._side = 0
        self._outside = 0

    @override
    def end_session(self, bar: Bar) -> None:
        self._side = 0
        self._outside = 0

    @override
    def decide(self, bar: Bar, vwap: MultiVenueVwap) -> float | None:
        close = bar.close.as_double()
        outside = self._where(close, vwap)
        crossed = outside != 0 and outside != self._outside
        self._outside = outside
        if self._side != 0:
            return self._manage(close, vwap)
        if crossed:
            self._side = -outside
            return self._side * self.params.size
        return None

    def _where(self, close: float, vwap: MultiVenueVwap) -> int:
        """1 above the entry bands, -1 below them, 0 inside or without bands."""
        low, high = vwap.bands(self.params.entry_deviations) or (0.0, 0.0)
        if high <= low:
            return 0
        return 1 if close > high else -1 if close < low else 0

    def _manage(self, close: float, vwap: MultiVenueVwap) -> float | None:
        low, high = vwap.bands(self.params.stop_deviations) or (0.0, 0.0)
        level = vwap.vwap
        if level is None:
            return None
        reached = close <= level if self._side < 0 else close >= level
        stopped = close >= high if self._side < 0 else close <= low
        if reached or stopped:
            self._side = 0
            return 0.0
        return None
