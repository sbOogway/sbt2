from pathlib import Path

import pytest
from catalog_kit import catalog_file_name, day_bounds, new_catalog, write_funding
from kit import FUNDING_INTERVAL, HOUR, INSTRUMENT_ID, START, funding, quote
from nautilus_trader.model import NautilusDataType
from nautilus_trader.persistence import ParquetDataCatalog

QUOTES = NautilusDataType.QuoteTick


def write_hourly_quotes(catalog: ParquetDataCatalog, day: int) -> str:
    start, end = day_bounds(day)
    return catalog.write_quote_ticks(
        [quote(ts) for ts in range(start, end, HOUR)], start, end
    )


def missing_quote_intervals(
    catalog: ParquetDataCatalog, days: int
) -> list[tuple[int, int]]:
    start, _ = day_bounds(0)
    _, end = day_bounds(days - 1)
    return catalog.get_missing_intervals_for_request(
        start, end, QUOTES, str(INSTRUMENT_ID)
    )


@pytest.mark.characterization
@pytest.mark.unit
def test_write_with_bounds_names_the_file_after_the_bounds(tmp_path: Path) -> None:
    written = write_hourly_quotes(new_catalog(tmp_path), 0)

    assert Path(written).name == catalog_file_name(day_bounds(0))


@pytest.mark.characterization
@pytest.mark.unit
def test_write_without_bounds_names_the_file_after_the_data(tmp_path: Path) -> None:
    first, last = START + HOUR, START + 2 * HOUR
    written = new_catalog(tmp_path).write_quote_ticks([quote(first), quote(last)])

    assert Path(written).name == catalog_file_name((first, last))


@pytest.mark.characterization
@pytest.mark.unit
def test_adjacent_day_files_leave_no_missing_interval(tmp_path: Path) -> None:
    catalog = new_catalog(tmp_path)
    write_hourly_quotes(catalog, 0)
    write_hourly_quotes(catalog, 1)

    assert missing_quote_intervals(catalog, 2) == []


@pytest.mark.characterization
@pytest.mark.unit
def test_missing_day_is_reported_as_a_missing_interval(tmp_path: Path) -> None:
    catalog = new_catalog(tmp_path)
    write_hourly_quotes(catalog, 0)
    write_hourly_quotes(catalog, 2)

    assert missing_quote_intervals(catalog, 3) == [day_bounds(1)]


@pytest.mark.characterization
@pytest.mark.unit
def test_catalog_has_no_python_writer_for_funding(tmp_path: Path) -> None:
    catalog = new_catalog(tmp_path)

    with pytest.raises(TypeError, match="CustomData"):
        catalog.write_custom_data([funding(START + FUNDING_INTERVAL)], *day_bounds(0))


@pytest.mark.characterization
@pytest.mark.unit
def test_hand_written_funding_file_round_trips(tmp_path: Path) -> None:
    fundings = [funding(START + k * FUNDING_INTERVAL) for k in (1, 2)]
    write_funding(tmp_path, fundings, day_bounds(0))
    catalog = new_catalog(tmp_path)

    assert catalog.query(NautilusDataType.FundingRateUpdate) == fundings
    intervals = catalog.get_intervals(
        NautilusDataType.FundingRateUpdate, str(INSTRUMENT_ID)
    )
    assert intervals == [day_bounds(0)]
