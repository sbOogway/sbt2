from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, override

import pytest
from dated_catalog import EXPIRY, START, future
from nautilus_trader.execution import FeeModel
from nautilus_trader.model import (
    AssetClass,
    IndexPriceUpdate,
    InstrumentClass,
    InstrumentId,
    LiquiditySide,
    Money,
    Price,
    Quantity,
)

from sbt2.core.assets import asset_profile
from sbt2.core.strategy import SETTLEMENT_TAG
from sbt2.data import Selection, Window

FUTURE = asset_profile(AssetClass.CRYPTOCURRENCY, InstrumentClass.FUTURE)
DELIVERY = Price.from_str("51234.5")
QUANTITY = Quantity.from_int(10_000)


class Rates(FeeModel):
    """A maker rate of 1 and a taker rate of 2 coins per contract."""

    @override
    def get_commission(
        self, order: Any, fill_quantity: Quantity, fill_px: Price, instrument: Any
    ) -> Money:
        rate = 1 if order.liquidity_side == LiquiditySide.MAKER else 2
        return Money(rate * fill_quantity.as_double(), instrument.settlement_currency)


def fee_model(inner: Any, delivery_fee: dict[str, Any] | None = None) -> Any:
    venue = {} if delivery_fee is None else {"delivery_fee": delivery_fee}
    completed = FUTURE.settlement.complete(venue)
    return FUTURE.settlement.fee_model(inner, completed, SETTLEMENT_TAG)


def order(*tags: str, side: LiquiditySide = LiquiditySide.TAKER) -> SimpleNamespace:
    return SimpleNamespace(tags=list(tags), liquidity_side=side)


@pytest.mark.unit
def test_future_delivery_selections() -> None:
    instruments = [
        future("BTC", EXPIRY),
        future("BTC", EXPIRY - timedelta(hours=1)),
        future("ETH", EXPIRY),
        future("BTC", START),
        future("ETH", EXPIRY + timedelta(days=1)),
    ]

    selections = FUTURE.settlement.delivery_selections(instruments, (START, EXPIRY))

    day = Window.of_days(EXPIRY.date(), EXPIRY.date())
    assert selections == [
        Selection(
            (InstrumentId.from_str(f"{coin}_USD_DELIVERY.DERIBIT"),),
            (IndexPriceUpdate,),
            day,
        )
        for coin in ("BTC", "ETH")
    ]


@pytest.mark.unit
@pytest.mark.parametrize("coin", ["BTC", "ETH"])
def test_future_delivery_fee_uses_inverse_notional(coin: str) -> None:
    contract = future(coin)
    settled = order(SETTLEMENT_TAG)

    fee = fee_model(None).get_commission(settled, QUANTITY, DELIVERY, contract)
    free = fee_model(None, {"rate": "0"}).get_commission(
        settled, QUANTITY, DELIVERY, contract
    )

    expected = Decimal(10_000) / Decimal("51234.5") * Decimal("0.00025")
    assert fee == Money(float(expected), contract.settlement_currency)
    assert free == Money.zero(contract.settlement_currency)


@pytest.mark.unit
def test_future_regular_fills_use_configured_fees() -> None:
    contract = future()
    model = fee_model(Rates())

    maker = model.get_commission(
        order(side=LiquiditySide.MAKER), QUANTITY, DELIVERY, contract
    )
    taker = model.get_commission_with_context(
        order("ENTRY"), QUANTITY, DELIVERY, contract
    )

    assert maker == Money(10_000, contract.settlement_currency)
    assert taker == Money(20_000, contract.settlement_currency)
