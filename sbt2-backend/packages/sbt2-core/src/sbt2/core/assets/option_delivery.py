from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_trader.model import CryptoOption, IndexPriceUpdate, InstrumentId

from sbt2.data import Catalog, Window

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class NoDeliveryPriceError(LookupError):
    pass


def expires_within(contract: CryptoOption, span: tuple[datetime, datetime]) -> bool:
    """Whether the contract expires after the start of ``span`` and by its end."""
    start, end = span
    return start < _expiry(contract) <= end


def delivery_id(contract: CryptoOption) -> InstrumentId:
    """The id of the series of delivery prices the contract settles at."""
    return InstrumentId.from_str(
        f"{contract.underlying.code}_USD_DELIVERY.{contract.id.venue.value}"
    )


def delivery_price(catalog: Catalog, contract: CryptoOption) -> Decimal:
    """The price the contract settles at: the last one of its expiry day, up to the
    expiry; ``NoDeliveryPriceError`` when the catalog has none."""
    expiry = _expiry(contract)
    day = expiry.date()
    prices = catalog.frame(
        delivery_id(contract), IndexPriceUpdate, Window.of_days(day, day)
    )["price"]
    known = prices.loc[:expiry]
    if known.empty:
        raise NoDeliveryPriceError(
            f"the catalog has no delivery price of {delivery_id(contract)} on {day}, "
            f"when {contract.id} expires"
        )
    return Decimal(str(known.iloc[-1]))


def _expiry(contract: CryptoOption) -> datetime:
    return _EPOCH + timedelta(microseconds=contract.expiration_ns // 1_000)
