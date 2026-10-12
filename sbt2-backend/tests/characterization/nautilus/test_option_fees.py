from decimal import Decimal

import pytest
from nautilus_trader.execution import CappedOptionFeeModel
from nautilus_trader.model import OrderSide
from option_kit import Market, btc, run_orders, trade

# Deribit's option fee: 0.03 % of the underlying per contract, capped at
# 12.5 % of the option price
DERIBIT_FEES = Market(
    fee_model=CappedOptionFeeModel(
        Decimal("0.0003"), Decimal("0.0003"), Decimal("0.125")
    )
)


@pytest.mark.characterization
@pytest.mark.integration
@pytest.mark.parametrize(
    ("price", "commission"),
    [("0.0500", "0.0003"), ("0.0020", "0.00025")],
    ids=["rate of the underlying", "cap on the price"],
)
def test_the_capped_option_fee_model_charges_deribits_option_fee(
    price: str, commission: str
) -> None:
    data = [trade(0, price), trade(5, price)]

    _, record = run_orders(data, {2: (OrderSide.BUY, "1.0")}, DERIBIT_FEES)

    assert record.commissions == [btc(commission)]
