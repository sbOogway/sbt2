from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from nautilus_trader.model import (
    CryptoOption,
    Currency,
    InstrumentId,
    Money,
    OptionKind,
)
from option_catalog import ETH, START, Terms, listed_option

from sbt2.core.strategy import NoMarketError, short_strangle
from sbt2.core.strategy.book_rules import BookRules
from sbt2.core.strategy.conversion import Conversion
from sbt2.core.strategy.short_premium import ShortPremiumRules

BTC_PUT = listed_option(
    InstrumentId.from_str("BTC-12JAN24-40000-P.DERIBIT"),
    Terms(OptionKind.PUT, START.replace(day=12), "40000"),
)
BTC_CALL = listed_option(
    InstrumentId.from_str("BTC-12JAN24-50000-C.DERIBIT"),
    Terms(OptionKind.CALL, START.replace(day=12), "50000"),
)
ETH_PUT = listed_option(
    InstrumentId.from_str("ETH-12JAN24-2000-P.DERIBIT"),
    Terms(OptionKind.PUT, START.replace(day=12), "2000", ETH),
)
PRICES = {"BTC": 40_000.0, "ETH": 2_000.0}


def strategy(balances: dict[str, str], held: dict[CryptoOption, str]) -> Any:
    """A strategy of a BTC strangle to open, holding ETH puts."""
    account = SimpleNamespace(
        balances_total=lambda: {
            Currency.from_str(code): Money.from_str(f"{amount} {code}")
            for code, amount in balances.items()
        }
    )
    margins = {contract.id: Decimal(each) for contract, each in held.items()}
    return SimpleNamespace(
        portfolio=SimpleNamespace(account=lambda _venue: account),
        cache=SimpleNamespace(
            instrument=lambda instrument_id: next(
                each for each in held if each.id == instrument_id
            )
        ),
        margin_of_positions=lambda: margins,
        margin_of_combo=lambda _combo: Decimal("0.09"),
        combos=(),
        chains={"BTC": SimpleNamespace(iv_rank=_no_rank)},
    )


def _no_rank() -> float:
    raise NoMarketError("no DVOL")


def rules_for(held_strategy: Any, prices: dict[str, float] | None = None) -> BookRules:
    conversion = Conversion(lambda: PRICES if prices is None else prices)
    return BookRules(ShortPremiumRules(), held_strategy, conversion)


STRANGLE = short_strangle(BTC_PUT, BTC_CALL, Decimal(1))


@pytest.mark.unit
def test_the_rules_weigh_a_combo_against_the_converted_portfolio_totals() -> None:
    # equity: 1 BTC + 10 ETH = 1.5 BTC; the ETH put holds 0.2 ETH = 0.01 BTC
    held = strategy({"BTC": "1.0", "ETH": "10.0"}, {ETH_PUT: "0.2"})

    # a BTC-only equity of 1 BTC would cap the combo at 0.07, below its 0.09
    assert rules_for(held).refusal(STRANGLE) is None


@pytest.mark.unit
def test_the_bpr_of_other_coins_counts_in_the_currency_of_the_combo() -> None:
    # the ETH put holds 8 ETH = 0.4 BTC; with the combo's 0.09 that is 0.49,
    # above the 0.25 allocation of the 1.5 BTC equity
    held = strategy({"BTC": "1.0", "ETH": "10.0"}, {ETH_PUT: "8.0"})

    reason = rules_for(held).refusal(STRANGLE)

    assert reason is not None
    assert reason.startswith("allocation")
    assert "would be 0.49" in reason


@pytest.mark.unit
def test_a_missing_index_price_leaves_the_combo_unpriced() -> None:
    held = strategy({"BTC": "1.0", "ETH": "10.0"}, {ETH_PUT: "0.2"})

    reason = rules_for(held, {"BTC": 40_000.0}).refusal(STRANGLE)

    assert reason is not None
    assert reason.startswith("the BPR of the combo cannot be priced")
