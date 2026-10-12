from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from math import erf, exp, pi, sqrt

import pytest
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import CryptoOption, InstrumentId, OptionKind, QuoteTick
from option_catalog import Terms, listed_option

from sbt2.core.strategy import CachedChain, ChainRecords, NoMarketError

NOW = datetime(2024, 1, 2, tzinfo=UTC)
EXPIRY = NOW + timedelta(days=73)
YEARS = 73 / 365
STRIKE = 45_000
INDEX = 45_000.0
IV = 0.6
CALL_ID = InstrumentId.from_str("BTC-15MAR24-45000-C.DERIBIT")
PUT_ID = InstrumentId.from_str("BTC-15MAR24-45000-P.DERIBIT")


def ns(moment: datetime) -> int:
    return dt_to_unix_nanos(moment)


def contract(instrument_id: InstrumentId, kind: OptionKind) -> CryptoOption:
    return listed_option(instrument_id, Terms(kind, EXPIRY, str(STRIKE)))


class FakeCache:
    def __init__(self, contracts: tuple[CryptoOption, ...]) -> None:
        self._contracts = {each.id: each for each in contracts}

    def instrument(self, instrument_id: InstrumentId, /) -> CryptoOption | None:
        return self._contracts.get(instrument_id)

    def quote(self, _instrument_id: InstrumentId, /) -> QuoteTick | None:
        return None


def chain_of(records: ChainRecords, *contracts: CryptoOption) -> CachedChain:
    return CachedChain(FakeCache(contracts), [each.id for each in contracts], records)


def cdf(x: float) -> float:
    return (1 + erf(x / sqrt(2))) / 2


def pdf(x: float) -> float:
    return exp(-(x**2) / 2) / sqrt(2 * pi)


def d1() -> float:
    spread = IV * sqrt(YEARS)
    return (0.5 * IV**2 * YEARS) / spread


def clock(moment: datetime) -> Callable[[], int]:
    return lambda: ns(moment)


@pytest.fixture
def records() -> ChainRecords:
    heard = ChainRecords(clock(NOW))
    heard.hear_iv(CALL_ID, ns(NOW) - 10, IV)
    heard.hear_iv(PUT_ID, ns(NOW) - 10, IV)
    heard.hear_index(ns(NOW) - 10, INDEX)
    return heard


@pytest.mark.unit
def test_a_contracts_iv_is_its_latest_deribit_iv(records: ChainRecords) -> None:
    call = contract(CALL_ID, OptionKind.CALL)
    records.hear_iv(CALL_ID, ns(NOW) - 5, 0.55)
    records.hear_iv(CALL_ID, ns(NOW), 0.52)

    assert chain_of(records, call).iv(call) == 0.52


@pytest.mark.unit
def test_a_contract_with_no_iv_yet_is_refused() -> None:
    call = contract(CALL_ID, OptionKind.CALL)

    with pytest.raises(NoMarketError, match=r"BTC-15MAR24-45000-C\.DERIBIT.*IV"):
        chain_of(ChainRecords(clock(NOW)), call).iv(call)


@pytest.mark.unit
def test_a_contracts_greeks_follow_black_scholes_on_the_current_index(
    records: ChainRecords,
) -> None:
    call, put = contract(CALL_ID, OptionKind.CALL), contract(PUT_ID, OptionKind.PUT)
    chain = chain_of(records, call, put)
    x = d1()
    gamma = pdf(x) / (INDEX * IV * sqrt(YEARS))
    vega = INDEX * pdf(x) * sqrt(YEARS) / 100
    # nautilus turns the yearly theta into a daily one over 365.25 days
    theta = -INDEX * pdf(x) * IV / (2 * sqrt(YEARS)) / 365.25

    for each, delta in ((call, cdf(x)), (put, cdf(x) - 1)):
        greeks = chain.greeks(each)
        assert greeks.delta == pytest.approx(delta)
        assert greeks.gamma == pytest.approx(gamma)
        assert greeks.vega == pytest.approx(vega)
        assert greeks.theta == pytest.approx(theta)


@pytest.mark.unit
def test_the_greeks_move_with_the_index_the_chain_heard_last(
    records: ChainRecords,
) -> None:
    call = contract(CALL_ID, OptionKind.CALL)
    records.hear_index(ns(NOW), 50_000.0)
    chain = chain_of(records, call)

    assert chain.greeks(call).delta > 0.6


@pytest.mark.unit
def test_greeks_without_an_index_price_are_refused() -> None:
    call = contract(CALL_ID, OptionKind.CALL)
    records = ChainRecords(clock(NOW))
    records.hear_iv(CALL_ID, ns(NOW), IV)

    with pytest.raises(NoMarketError, match="index"):
        chain_of(records, call).greeks(call)


@pytest.mark.unit
def test_the_iv_and_greeks_never_look_ahead(records: ChainRecords) -> None:
    call = contract(CALL_ID, OptionKind.CALL)
    asked = chain_of(records, call)
    before = asked.greeks(call)
    records.hear_iv(CALL_ID, ns(NOW) + 1, 0.9)
    records.hear_index(ns(NOW) + 1, 30_000.0)

    assert asked.iv(call) == IV
    assert asked.greeks(call) == before
