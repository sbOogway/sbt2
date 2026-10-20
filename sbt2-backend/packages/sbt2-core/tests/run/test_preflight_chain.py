from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from chain_source import (
    BEFORE,
    DAYS,
    DELIVERY,
    INDEX_PRICE,
    ChainSource,
    ChainSourceWithLookBack,
    ChainSourceWithoutTrades,
)
from nautilus_trader.model import IndexPriceUpdate, InstrumentId, MarkPriceUpdate

from sbt2.core.run import DataFolders, MissingDataError, preflight
from sbt2.core.spec import ResolvedRunSpec, load
from sbt2.data import (
    Catalog,
    DayRange,
    DownloadOptions,
    DownloadRequest,
    IngestOptions,
    IngestRequest,
    Window,
    download,
    ingest,
)

SPEC = """
strategy = "run_strategies:ActOnSchedule"
instruments = ["BTC-OPTIONS.DERIBIT"]
period = [2024-01-01, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
execution = { fee_model = { kind = "capped_option", config = { maker_rate = "0.0003", taker_rate = "0.0003", cap_rate = "0.125" } } }
capital = "1 BTC"

[chain]
min_dte = 0
max_dte = 90
strike_band = "0.5"
"""
INDEX = InstrumentId.from_str("BTC_USD.DERIBIT")
DVOL = InstrumentId.from_str("BTC_DVOL.DERIBIT")
DELIVERY_ID = InstrumentId.from_str("BTC_USD_DELIVERY.DERIBIT")
IN_BAND = InstrumentId.from_str("BTC-2JAN24-45000-C.DERIBIT")


def spec_of(
    tmp_path: Path, strategy: str = "run_strategies:ActOnSchedule"
) -> ResolvedRunSpec:
    spec = tmp_path / "spec.toml"
    spec.write_text(SPEC.replace("run_strategies:ActOnSchedule", strategy))
    [resolved] = load(spec)
    return resolved


def folders_of(tmp_path: Path) -> DataFolders:
    return DataFolders(tmp_path / "raw", tmp_path / "catalog")


def frame_of(
    folders: DataFolders, instrument_id: InstrumentId, data_type: type
) -> list[float]:
    window = Window.of_days(DAYS[0], DAYS[-1])
    frame = Catalog(folders.catalog).frame(instrument_id, data_type, window)
    return list(frame["price"])


@pytest.mark.integration
def test_preflight_fetches_the_index_dvol_and_delivery_prices_of_a_chain_run(
    tmp_path: Path,
) -> None:
    folders = folders_of(tmp_path)
    source = ChainSource()

    preflight(spec_of(tmp_path), lambda _: source, folders)

    [delivery] = [each for each in source.asked if "DELIVERY" in each.name]
    assert delivery.name.endswith("2024-01-02.json")
    assert set(frame_of(folders, INDEX, IndexPriceUpdate)) == {INDEX_PRICE}
    assert len(frame_of(folders, DVOL, IndexPriceUpdate)) == 48
    assert frame_of(folders, DELIVERY_ID, IndexPriceUpdate) == [DELIVERY]
    assert frame_of(folders, IN_BAND, MarkPriceUpdate)


@pytest.mark.integration
def test_a_chain_run_without_its_index_names_the_missing_days(
    tmp_path: Path,
) -> None:
    days = ".*".join(f"BTC-OPTIONS.DERIBIT IndexPriceUpdate {each}" for each in DAYS)

    with pytest.raises(MissingDataError, match=days):
        preflight(
            spec_of(tmp_path),
            lambda _: ChainSourceWithoutTrades(),
            folders_of(tmp_path),
        )


@pytest.mark.integration
def test_a_covered_chain_run_fetches_nothing(tmp_path: Path) -> None:
    folders = folders_of(tmp_path)
    preflight(spec_of(tmp_path), lambda _: ChainSource(), folders)
    again = ChainSource()

    assert preflight(spec_of(tmp_path), lambda _: again, folders) == ()
    assert again.asked == []


@pytest.mark.integration
def test_preflight_fetches_the_dvol_look_back_before_the_run(tmp_path: Path) -> None:
    folders = folders_of(tmp_path)
    source = ChainSourceWithLookBack()

    preflight(
        spec_of(tmp_path, "run_strategies:DayLookBack"), lambda _: source, folders
    )

    frame = Catalog(folders.catalog).frame(
        DVOL, IndexPriceUpdate, Window.of_days(BEFORE, DAYS[-1])
    )
    assert len(frame) == 72
    assert any(each.name.endswith(f"{BEFORE}.json") for each in source.asked)


@pytest.mark.integration
def test_a_chain_run_without_its_dvol_look_back_names_the_missing_day(
    tmp_path: Path,
) -> None:
    spec = spec_of(tmp_path, "run_strategies:DayLookBack")

    with pytest.raises(
        MissingDataError, match=rf"BTC_DVOL.DERIBIT IndexPriceUpdate {BEFORE}"
    ):
        preflight(spec, lambda _: ChainSource(), folders_of(tmp_path))


@pytest.mark.integration
def test_preflight_fetches_a_chain_when_only_its_index_is_cached(
    tmp_path: Path,
) -> None:
    folders = folders_of(tmp_path)
    source = ChainSource()
    days = DayRange(("BTC",), DAYS[0], DAYS[-1], data=(IndexPriceUpdate.__name__,))
    download(source, DownloadRequest(days), DownloadOptions(folders.raw))
    ingest(source, IngestRequest(days), IngestOptions(folders.raw, folders.catalog))
    source.asked.clear()

    preflight(spec_of(tmp_path), lambda _: source, folders)

    assert frame_of(folders, IN_BAND, MarkPriceUpdate)


@pytest.mark.integration
def test_a_preflight_reads_the_catalog_instruments_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folders = folders_of(tmp_path)
    preflight(spec_of(tmp_path), lambda _: ChainSource(), folders)
    reads: list[int] = []
    read = Catalog.instruments

    def counted(self: Catalog, instrument_ids: Iterable[InstrumentId]) -> Any:
        ids = list(instrument_ids)
        reads.append(len(ids))
        return read(self, ids)

    monkeypatch.setattr(Catalog, "instruments", counted)

    preflight(spec_of(tmp_path), lambda _: ChainSource(), folders)

    assert len(reads) == 1
