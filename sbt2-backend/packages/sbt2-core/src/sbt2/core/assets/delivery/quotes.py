from decimal import ROUND_HALF_EVEN, Decimal

from nautilus_trader.model import Price, Quantity, QuoteTick

from sbt2.core.assets.delivery.prices import Expiring
from sbt2.core.assets.option.quotes.quotes import QUOTE_SIZE

# The strategy settles its position one nanosecond before the expiry, as nautilus
# rejects the orders of an expired contract; the quote of the settlement price comes
# before that. Nautilus fires a timer only when the next data arrives, so a second
# quote at the expiry itself makes sure it fires.
_SETTLEMENT_NS_BEFORE_EXPIRY = 2


def settlement_quotes(contract: Expiring, price: Decimal) -> list[QuoteTick]:
    """The last quotes of the contract: ``price`` to the tick as bid and ask just
    before the expiry, and again at the expiry. A market order then fills at the
    settlement price."""
    tick = Decimal(str(contract.price_increment))
    ticks = (price / tick).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
    settled = Price(float(ticks * tick), contract.price_precision)
    size = Quantity(QUOTE_SIZE, contract.size_precision)
    expiry = contract.expiration_ns
    return [
        QuoteTick(contract.id, settled, settled, size, size, ts, ts)
        for ts in (expiry - _SETTLEMENT_NS_BEFORE_EXPIRY, expiry)
    ]
