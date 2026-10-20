from nautilus_trader.model import Bar

from sbt2.core.strategy import MultiVenueVwap
from sbt2.strategies.vwap_session import VwapParams, VwapSession


class VwapTrend(VwapSession[VwapParams]):
    """Long the whole equity while the close is above the session VWAP, short
    while it is below, flat at the end of the session.

    The baseline of the VWAP strategies: it decides every half hour, as the
    cost of a trade rules out the minute rule of its paper.
    """

    Params = VwapParams

    def decide(self, bar: Bar, vwap: MultiVenueVwap) -> float | None:
        level = vwap.vwap
        close = bar.close.as_double()
        if level is None or close == level:
            return None
        return 1.0 if close > level else -1.0
