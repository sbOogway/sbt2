import pytest
from nautilus_trader.model import InstrumentClose, InstrumentCloseType, OrderSide, Price
from option_kit import CALL_ID, EXPIRY, EXPIRY_HOUR, btc, run_orders, trade

BUY = (OrderSide.BUY, "1.0")
SELL = (OrderSide.SELL, "1.0")


def expired_close(price: str) -> InstrumentClose:
    return InstrumentClose(
        CALL_ID,
        Price.from_str(price),
        InstrumentCloseType.CONTRACT_EXPIRED,
        EXPIRY,
        EXPIRY,
    )


@pytest.mark.characterization
@pytest.mark.integration
def test_a_position_stays_open_after_its_contract_expires() -> None:
    data = [trade(0, "0.0500"), trade(EXPIRY_HOUR + 12, "0.0100")]

    engine, _ = run_orders(data, {2: BUY})

    [position] = engine.cache.positions()
    assert position.is_open


@pytest.mark.characterization
@pytest.mark.integration
def test_a_contract_expired_close_does_not_settle_the_position() -> None:
    data = [
        trade(0, "0.0500"),
        expired_close("0.0200"),
        trade(EXPIRY_HOUR + 12, "0.0100"),
    ]

    engine, _ = run_orders(data, {2: BUY})

    [position] = engine.cache.positions()
    assert position.is_open
    assert position.realized_pnl == btc("0")


@pytest.mark.characterization
@pytest.mark.integration
def test_an_order_after_expiry_is_rejected_as_pending_resolution() -> None:
    data = [trade(0, "0.0500"), trade(EXPIRY_HOUR + 12, "0.0100")]

    _, record = run_orders(data, {2: BUY, EXPIRY_HOUR + 7: SELL})

    assert len(record.fills) == 1
    assert record.rejections == [
        f"Contract {CALL_ID} has expired and is pending resolution"
    ]
