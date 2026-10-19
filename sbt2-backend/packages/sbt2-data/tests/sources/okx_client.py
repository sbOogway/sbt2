"""OKX with a stand-in for the nautilus client."""

from nautilus_stubs import OkxClientStub, load_sample, synthetic_day
from nautilus_trader.model import BarType

from sbt2.data.sources.okx import OkxSource

BTC_SWAP_BARS = BarType.from_str("BTC-USDT-SWAP.OKX-1-MINUTE-LAST-EXTERNAL")


def okx_stub() -> OkxClientStub:
    """A client that lists the BTC and ETH swaps and holds a day of the BTC one."""
    sample = load_sample("okx_nautilus_sample.json")
    listed = {each["raw_symbol"]: each for each in sample["instruments"]}
    return OkxClientStub(synthetic_day(BTC_SWAP_BARS, 2), listed)


def okx_stubbed() -> OkxSource:
    """OKX, served by the stand-in client."""
    return OkxSource(frozenset(), okx_stub())
