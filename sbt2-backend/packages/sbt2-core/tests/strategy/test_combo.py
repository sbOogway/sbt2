from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from nautilus_trader.model import (
    CryptoOption,
    InstrumentId,
    OptionKind,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
)
from option_catalog import Terms, listed_option

from sbt2.core.strategy import (
    Combo,
    ComboExit,
    Leg,
    NoMarketError,
    iron_condor,
    short_put,
    short_straddle,
    short_strangle,
    vertical_spread,
)

NOW = datetime(2024, 1, 2, tzinfo=UTC)
LETTER = {OptionKind.CALL: "C", OptionKind.PUT: "P"}
ONE = Decimal(1)


def contract(strike: int, kind: OptionKind, days: int = 40) -> CryptoOption:
    name = f"BTC-{days}D-{strike}-{LETTER[kind]}.DERIBIT"
    terms = Terms(kind, NOW + timedelta(days=days), str(strike))
    return listed_option(InstrumentId.from_str(name), terms)


def put(strike: int, days: int = 40) -> CryptoOption:
    return contract(strike, OptionKind.PUT, days)


def call(strike: int, days: int = 40) -> CryptoOption:
    return contract(strike, OptionKind.CALL, days)


def legs_of(combo: Combo) -> list[tuple[str, OrderSide, Decimal]]:
    return [
        (leg.contract.id.symbol.value, leg.side, leg.quantity) for leg in combo.legs
    ]


def quotes(
    prices: dict[InstrumentId, tuple[str, str]],
) -> Callable[[CryptoOption], QuoteTick | None]:
    def quote(each: CryptoOption) -> QuoteTick | None:
        if each.id not in prices:
            return None
        bid, ask = (Price.from_str(text) for text in prices[each.id])
        size = Quantity.from_str("1.0")
        return QuoteTick(each.id, bid, ask, size, size, 0, 0)

    return quote


@pytest.mark.unit
def test_a_short_strangle_sells_a_put_and_a_call_of_one_expiry() -> None:
    combo = short_strangle(put(40_000), call(50_000), Decimal(2))

    assert combo.name == "short strangle"
    assert legs_of(combo) == [
        ("BTC-40D-40000-P", OrderSide.SELL, Decimal(2)),
        ("BTC-40D-50000-C", OrderSide.SELL, Decimal(2)),
    ]
    with pytest.raises(ValueError, match="one expiry"):
        short_strangle(put(40_000, days=10), call(50_000), ONE)


@pytest.mark.unit
def test_a_short_straddle_sells_a_put_and_a_call_of_one_strike() -> None:
    combo = short_straddle(put(45_000), call(45_000), ONE)

    assert combo.name == "short straddle"
    assert legs_of(combo) == [
        ("BTC-40D-45000-P", OrderSide.SELL, ONE),
        ("BTC-40D-45000-C", OrderSide.SELL, ONE),
    ]
    with pytest.raises(ValueError, match="one strike"):
        short_straddle(put(40_000), call(45_000), ONE)


@pytest.mark.unit
def test_an_iron_condor_buys_a_wing_on_each_side_of_a_short_strangle() -> None:
    body = short_strangle(put(40_000), call(50_000), ONE)

    combo = iron_condor(body, put(35_000), call(55_000))

    assert combo.name == "iron condor"
    assert legs_of(combo) == [
        ("BTC-40D-40000-P", OrderSide.SELL, ONE),
        ("BTC-40D-50000-C", OrderSide.SELL, ONE),
        ("BTC-40D-35000-P", OrderSide.BUY, ONE),
        ("BTC-40D-55000-C", OrderSide.BUY, ONE),
    ]


@pytest.mark.unit
def test_a_vertical_spread_sells_one_contract_and_buys_another_of_its_kind() -> None:
    combo = vertical_spread(put(40_000), put(35_000), ONE)

    assert combo.name == "vertical spread"
    assert legs_of(combo) == [
        ("BTC-40D-40000-P", OrderSide.SELL, ONE),
        ("BTC-40D-35000-P", OrderSide.BUY, ONE),
    ]
    with pytest.raises(ValueError, match="one kind"):
        vertical_spread(put(40_000), call(45_000), ONE)
    with pytest.raises(ValueError, match="one expiry"):
        vertical_spread(put(40_000), put(35_000, days=10), ONE)


@pytest.mark.unit
def test_a_short_put_sells_one_put() -> None:
    combo = short_put(put(40_000), Decimal(3))

    assert combo.name == "short put"
    assert legs_of(combo) == [("BTC-40D-40000-P", OrderSide.SELL, Decimal(3))]
    with pytest.raises(ValueError, match="put"):
        short_put(call(50_000), ONE)


@pytest.mark.unit
def test_an_iron_condor_and_a_vertical_are_defined_risk() -> None:
    body = short_strangle(put(40_000), call(50_000), ONE)

    assert iron_condor(body, put(35_000), call(55_000)).defined_risk
    assert vertical_spread(put(40_000), put(35_000), ONE).defined_risk
    assert vertical_spread(call(50_000), call(55_000), ONE).defined_risk


@pytest.mark.unit
def test_a_strangle_a_straddle_and_a_short_put_are_undefined_risk() -> None:
    assert not short_strangle(put(40_000), call(50_000), ONE).defined_risk
    assert not short_straddle(put(45_000), call(45_000), ONE).defined_risk
    assert not short_put(put(40_000), ONE).defined_risk


