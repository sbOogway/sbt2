from datetime import date, timedelta
from pathlib import Path

import pytest
from local_catalog import DAY, LocalCatalog, days, gap, midnight
from local_source import INSTRUMENT_ID
from nautilus_trader.model import MarkPriceUpdate, TradeTick

from sbt2.data import Catalog, Coverage, Selection, Window

DAY_2 = DAY + timedelta(days=1)
DAY_3 = DAY + timedelta(days=2)


@pytest.fixture
def local(tmp_path: Path) -> LocalCatalog:
    return LocalCatalog(tmp_path)


def trades_coverage(local: LocalCatalog, window: Window, *gaps: date) -> Coverage:
    selection = Selection((INSTRUMENT_ID,), (TradeTick,), window)
    known = frozenset(gap(TradeTick, each) for each in gaps)
    (coverage,) = Catalog(local.path).coverage(selection, known)
    return coverage


def test_a_fully_covered_window_has_no_missing_days(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY, DAY_2, DAY_3)

    coverage = trades_coverage(local, days(DAY, DAY_3))

    assert coverage == Coverage(INSTRUMENT_ID, TradeTick, (), ())


def test_a_missing_day_inside_the_window_is_reported(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY, DAY_3)

    assert trades_coverage(local, days(DAY, DAY_3)).missing == (DAY_2,)


def test_days_outside_the_catalog_are_missing(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY_2)

    assert trades_coverage(local, days(DAY, DAY_3)).missing == (DAY, DAY_3)


def test_a_partial_day_window_needs_only_the_days_it_touches(
    local: LocalCatalog,
) -> None:
    local.add(TradeTick, DAY_2)
    morning = midnight(DAY_2) + timedelta(hours=6)

    within_the_day = Window(morning, morning + timedelta(hours=12))
    to_midnight = Window(morning, midnight(DAY_3))

    assert trades_coverage(local, within_the_day).missing == ()
    assert trades_coverage(local, to_midnight).missing == ()


def test_known_gap_days_are_returned_separately(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY, DAY_3)

    coverage = trades_coverage(local, days(DAY, DAY_3), DAY_2)

    assert (coverage.missing, coverage.known_gaps) == ((), (DAY_2,))


def test_a_known_gap_for_another_type_is_still_missing(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY, DAY_3)
    selection = Selection((INSTRUMENT_ID,), (TradeTick,), days(DAY, DAY_3))
    known = frozenset({gap(MarkPriceUpdate, DAY_2)})

    (coverage,) = Catalog(local.path).coverage(selection, known)

    assert (coverage.missing, coverage.known_gaps) == ((DAY_2,), ())


def test_coverage_is_given_per_instrument_and_data_type(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY, DAY_2)
    local.add(MarkPriceUpdate, DAY_2, DAY_3)
    selection = Selection(
        (INSTRUMENT_ID,), (TradeTick, MarkPriceUpdate), days(DAY, DAY_3)
    )

    coverages = Catalog(local.path).coverage(selection)

    assert coverages == (
        Coverage(INSTRUMENT_ID, TradeTick, (DAY_3,), ()),
        Coverage(INSTRUMENT_ID, MarkPriceUpdate, (DAY,), ()),
    )


def test_an_empty_day_counts_as_covered(local: LocalCatalog) -> None:
    local.add(TradeTick, DAY, rows=0)

    assert trades_coverage(local, days(DAY, DAY)).missing == ()
