from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

import pandas as pd

from sbt2.core.results.metrics.curves import RunTables
from sbt2.core.results.metrics.money import amounts
from sbt2.core.results.metrics.trades import closed_trades
from sbt2.core.strategy import combo_ids

TRADE_COLUMNS = [
    "trade_id",
    "instrument_id",
    "ts_opened",
    "ts_closed",
    "days_held",
    "credit",
    "pl",
    "pl_percent",
    "index_at_close",
    "pl_usd",
]
_BASE = ["trade_id", "instrument_id", "ts_opened", "ts_closed", "credit", "pl"]
_DAY = pd.Timedelta(days=1)
_FLAT = 1e-9


@dataclass(frozen=True)
class _Fill:
    """What a fill brought in: ``sign`` is 1 for a sale and -1 for a purchase."""

    instrument: str
    at: pd.Timestamp
    sign: float
    qty: float
    px: float
    fee: float
    combos: tuple[str, ...]
    position: str | None

    @property
    def flow(self) -> float:
        return self.sign * self.qty * self.px


@dataclass(frozen=True)
class _Trade:
    trade_id: str
    instrument: str
    opened: pd.Timestamp
    closed: pd.Timestamp
    credit: float
    pl: float


def trade_table(
    run: RunTables, index_prices: Mapping[str, pd.Series] | None = None
) -> pd.DataFrame:
    """One row per closed trade, as the ``TRADE_COLUMNS`` name them.

    A trade is a combo, found by the combo ids in the tags of the orders of the
    fills, or else a position. Its ``pl`` is in the settlement currency after
    fees, and its ``credit`` the premium taken in at entry, a debit negative.
    A settlement fill shared by several combos is split between them by the
    quantity each held of the contract. ``index_prices`` give each instrument's
    index by time; ``index_at_close`` is its last price at or before the close,
    and ``pl_usd`` the ``pl`` at that price.
    """
    fills = _fills(run)
    tagged = [each for each in fills if each.combos]
    untagged = [each for each in fills if not each.combos]
    trades = [*_combo_trades(tagged), *_position_trades(untagged, run)]
    trades.sort(key=lambda each: each.opened)
    return _table(trades, index_prices or {})


def _fills(run: RunTables) -> list[_Fill]:
    fills = run.fills
    if fills.empty:
        return []
    positions = fills["position_id"] if "position_id" in fills else [None] * len(fills)
    rows = zip(
        fills["instrument_id"].astype(str),
        pd.to_datetime(fills["ts_event"], utc=True),
        fills["order_side"],
        fills["last_qty"].astype(float),
        fills["last_px"].astype(float),
        amounts(fills["commission"], run.currency),
        _combos_of(fills, run.orders),
        positions,
        strict=True,
    )
    return [
        _Fill(
            instrument,
            at,
            1.0 if side == "SELL" else -1.0,
            qty,
            px,
            fee,
            ids,
            None if position is None else str(position),
        )
        for instrument, at, side, qty, px, fee, ids, position in rows
    ]


def _combos_of(fills: pd.DataFrame, orders: pd.DataFrame) -> list[tuple[str, ...]]:
    if orders.empty or "tags" not in orders:
        return [()] * len(fills)
    tags = orders.set_index("venue_order_id")["tags"].to_dict()
    return [_ids(tags.get(each)) for each in fills["venue_order_id"]]


def _ids(tags: object) -> tuple[str, ...]:
    if isinstance(tags, str) or not isinstance(tags, Iterable):
        return ()
    return combo_ids(tags)


def _combo_trades(fills: list[_Fill]) -> list[_Trade]:
    by_combo: defaultdict[str, list[_Fill]] = defaultdict(list)
    for combo, share in _shares(fills):
        by_combo[combo].append(share)
    return [
        _trade(combo, shares) for combo, shares in by_combo.items() if _is_flat(shares)
    ]


def _shares(fills: list[_Fill]) -> list[tuple[str, _Fill]]:
    """One fill per combo it belongs to, with the quantity and fee that combo bears."""
    held = _held(fills)
    shares = []
    for fill in fills:
        weights = _weights(fill, held)
        shares.extend(
            (combo, replace(fill, qty=fill.qty * w, fee=fill.fee * w))
            for combo, w in weights.items()
        )
    return shares