@pytest.mark.unit
def test_a_short_leg_is_undefined_risk_when_its_cover_is_too_small_or_not_its_own() -> (
    None
):
    short = Leg(put(40_000), OrderSide.SELL, Decimal(2))
    small = Leg(put(35_000), OrderSide.BUY, ONE)
    other_expiry = Leg(put(35_000, days=10), OrderSide.BUY, Decimal(2))
    other_kind = Leg(call(55_000), OrderSide.BUY, Decimal(2))

    assert not Combo("odd", (short, small)).defined_risk
    assert not Combo("odd", (short, other_expiry)).defined_risk
    assert not Combo("odd", (short, other_kind)).defined_risk


@pytest.mark.unit
def test_a_debit_vertical_is_defined_risk() -> None:
    assert vertical_spread(put(35_000), put(40_000), ONE).defined_risk
    assert vertical_spread(call(55_000), call(50_000), ONE).defined_risk


@pytest.mark.unit
def test_a_short_leg_covered_by_a_smaller_long_quantity_is_undefined_risk() -> None:
    short = Leg(call(50_000), OrderSide.SELL, Decimal(3))
    cover = Leg(call(55_000), OrderSide.BUY, Decimal(2))

    assert not Combo("odd", (short, cover)).defined_risk


@pytest.mark.unit
def test_one_long_leg_covers_only_one_short_leg() -> None:
    inner = Leg(put(40_000), OrderSide.SELL, ONE)
    outer = Leg(put(38_000), OrderSide.SELL, ONE)
    cover = Leg(put(35_000), OrderSide.BUY, ONE)
    second = Leg(put(35_000), OrderSide.BUY, ONE)

    assert not Combo("odd", (inner, outer, cover)).defined_risk
    assert Combo("odd", (inner, outer, cover, second)).defined_risk


def entered(combo: Combo, *prices: str) -> Combo:
    return combo.priced(
        {
            leg.contract.id: Decimal(price)
            for leg, price in zip(combo.legs, prices, strict=True)
        }
    )


def condor() -> Combo:
    body = short_strangle(put(40_000), call(50_000), ONE)
    return iron_condor(body, put(35_000), call(55_000))


@pytest.mark.unit
def test_a_combos_credit_is_the_premium_it_took_in() -> None:
    strangle = short_strangle(put(40_000), call(50_000), Decimal(2))

    assert entered(strangle, "0.05", "0.04").credit == Decimal("0.18")
    assert entered(condor(), "0.05", "0.04", "0.01", "0.01").credit == Decimal("0.07")
    with pytest.raises(ValueError, match="entry prices"):
        _ = strangle.credit


@pytest.mark.unit
def test_a_debit_combo_has_a_negative_credit() -> None:
    spread = vertical_spread(put(35_000), put(40_000), ONE)

    assert entered(spread, "0.01", "0.05").credit == Decimal("-0.04")


def condor_quotes(combo: Combo) -> Callable[[CryptoOption], QuoteTick | None]:
    [short_put_, short_call, long_put, long_call] = (
        leg.contract.id for leg in combo.legs
    )
    return quotes(
        {
            short_put_: ("0.0250", "0.0300"),
            short_call: ("0.0150", "0.0200"),
            long_put: ("0.0050", "0.0080"),
            long_call: ("0.0050", "0.0080"),
        }
    )


@pytest.mark.unit
def test_a_combos_pl_percent_of_credit_follows_its_legs() -> None:
    held = entered(condor(), "0.05", "0.04", "0.01", "0.01")
    quote = condor_quotes(held)

    # closing buys the shorts at the ask and sells the longs at the bid
    assert held.pl(quote) == Decimal("0.03")
    assert held.pl_percent(quote) == pytest.approx(Decimal(300) / 7)


@pytest.mark.unit
def test_a_combos_pl_is_negative_when_closing_costs_more_than_the_credit() -> None:
    held = entered(short_put(put(40_000), ONE), "0.05")

    assert held.pl(quotes({held.legs[0].contract.id: ("0.1100", "0.1200")})) == Decimal(
        "-0.07"
    )
    assert held.pl_percent(
        quotes({held.legs[0].contract.id: ("0.1100", "0.1200")})
    ) == pytest.approx(Decimal(-140))


@pytest.mark.unit
def test_a_combo_without_a_quote_for_a_leg_has_no_pl() -> None:
    held = entered(short_put(put(40_000), ONE), "0.05")

    with pytest.raises(NoMarketError, match="BTC-40D-40000-P"):
        held.pl(quotes({}))


@pytest.mark.unit
def test_a_combos_dte_is_its_nearest_expiry() -> None:
    near, far = put(40_000, days=10), put(40_000, days=40)
    combo = Combo(
        "calendar", (Leg(far, OrderSide.BUY, ONE), Leg(near, OrderSide.SELL, ONE))
    )

    assert combo.dte(NOW) == 10
    assert combo.dte(NOW + timedelta(days=4, hours=12)) == 5.5


@pytest.mark.unit
def test_a_combo_exit_closes_at_a_dte_or_a_target_and_waits_for_a_quote() -> None:
    held = entered(short_put(put(40_000), ONE), "0.1000")
    quote = quotes({held.legs[0].contract.id: ("0.0400", "0.0500")})
    none = quotes({})

    assert ComboExit(profit_target=Decimal(50)).reached(held, NOW, quote)
    assert not ComboExit(profit_target=Decimal(60)).reached(held, NOW, quote)
    assert ComboExit(loss_target=Decimal(50)).reached(
        held, NOW, quotes({held.legs[0].contract.id: ("0.1500", "0.1600")})
    )
    assert not ComboExit(loss_target=Decimal(50)).reached(held, NOW, quote)
    assert ComboExit(dte=40).reached(held, NOW, none)
    assert not ComboExit(dte=39, profit_target=Decimal(1)).reached(held, NOW, none)
    assert not ComboExit().reached(held, NOW, quote)
