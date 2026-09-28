import re
from datetime import timedelta
from pathlib import Path

import pytest
from local_catalog import DAY, LocalCatalog, days
from local_source import INSTRUMENT_ID
from nautilus_trader.model import MarkPriceUpdate, TradeTick

from sbt2.data import Catalog, Selection

DAY_2 = DAY + timedelta(days=1)
DAY_3 = DAY + timedelta(days=2)
TRADES = Selection((INSTRUMENT_ID,), (TradeTick,), days(DAY, DAY_2))


@pytest.fixture
def local(tmp_path: Path) -> LocalCatalog:
    local = LocalCatalog(tmp_path / "one")
    local.add(TradeTick, DAY, DAY_2)
    return local


def fingerprint(local: LocalCatalog) -> str:
    return Catalog(local.path).fingerprint(TRADES)


def test_the_same_catalog_gives_the_same_fingerprint(
    local: LocalCatalog, tmp_path: Path
) -> None:
    other = LocalCatalog(tmp_path / "other")
    other.add(TradeTick, DAY, DAY_2)

    assert fingerprint(local) == fingerprint(other)
    assert re.fullmatch("[0-9a-f]{64}", fingerprint(local))


def test_a_changed_file_in_the_window_changes_it(local: LocalCatalog) -> None:
    before = fingerprint(local)

    local.rewrite(TradeTick, DAY_2, rows=5)

    assert fingerprint(local) != before


def test_files_outside_the_window_do_not_change_it(local: LocalCatalog) -> None:
    before = fingerprint(local)

    local.add(TradeTick, DAY_3)

    assert fingerprint(local) == before


def test_unselected_data_types_do_not_change_it(local: LocalCatalog) -> None:
    before = fingerprint(local)

    local.add(MarkPriceUpdate, DAY, DAY_2)

    assert fingerprint(local) == before


def test_a_replaced_instrument_changes_it(local: LocalCatalog) -> None:
    before = fingerprint(local)

    local.reingest("0.02", TradeTick, DAY, DAY_2)

    assert fingerprint(local) != before