def _held(fills: list[_Fill]) -> dict[tuple[str, str], float]:
    """The quantity each combo holds of a contract, from the fills only it has."""
    net: defaultdict[tuple[str, str], float] = defaultdict(float)
    for fill in fills:
        if len(fill.combos) == 1:
            net[(fill.combos[0], fill.instrument)] += fill.sign * fill.qty
    return {key: abs(value) for key, value in net.items()}


def _weights(fill: _Fill, held: Mapping[tuple[str, str], float]) -> dict[str, float]:
    if len(fill.combos) == 1:
        return {fill.combos[0]: 1.0}
    sizes = {each: held.get((each, fill.instrument), 0.0) for each in fill.combos}
    total = sum(sizes.values())
    if total <= 0:
        return {each: 1 / len(fill.combos) for each in fill.combos}
    return {each: size / total for each, size in sizes.items()}


def _is_flat(shares: list[_Fill]) -> bool:
    net: defaultdict[str, float] = defaultdict(float)
    for fill in shares:
        net[fill.instrument] += fill.sign * fill.qty
    return all(abs(value) < _FLAT for value in net.values())


def _trade(trade_id: str, shares: list[_Fill]) -> _Trade:
    ordered = sorted(shares, key=lambda each: each.at)
    return _Trade(
        trade_id,
        ordered[0].instrument,
        ordered[0].at,
        ordered[-1].at,
        sum(each.flow for each in _entries(ordered)),
        sum(each.flow - each.fee for each in ordered),
    )


def _entries(ordered: list[_Fill]) -> list[_Fill]:
    """The fills that open a contract's position: those on the side of its first."""
    first: dict[str, float] = {}
    for fill in ordered:
        first.setdefault(fill.instrument, fill.sign)
    return [each for each in ordered if each.sign == first[each.instrument]]


def _position_trades(fills: list[_Fill], run: RunTables) -> list[_Trade]:
    if "ts_closed" not in run.positions:
        return []
    closed = closed_trades(run.positions, run.currency)
    closed = closed.loc[
        closed.index.astype(str).isin({each.position for each in fills})
    ]
    credit = _position_credit(fills, closed)
    rows = zip(
        closed.index.astype(str),
        closed["instrument_id"].astype(str),
        pd.to_datetime(closed["ts_opened"], utc=True),
        pd.to_datetime(closed["ts_closed"], utc=True),
        closed["pnl"].astype(float),
        strict=True,
    )
    return [
        _Trade(
            position, instrument, opened, ended, credit.get(position, float("nan")), pnl
        )
        for position, instrument, opened, ended, pnl in rows
    ]


def _position_credit(fills: list[_Fill], closed: pd.DataFrame) -> dict[str, float]:
    entry_sign = {
        str(position): 1.0 if entry == "SELL" else -1.0
        for position, entry in zip(closed.index, closed["entry"], strict=True)
    }
    credit: defaultdict[str, float] = defaultdict(float)
    for fill in fills:
        if fill.position in entry_sign and fill.sign == entry_sign[fill.position]:
            credit[fill.position] += fill.flow
    return dict(credit)


def _table(trades: list[_Trade], index_prices: Mapping[str, pd.Series]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "trade_id": [each.trade_id for each in trades],
            "instrument_id": [each.instrument for each in trades],
            "ts_opened": pd.to_datetime([each.opened for each in trades], utc=True),
            "ts_closed": pd.to_datetime([each.closed for each in trades], utc=True),
            "credit": pd.Series([each.credit for each in trades], dtype=float),
            "pl": pd.Series([each.pl for each in trades], dtype=float),
        }
    )
    index_at_close = pd.Series(
        [_index_at(index_prices.get(each.instrument), each.closed) for each in trades],
        dtype=float,
    )
    credit, pl = frame["credit"], frame["pl"]
    return pd.DataFrame(
        {
            **{name: frame[name] for name in _BASE},
            "days_held": (frame["ts_closed"] - frame["ts_opened"]) / _DAY,
            "pl_percent": pl / credit.abs().where(credit != 0) * 100,
            "index_at_close": index_at_close,
            "pl_usd": pl * index_at_close,
        },
        columns=TRADE_COLUMNS,
    )


def _index_at(prices: pd.Series | None, moment: pd.Timestamp) -> float:
    if prices is None:
        return float("nan")
    known = prices.sort_index().loc[:moment].to_list()
    return float(known[-1]) if known else float("nan")
