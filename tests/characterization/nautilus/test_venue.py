from decimal import Decimal

import pytest
from kit import (
    HOUR,
    INSTRUMENT_ID,
    START,
    STARTING_BALANCE,
    VENUE,
    mark,
    quiet_engine_config,
    quote,
    run_long_one_btc,
    usdt,
)
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.model import AccountType, Money, OmsType
from nautilus_trader.portfolio import PortfolioConfig

MARK_ABOVE_QUOTES = [
    quote(START),
    mark(START),
    quote(START + HOUR, "52000.0"),
    mark(START + HOUR, "51000.0"),
]


@pytest.mark.characterization
@pytest.mark.unit
def test_venue_without_fee_model_is_refused() -> None:
    engine = BacktestEngine(quiet_engine_config())

    with pytest.raises(ValueError, match="explicit fee_model"):
        engine.add_venue(
            VENUE,
            OmsType.NETTING,
            AccountType.MARGIN,
            [Money.from_str(STARTING_BALANCE)],
            default_leverage=Decimal(10),
        )


@pytest.mark.characterization
@pytest.mark.integration
@pytest.mark.parametrize(
    "portfolio",
    [None, PortfolioConfig(use_mark_prices=True)],
    ids=["default", "use_mark_prices"],
)
def test_open_position_is_valued_at_mark_price(
    portfolio: PortfolioConfig | None,
) -> None:
    engine = run_long_one_btc(MARK_ABOVE_QUOTES, portfolio)

    assert engine.portfolio.unrealized_pnl(INSTRUMENT_ID) == usdt("1000.00")


@pytest.mark.characterization
@pytest.mark.integration
def test_open_position_is_valued_at_quotes_without_mark_prices() -> None:
    engine = run_long_one_btc(MARK_ABOVE_QUOTES, PortfolioConfig(use_mark_prices=False))

    assert engine.portfolio.unrealized_pnl(INSTRUMENT_ID) == usdt("2000.00")
