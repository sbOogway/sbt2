from datetime import UTC, datetime, timedelta

import pytest
from chain_kit import chain_of, clock, ns
from nautilus_trader.model import CryptoOption, InstrumentId, OptionKind
from option_catalog import Terms, listed_option

from sbt2.core.strategy import CachedChain, ChainRecords

NOW = datetime(2024, 1, 2, tzinfo=UTC)
DAYS = (10, 40, 75)
STRIKES = (40_000, 45_000, 50_000)
INDEX = 45_000.0
IV = 0.6
LETTER = {OptionKind.CALL: "C", OptionKind.PUT: "P"}


def expiry_in(days: int) -> datetime:
    return NOW + timedelta(days=days)


def contract(days: int, strike: int, kind: OptionKind) -> CryptoOption:
    name = f"BTC-{days}D-{strike}-{LETTER[kind]}.DERIBIT"
    terms = Terms(kind, expiry_in(days), str(strike))
    return listed_option(InstrumentId.from_str(name), terms)


def listing() -> list[CryptoOption]:
    return [
        contract(days, strike, kind)
        for days in DAYS
        for strike in STRIKES
        for kind in (OptionKind.CALL, OptionKind.PUT)
    ]


def heard(contracts: list[CryptoOption]) -> ChainRecords:
    records = ChainRecords(clock(NOW))
    records.hear_index(ns(NOW), INDEX)
    for each in contracts:
        records.hear_iv(each.id, ns(NOW), IV)
    return records


def chain(unquoted: tuple[InstrumentId, ...] = ()) -> CachedChain:
    contracts = listing()
    return chain_of(heard(contracts), *contracts, unquoted=unquoted)


def picked(found: CryptoOption | None) -> tuple[int, str]:
    assert found is not None
    return int(found.strike_price), found.option_kind.name


# by hand, at 40 days to expiry, an IV of 0.6 and an index of 45000: the deltas of
# the 40000, 45000 and 50000 calls are 0.756, 0.540 and 0.333, those of the puts
# are those minus 1
@pytest.mark.unit
@pytest.mark.parametrize(
    ("delta", "strike", "kind"),
    [
        (0.30, 50_000, "CALL"),
        (0.50, 45_000, "CALL"),
        (0.80, 40_000, "CALL"),
        (-0.25, 40_000, "PUT"),
        (-0.50, 45_000, "PUT"),
        (-0.70, 50_000, "PUT"),
    ],
)
def test_the_nearest_delta_contract_of_an_expiry_is_picked_for_calls_and_puts(
    delta: float, strike: int, kind: str
) -> None:
    found = chain().nearest_delta(expiry_in(40), delta)

    assert picked(found) == (strike, kind)
    assert found is not None
    assert found.expiration_ns == ns(expiry_in(40))


@pytest.mark.unit
def test_the_nearest_delta_search_skips_contracts_without_a_quote() -> None:
    unquoted = (contract(40, 45_000, OptionKind.CALL).id,)

    found = chain(unquoted).nearest_delta(expiry_in(40), 0.5)

    assert picked(found) == (50_000, "CALL")


@pytest.mark.unit
def test_the_nearest_delta_search_skips_contracts_without_an_iv() -> None:
    contracts = listing()
    records = ChainRecords(clock(NOW))
    records.hear_index(ns(NOW), INDEX)
    for each in contracts:
        if each.id != contract(40, 45_000, OptionKind.CALL).id:
            records.hear_iv(each.id, ns(NOW), IV)

    found = chain_of(records, *contracts).nearest_delta(expiry_in(40), 0.5)

    assert picked(found) == (50_000, "CALL")


@pytest.mark.unit
def test_the_nearest_delta_search_gives_nothing_for_an_expiry_without_contracts() -> (
    None
):
    assert chain().nearest_delta(expiry_in(41), 0.5) is None


@pytest.mark.unit
def test_a_target_delta_of_zero_is_refused() -> None:
    with pytest.raises(ValueError, match="above 0 for a call and below 0 for a put"):
        chain().nearest_delta(expiry_in(40), 0.0)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("dte", "days"),
    [
        (5, 10),
        (45, 40),
        (60, 75),
        (200, 75),
        (25, 10),
    ],
)
def test_the_expiry_nearest_a_target_dte_is_picked(dte: float, days: int) -> None:
    assert chain().nearest_expiry(dte) == expiry_in(days)


@pytest.mark.unit
def test_the_expiry_search_gives_nothing_on_an_empty_chain() -> None:
    assert chain_of(ChainRecords(clock(NOW))).nearest_expiry(45) is None
