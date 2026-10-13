import pandas as pd

from sbt2.core.market import Rates
from sbt2.core.results.metrics.money import amounts, split_amounts

_COLUMNS = ["instrument_id", "entry", "ts_closed", "duration_ns", "pnl"]


def closed_trades(
    positions: pd.DataFrame, currency: str, rates: Rates | None = None
) -> pd.DataFrame:
    """Closed positions and snapshots, with their realized PnL as ``pnl``, in
    ``currency``; with ``rates``, one realized in another currency converts at
    the time of its close.

    A position still open at the end has no close time, so it is left out.
    """
    if positions.empty:
        return pd.DataFrame(columns=_COLUMNS)
    trades = positions.loc[positions["ts_closed"].notna()]
    if rates is None:
        return trades.assign(pnl=amounts(trades["realized_pnl"], currency))
    closed = closed_positions(positions)
    times = pd.DatetimeIndex(pd.to_datetime(closed["ts_closed"], utc=True))
    factors = rates.factors(list(closed["currency"]), times)
    return closed.assign(pnl=closed["pnl"] * factors).drop(columns="currency")


def closed_positions(positions: pd.DataFrame) -> pd.DataFrame:
    """Like ``closed_trades``, with the ``currency`` each position realized its
    PnL in, whichever it is."""
    if positions.empty:
        return pd.DataFrame(columns=[*_COLUMNS, "currency"])
    closed = positions.loc[positions["ts_closed"].notna()]
    found, currencies = split_amounts(closed["realized_pnl"])
    return closed.assign(pnl=found, currency=currencies)
