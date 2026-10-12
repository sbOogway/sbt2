import json
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import override

import pytest
from nautilus_trader.model import IndexPriceUpdate
from option_catalog import DELIVERY_ID, build_expiring_catalog

from sbt2.core.run import DataFolders, MissingDataError, preflight
from sbt2.core.spec import ResolvedRunSpec, load
from sbt2.data import Catalog, Window
from sbt2.data.sources import MissingAtSourceError, RawFile
from sbt2.data.sources.deribit import DeribitSource

SPEC = """
strategy = "run_strategies:BuyOneOption"
instruments = ["BTC-2JAN24-50000-C.DERIBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
venue = "deribit_option"
capital = "1 BTC"
"""
VENUES = """
[deribit_option]
name = "DERIBIT"
source = "deribit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "OPTION"
fee_model = { kind = "capped_option", config = { maker_rate = "0.0003", taker_rate = "0.0003", cap_rate = "0.125" } }
"""
EXPIRY_DAY = date(2024, 1, 2)
DELIVERY = 62_500.0


class DeliverySource(DeribitSource):
    """Deribit's source serving the delivery price of one day from memory."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[PurePosixPath] = []

    @override
    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        async def fetch() -> bytes:
            self.asked.append(path)
            row = {"date": day.isoformat(), "delivery_price": DELIVERY}
            return json.dumps([row]).encode()

        path = super().day_file(symbol, data_type, day).path
        return RawFile(path, fetch)


def spec_of(tmp_path: Path) -> ResolvedRunSpec:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    return resolved


@pytest.mark.integration
def test_preflight_fetches_the_delivery_price_of_an_expiry_in_the_run(
    tmp_path: Path,
) -> None:
    folders = DataFolders(tmp_path / "raw", tmp_path / "catalog")
    build_expiring_catalog(folders.catalog, None)
    source = DeliverySource()

    preflight(spec_of(tmp_path), source, folders)

    day = Window.of_days(EXPIRY_DAY, EXPIRY_DAY)
    prices = Catalog(folders.catalog).frame(DELIVERY_ID, IndexPriceUpdate, day)
    assert list(prices["price"]) == [DELIVERY]
    assert prices.index[0] == datetime(2024, 1, 2, 8, tzinfo=UTC)


@pytest.mark.integration
def test_preflight_fails_naming_a_delivery_day_the_source_lacks(
    tmp_path: Path,
) -> None:
    folders = DataFolders(tmp_path / "raw", tmp_path / "catalog")
    build_expiring_catalog(folders.catalog, None)

    with pytest.raises(MissingDataError, match=f"{DELIVERY_ID}.*2024-01-02"):
        preflight(spec_of(tmp_path), DeribitSourceWithoutDelivery(), folders)


class DeribitSourceWithoutDelivery(DeliverySource):
    @override
    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        async def fetch() -> bytes:
            raise MissingAtSourceError(symbol)

        return RawFile(super().day_file(symbol, data_type, day).path, fetch)
