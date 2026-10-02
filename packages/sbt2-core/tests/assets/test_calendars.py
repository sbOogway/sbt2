from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from nautilus_trader.model import AssetClass, InstrumentClass

from sbt2.core.assets import asset_profile

CALENDAR = asset_profile(AssetClass.CRYPTOCURRENCY, InstrumentClass.SWAP).calendar


def utc(day: int, hour: int = 0) -> datetime:
    return datetime(2024, 1, day, hour, tzinfo=UTC)


@pytest.mark.unit
def test_every_day_in_the_window_is_a_trading_day() -> None:
    assert CALENDAR.trading_days(utc(1), utc(4)) == [
        date(2024, 1, 1),
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]


@pytest.mark.unit
def test_window_end_is_exclusive() -> None:
    assert CALENDAR.trading_days(utc(1), utc(2)) == [date(2024, 1, 1)]


@pytest.mark.unit
def test_partial_days_count_as_trading_days() -> None:
    assert CALENDAR.trading_days(utc(1, 23), utc(2, 1)) == [
        date(2024, 1, 1),
        date(2024, 1, 2),
    ]


@pytest.mark.unit
def test_empty_window_has_no_trading_days() -> None:
    assert CALENDAR.trading_days(utc(2), utc(2)) == []


@pytest.mark.unit
def test_days_are_utc_days() -> None:
    plus_two = timezone(timedelta(hours=2))
    start = datetime(2024, 1, 2, 1, tzinfo=plus_two)

    assert CALENDAR.trading_days(start, start + timedelta(hours=1)) == [
        date(2024, 1, 1)
    ]


@pytest.mark.unit
def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        CALENDAR.trading_days(utc(1).replace(tzinfo=None), utc(2))
