from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from sbt2.assets import asset_class

CALENDAR = asset_class("crypto_perp").calendar


def utc(day: int, hour: int = 0) -> datetime:
    return datetime(2024, 1, day, hour, tzinfo=UTC)


def test_every_day_in_the_window_is_a_trading_day() -> None:
    assert CALENDAR.trading_days(utc(1), utc(4)) == [
        date(2024, 1, 1),
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]


def test_window_end_is_exclusive() -> None:
    assert CALENDAR.trading_days(utc(1), utc(2)) == [date(2024, 1, 1)]


def test_partial_days_count_as_trading_days() -> None:
    assert CALENDAR.trading_days(utc(1, 23), utc(2, 1)) == [
        date(2024, 1, 1),
        date(2024, 1, 2),
    ]


def test_empty_window_has_no_trading_days() -> None:
    assert CALENDAR.trading_days(utc(2), utc(2)) == []


def test_days_are_utc_days() -> None:
    plus_two = timezone(timedelta(hours=2))
    start = datetime(2024, 1, 2, 1, tzinfo=plus_two)

    assert CALENDAR.trading_days(start, start + timedelta(hours=1)) == [
        date(2024, 1, 1)
    ]


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        CALENDAR.trading_days(utc(1).replace(tzinfo=None), utc(2))
