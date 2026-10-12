from pathlib import Path

import pytest
from local_catalog import DAY, LocalCatalog
from local_source import INSTRUMENT_ID, perpetual
from nautilus_trader.model import CryptoPerpetual, InstrumentId, TradeTick

from sbt2.data import Catalog


@pytest.mark.unit
def test_instruments_are_returned_by_id(tmp_path: Path) -> None:
    local = LocalCatalog(tmp_path)
    local.add(TradeTick, DAY)

    found = Catalog(local.path).instruments((INSTRUMENT_ID,))

    instrument = found[INSTRUMENT_ID]
    assert isinstance(instrument, CryptoPerpetual)
    assert instrument.margin_init == perpetual().margin_init
    assert instrument.price_precision == perpetual().price_precision


@pytest.mark.unit
def test_an_unknown_id_is_absent_from_the_result(tmp_path: Path) -> None:
    local = LocalCatalog(tmp_path)
    local.add(TradeTick, DAY)
    unknown = InstrumentId.from_str("ETHUSDT-PERP.LOCAL")

    found = Catalog(local.path).instruments((INSTRUMENT_ID, unknown))

    assert list(found) == [INSTRUMENT_ID]


@pytest.mark.unit
def test_the_catalog_lists_the_ids_of_its_instruments(tmp_path: Path) -> None:
    local = LocalCatalog(tmp_path)
    local.add(TradeTick, DAY)

    assert Catalog(local.path).instrument_ids() == (INSTRUMENT_ID,)


@pytest.mark.unit
def test_a_catalog_without_instruments_lists_none(tmp_path: Path) -> None:
    assert Catalog(tmp_path / "catalog").instrument_ids() == ()
