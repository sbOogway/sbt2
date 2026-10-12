from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    CryptoOption,
    InstrumentId,
    OptionKind,
    OrderSide,
    QuoteTick,
)

from sbt2.core.strategy.chain import NoMarketError

_DAY_NS = 86_400 * 10**9
Quotes = Callable[[CryptoOption], QuoteTick | None]


@dataclass(frozen=True)
class Leg:
    """``quantity`` contracts of ``contract`` bought or sold; ``price`` is the
    entry price in the coin once the leg is filled."""

    contract: CryptoOption
    side: OrderSide
    quantity: Decimal
    price: Decimal | None = None

    @property
    def is_short(self) -> bool:
        return self.side == OrderSide.SELL


@dataclass(frozen=True)
class Combo:
    """Legs opened and closed together as one position. ``id`` is set when the
    strategy opens the combo; the fills of its legs carry it."""

    name: str
    legs: tuple[Leg, ...]
    id: str = ""

    @property
    def defined_risk(self) -> bool:
        """Whether every short leg is covered by a long leg of the same kind and
        expiry, further out of the money; one long leg covers one short leg."""
        return all(
            _covered(self.legs, kind, expiry)
            for kind, expiry in {
                (leg.contract.option_kind, leg.contract.expiration_ns)
                for leg in self.legs
            }
        )

    @property
    def credit(self) -> Decimal:
        """The premium taken in at entry, in the coin; negative for a debit."""
        return sum((_flow(leg, _entry(leg)) for leg in self.legs), Decimal(0))

    def priced(self, entries: Mapping[InstrumentId, Decimal]) -> Combo:
        """The combo with the entry price of each leg."""
        return replace(
            self,
            legs=tuple(
                replace(leg, price=entries[leg.contract.id]) for leg in self.legs
            ),
        )

    def pl(self, quote: Quotes) -> Decimal:
        """The profit or loss in the coin if the combo closed now: its credit less
        the cost of closing, which buys the short legs at the ask and sells the
        long legs at the bid."""
        return self.credit + sum(
            (_flow(leg, _closing_price(leg, quote)) for leg in self.legs), Decimal(0)
        )

    def pl_percent(self, quote: Quotes) -> Decimal:
        """``pl`` as a percentage of the credit's size."""
        return self.pl(quote) / abs(self.credit) * 100

    def dte(self, now: datetime) -> float:
        """The days to the nearest expiry of the legs."""
        nearest = min(leg.contract.expiration_ns for leg in self.legs)
        return (nearest - dt_to_unix_nanos(now)) / _DAY_NS


def short_strangle(put: CryptoOption, call: CryptoOption, quantity: Decimal) -> Combo:
    """Sells a put and a call of one expiry."""
    _require_one_expiry(put, call)
    return _selling("short strangle", (put, call), quantity)


def short_straddle(put: CryptoOption, call: CryptoOption, quantity: Decimal) -> Combo:
    """Sells a put and a call of one expiry and one strike."""
    _require_one_expiry(put, call)
    if put.strike_price != call.strike_price:
        raise ValueError("a straddle needs one strike")
    return _selling("short straddle", (put, call), quantity)


def iron_condor(body: Combo, put_wing: CryptoOption, call_wing: CryptoOption) -> Combo:
    """``body``, a short strangle, with a long put and a long call of its size and
    expiry."""
    [short_leg, *_] = body.legs
    _require_one_expiry(short_leg.contract, put_wing, call_wing)
    wings = tuple(
        Leg(each, OrderSide.BUY, short_leg.quantity) for each in (put_wing, call_wing)
    )
    return Combo("iron condor", (*body.legs, *wings))


def vertical_spread(
    short: CryptoOption, long: CryptoOption, quantity: Decimal
) -> Combo:
    """Sells ``short`` and buys ``long``, of one kind and expiry."""
    _require_one_expiry(short, long)
    if short.option_kind != long.option_kind:
        raise ValueError("a vertical spread needs one kind")
    legs = (
        Leg(short, OrderSide.SELL, quantity),
        Leg(long, OrderSide.BUY, quantity),
    )
    return Combo("vertical spread", legs)


def short_put(put: CryptoOption, quantity: Decimal) -> Combo:
    """Sells a put."""
    if put.option_kind != OptionKind.PUT:
        raise ValueError("a short put sells a put")
    return _selling("short put", (put,), quantity)


@dataclass(frozen=True)
class ComboExit:
    """When to close an open combo: at ``dte`` days to its nearest expiry or
    fewer, once its profit is ``profit_target`` percent of its credit or more,
    or once its loss is ``loss_target`` percent of its credit or more. A rule
    left out never closes."""

    dte: float | None = None
    profit_target: Decimal | None = None
    loss_target: Decimal | None = None

    def reached(self, combo: Combo, now: datetime, quote: Quotes) -> bool:
        if self.dte is not None and combo.dte(now) <= self.dte:
            return True
        if self.profit_target is None and self.loss_target is None:
            return False
        percent = combo.pl_percent(quote)
        return (self.profit_target is not None and percent >= self.profit_target) or (
            self.loss_target is not None and percent <= -self.loss_target
        )


def _selling(
    name: str, contracts: tuple[CryptoOption, ...], quantity: Decimal
) -> Combo:
    return Combo(name, tuple(Leg(each, OrderSide.SELL, quantity) for each in contracts))


def _require_one_expiry(*contracts: CryptoOption) -> None:
    if len({each.expiration_ns for each in contracts}) > 1:
        raise ValueError("a combo of these legs needs one expiry")


def _entry(leg: Leg) -> Decimal:
    if leg.price is None:
        raise ValueError("a combo has no credit before it has entry prices")
    return leg.price


def _flow(leg: Leg, price: Decimal) -> Decimal:
    """What the leg brings in at ``price``: a sold leg brings it in, a bought leg
    pays it out."""
    return (1 if leg.is_short else -1) * leg.quantity * price


def _closing_price(leg: Leg, quote: Quotes) -> Decimal:
    found = quote(leg.contract)
    if found is None:
        raise NoMarketError(f"{leg.contract.id} has no quote to close at")
    price = found.ask_price if leg.is_short else found.bid_price
    return -Decimal(str(price))


def _covered(legs: tuple[Leg, ...], kind: OptionKind, expiry: int) -> bool:
    group = [
        leg
        for leg in legs
        if leg.contract.option_kind == kind and leg.contract.expiration_ns == expiry
    ]
    depth = _depth(kind)
    covers = [leg for leg in group if not leg.is_short]
    spare = [leg.quantity for leg in covers]
    # the furthest short has the fewest covers, so it picks first
    shorts = sorted((leg for leg in group if leg.is_short), key=depth, reverse=True)
    for short in shorts:
        needed = short.quantity
        for index, cover in enumerate(covers):
            if depth(cover) > depth(short):
                taken = min(needed, spare[index])
                spare[index] -= taken
                needed -= taken
        if needed > 0:
            return False
    return True


def _depth(kind: OptionKind) -> Callable[[Leg], float]:
    """How far out of the money a leg is, relative to the legs of its kind: it
    grows with the strike for a call and falls with it for a put."""
    sign = 1 if kind == OptionKind.CALL else -1
    return lambda leg: sign * float(leg.contract.strike_price)
