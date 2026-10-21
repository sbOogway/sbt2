from decimal import Decimal

import pytest
from dated_catalog import EXPIRY, future, spot
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    CryptoOption,
    CryptoPerpetual,
    Currency,
    InstrumentId,
    OptionKind,
    Price,
    Quantity,
    Symbol,
)

from sbt2.core.strategy.expiry import settlement_time


def option() -> CryptoOption:
    btc = Currency.from_str("BTC")
    return CryptoOption(
        InstrumentId.from_str("BTC-2JAN24-50000-C.DERIBIT"),
        Symbol("BTC-2JAN24-50000-C"),
        btc,
        Currency.from_str("USD"),
        btc,
        True,
        OptionKind.CALL,
        Price.from_str("50000"),
        0,
        dt_to_unix_nanos(EXPIRY),
        4,
        1,
        Price.from_str("0.0001"),
        Quantity.from_str("0.1"),
        0,
        0,
    )


def perpetual() -> CryptoPerpetual:
    btc = Currency.from_str("BTC")
    return CryptoPerpetual(
        InstrumentId.from_str("BTC-PERPETUAL.DERIBIT"),
        Symbol("BTC-PERPETUAL"),
        btc,
        Currency.from_str("USD"),
        btc,
        True,
        1,
        0,
        Price.from_str("0.5"),
        Quantity.from_str("10"),
        0,
        0,
        margin_init=Decimal("0.02"),
        margin_maint=Decimal("0.0133"),
    )


@pytest.mark.unit
def test_future_settlement_time() -> None:
    before_expiry = dt_to_unix_nanos(EXPIRY) - 1

    assert settlement_time(future()) == before_expiry
    assert settlement_time(option()) == before_expiry
    assert settlement_time(perpetual()) is None
    assert settlement_time(spot()) is None
