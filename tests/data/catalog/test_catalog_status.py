from datetime import timedelta
from pathlib import Path

import pytest
from local_catalog import DAY, LocalCatalog, days, gap
from local_source import INSTRUMENT_ID
from nautilus_trader.model import Bar, FundingRateUpdate, TradeTick

from sbt2.data import Catalog, Holding

DAY_2 = DAY + timedelta(days=1)
DAY_3 = DAY + timedelta(days=2)
DAY_4 = DAY + timedelta(days=3)
DAY_5 = DAY + timedelta(days=4)


@pytest.fixture
def local(tmp_path: Path) -> LocalCatalog:
    return LocalCatalog(tmp_path)


@pytest.mark.unit
def test_status_lists_each_instrument_and_data_type(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY, DAY_2)
    local.add(FundingRateUpdate, DAY_2)

    holdings = Catalog(local.path).status(frozenset())

    assert sorted(holdings, key=lambda each: each.data_type.__name__) == [
        Holding(INSTRUMENT_ID, FundingRateUpdate, DAY_2, DAY_2, 1, (), ()),
        Holding(INSTRUMENT_ID, TradeTick, DAY, DAY_2, 2, (), ()),
    ]


@pytest.mark.unit
def test_gaps_are_holes_between_the_first_and_last_day(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY, DAY_2, DAY_5)

    (holding,) = Catalog(local.path).status(frozenset())

    assert (holding.first, holding.last, holding.days) == (DAY, DAY_5, 3)
    assert holding.gaps == (DAY_3, DAY_4)


@pytest.mark.unit
def test_a_window_checks_every_day_in_it(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY_2, DAY_3)

    (holding,) = Catalog(local.path).status(frozenset(), days(DAY, DAY_4))

    assert holding.gaps == (DAY, DAY_4)


@pytest.mark.unit
def test_known_gaps_are_not_counted_as_gaps(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY, DAY_3)

    (holding,) = Catalog(local.path).status(frozenset({gap(TradeTick, DAY_2)}))

    assert (holding.gaps, holding.known_gaps) == ((), (DAY_2,))


@pytest.mark.unit
def test_an_empty_catalog_has_no_holdings(tmp_path: Path) -> None:
    assert Catalog(tmp_path / "nothing").status(frozenset()) == ()


@pytest.mark.unit
def test_a_data_type_whose_files_were_removed_is_not_listed(
    local: LocalCatalog,
) -> None:
    local.add(TradeTick, DAY)
    local.add(FundingRateUpdate, DAY)

    local.reingest("0.02", TradeTick, DAY)

    holdings = Catalog(local.path).status(frozenset())
    assert [each.data_type for each in holdings] == [TradeTick]


@pytest.mark.unit
def test_status_lists_candles_under_their_instrument(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY)
    local.add(Bar, DAY, DAY_3)

    holdings = Catalog(local.path).status(frozenset())

    assert Holding(INSTRUMENT_ID, Bar, DAY, DAY_3, 2, (DAY_2,), ()) in holdings
    assert len(holdings) == 2
