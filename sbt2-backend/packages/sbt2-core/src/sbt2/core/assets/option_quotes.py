import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from nautilus_trader.model import (
    CryptoOption,
    OptionKind,
    Price,
    Quantity,
    QuoteTick,
    black_scholes_greeks,
    imply_vol,
)

_YEAR_NANOS = 365 * 86_400 * 10**9
QUOTE_SIZE = 1_000_000
# The solver's float noise, in ticks, must not move a rounded price.
_NOISE_DIGITS = 2


@dataclass(frozen=True)
class QuoteSettings:
    """The spread model: a quote every ``interval_seconds``, half a spread of
    ``ticks`` ticks or ``fraction`` of the price, whichever is larger."""

    interval_seconds: int = 60
    ticks: int = 1
    fraction: float = 0.05

    def __post_init__(self) -> None:
        if self.interval_seconds < 1:
            raise ValueError("the interval is at least 1 second")
        if self.ticks < 0 or self.fraction < 0:
            raise ValueError("the half-spread is not negative")


@dataclass(frozen=True)
class OptionHistory:
    """What the quotes of one contract are made from.

    ``marks`` has a ``price`` column in the contract's quote currency, ``greeks``
    has ``mark_iv`` and ``underlying_price`` columns, and ``index`` is the index
    price; all are indexed by event time.
    """

    contract: CryptoOption
    marks: pd.DataFrame
    greeks: pd.DataFrame
    index: pd.Series


def quote_ticks(
    history: OptionHistory, settings: QuoteSettings, span: tuple[datetime, datetime]
) -> list[QuoteTick]:
    """The contract's quotes on the settings' grid within ``span``.

    The mid is the Black-Scholes price from the index at the quote's time and the
    vol implied by the last mark, so it equals a mark at the mark's time. A
    contract has no quote before its first mark or from its expiry on.

    Each quote has a size of 1,000,000 on both sides, so depth is unlimited at the
    quoted price: an order of any size fills at the bid or the ask. This is a known
    limitation.
    """
    grid = _grid(history, settings, span)
    mids = _mids(history, grid)
    return [
        _quote(history.contract, settings, (int(ts), mid))
        for ts, mid in zip(grid, mids, strict=True)
        if not math.isnan(mid)
    ]


def _nanos(index: pd.Index) -> np.ndarray:
    return pd.DatetimeIndex(index).as_unit("ns").asi8


def _ns(moment: datetime) -> int:
    return pd.Timestamp(moment).value


def _grid(
    history: OptionHistory, settings: QuoteSettings, span: tuple[datetime, datetime]
) -> np.ndarray:
    if history.marks.empty:
        return np.array([], dtype=np.int64)
    step = settings.interval_seconds * 10**9
    first = max(_ns(span[0]), int(_nanos(history.marks.index)[0]))
    end = min(_ns(span[1]), history.contract.expiration_ns)
    return np.arange(-(-first // step) * step, end, step, dtype=np.int64)


def _mids(history: OptionHistory, grid: np.ndarray) -> np.ndarray:
    """The mid of each grid time, NaN where there is no index or vol yet."""
    vol_ns, vols = _vols(history)
    index_ns = _nanos(history.index.index)
    mids = np.full(len(grid), np.nan)
    for slot, ts in enumerate(grid):
        vol_at = np.searchsorted(vol_ns, ts, side="right") - 1
        index_at = np.searchsorted(index_ns, ts, side="right") - 1
        if vol_at >= 0 and index_at >= 0:
            underlying = float(history.index.iloc[index_at])
            mids[slot] = _price(
                history.contract, (underlying, float(vols[vol_at])), int(ts)
            )
    return mids


def _years(contract: CryptoOption, ts: int) -> float:
    return (contract.expiration_ns - ts) / _YEAR_NANOS


def _is_call(contract: CryptoOption) -> bool:
    return contract.option_kind == OptionKind.CALL


def _price(contract: CryptoOption, market: tuple[float, float], ts: int) -> float:
    """The Black-Scholes price in the quote currency (USD over the index)."""
    underlying, vol = market
    greeks = black_scholes_greeks(
        underlying,
        0.0,
        0.0,
        vol,
        _is_call(contract),
        float(contract.strike_price),
        _years(contract, ts),
    )
    return greeks.price / underlying


def _vols(history: OptionHistory) -> tuple[np.ndarray, np.ndarray]:
    """The vol at each IV record: implied from the mark of that time when it can
    be, else the IV the record holds."""
    greeks = history.greeks
    times = _nanos(greeks.index)
    marks = history.marks["price"].reindex(greeks.index, method="ffill")
    records = zip(
        times, greeks["underlying_price"], greeks["mark_iv"], marks, strict=True
    )
    vols = [
        _anchored(history.contract, (int(ts), underlying, iv), mark)
        for ts, underlying, iv, mark in records
    ]
    return times, np.array(vols, dtype=float)


def _anchored(
    contract: CryptoOption, record: tuple[int, float, float], mark: float
) -> float:
    ts, underlying, mark_iv = record
    try:
        vol = imply_vol(
            underlying,
            0.0,
            0.0,
            _is_call(contract),
            float(contract.strike_price),
            _years(contract, ts),
            mark * underlying,
        )
    except ValueError, RuntimeError:
        return mark_iv
    return vol if math.isfinite(vol) and vol > 0 else mark_iv


def _quote(
    contract: CryptoOption, settings: QuoteSettings, priced: tuple[int, float]
) -> QuoteTick:
    ts, mid = priced
    tick = float(contract.price_increment)
    bid, ask = _tick_counts(mid / tick, settings)
    size = Quantity(QUOTE_SIZE, contract.size_precision)
    precision = contract.price_precision
    return QuoteTick(
        contract.id,
        Price(round(bid * tick, precision), precision),
        Price(round(ask * tick, precision), precision),
        size,
        size,
        ts,
        ts,
    )


def _tick_counts(mid: float, settings: QuoteSettings) -> tuple[int, int]:
    """Bid down and ask up to a tick; the bid is at least one tick."""
    half = max(settings.ticks, settings.fraction * mid)
    bid = max(math.floor(round(mid - half, _NOISE_DIGITS)), 1)
    ask = max(math.ceil(round(mid + half, _NOISE_DIGITS)), bid + 1)
    return bid, ask
