from datetime import UTC, date, datetime

import pytest

from sbt2.spec import Split


def day(month: int, day: int, hour: int = 0) -> datetime:
    return datetime(2020, month, day, hour, tzinfo=UTC)


@pytest.mark.unit
def test_fractions_take_test_from_the_end_and_validation_before_it() -> None:
    parts = Split(validation=0.2, test=0.2).parts((day(1, 1), day(1, 11)))

    assert parts == {
        "train": (day(1, 1), day(1, 7)),
        "validation": (day(1, 7), day(1, 9)),
        "test": (day(1, 9), day(1, 11)),
    }


@pytest.mark.unit
def test_fraction_boundaries_round_to_the_nearest_utc_day() -> None:
    parts = Split(validation=0.2, test=0.2).parts((day(1, 1), day(1, 8)))

    assert parts["validation"] == (day(1, 5), day(1, 7))


@pytest.mark.unit
def test_each_part_starts_where_the_one_before_it_ends() -> None:
    parts = Split(validation=0.3, test=0.1).parts((day(1, 1), day(3, 1)))

    assert parts["train"][1] == parts["validation"][0]
    assert parts["validation"][1] == parts["test"][0]


@pytest.mark.unit
def test_the_period_ends_are_not_rounded() -> None:
    parts = Split(validation=0.2, test=0.2).parts((day(1, 1, 2), day(1, 11, 2)))

    assert parts["train"][0] == day(1, 1, 2)
    assert parts["test"] == (day(1, 9), day(1, 11, 2))


@pytest.mark.unit
def test_dates_set_the_part_boundaries() -> None:
    split = Split(validation_start="2020-03-01", test_start=date(2020, 4, 1))

    parts = split.parts((day(1, 1), day(5, 1)))

    assert parts == {
        "train": (day(1, 1), day(3, 1)),
        "validation": (day(3, 1), day(4, 1)),
        "test": (day(4, 1), day(5, 1)),
    }


@pytest.mark.unit
def test_date_boundaries_are_floored_to_their_utc_day() -> None:
    split = Split(
        validation_start=datetime.fromisoformat("2020-03-01T13:00:00+02:00"),
        test_start="2020-04-01",
    )

    parts = split.parts((day(1, 1), day(5, 1)))

    assert parts["validation"][0] == day(3, 1)
