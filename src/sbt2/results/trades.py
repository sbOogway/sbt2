import pandas as pd

from sbt2.results.money import amounts


def closed_trades(positions: pd.DataFrame, currency: str) -> pd.DataFrame:
    """Closed positions and snapshots, with their realized PnL as ``pnl``.

    A position still open at the end has no close time, so it is left out.
    """
    if positions.empty:
        return pd.DataFrame(
            columns=["instrument_id", "entry", "ts_closed", "duration_ns", "pnl"]
        )
    trades = positions.loc[positions["ts_closed"].notna()]
    return trades.assign(pnl=amounts(trades["realized_pnl"], currency))
