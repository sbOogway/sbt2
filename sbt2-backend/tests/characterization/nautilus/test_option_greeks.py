import pytest
from nautilus_trader.model import black_scholes_greeks, imply_vol

UNDERLYING = 45000.0
STRIKE = 50000.0
YEARS = 0.1
VOL = 0.6


def call_price_in_usd() -> float:
    return black_scholes_greeks(UNDERLYING, 0.0, 0.0, VOL, True, STRIKE, YEARS).price


@pytest.mark.characterization
@pytest.mark.unit
def test_black_scholes_prices_an_option_in_the_quote_currency() -> None:
    price = call_price_in_usd()

    # by hand: d1 = -0.4604, d2 = -0.6502, so 45000 N(d1) - 50000 N(d2);
    # Deribit quotes the same option in BTC, the USD price over the underlying
    assert price == pytest.approx(1627.56, abs=0.01)
    assert price / UNDERLYING == pytest.approx(0.036168, abs=1e-6)


@pytest.mark.characterization
@pytest.mark.unit
def test_imply_vol_needs_the_price_in_the_quote_currency() -> None:
    usd = call_price_in_usd()

    from_usd = imply_vol(UNDERLYING, 0.0, 0.0, True, STRIKE, YEARS, usd)
    from_btc = imply_vol(UNDERLYING, 0.0, 0.0, True, STRIKE, YEARS, usd / UNDERLYING)

    assert from_usd == pytest.approx(VOL, abs=1e-6)
    assert from_btc < VOL / 2
