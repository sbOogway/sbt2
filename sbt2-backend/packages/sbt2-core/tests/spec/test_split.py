from datetime import UTC, date, datetime

import pytest

from sbt2.core.spec import DateSplit, FractionSplit, SplitDateError, SplitFractionError


def day(month: int, day: int, hour: int = 0) -> datetime:
    return datetime(2020, month, day, hour, tzinfo=UTC)


@pytest.mark.unit
def test_fractions_take_test_from_the_end_and_validation_before_it() -> None:
    parts = FractionSplit(validation=0.2, test=0.2).parts((day(1, 1), day(1, 11)))

    assert parts == {
        "train": (day(1, 1), day(1, 7)),
        "validation": (day(1, 7), day(1, 9)),
        "test": (day(1, 9), day(1, 11)),
    }


@pytest.mark.unit
def test_fraction_boundaries_round_to_the_nearest_utc_day() -> None:
    parts = FractionSplit(validation=0.2, test=0.2).parts((day(1, 1), day(1, 8)))

    assert parts["validation"] == (day(1, 5), day(1, 7))


@pytest.mark.unit
def test_each_part_starts_where_the_one_before_it_ends() -> None:
    parts = FractionSplit(validation=0.3, test=0.1).parts((day(1, 1), day(3, 1)))

    assert parts["train"][1] == parts["validation"][0]
    assert parts["validation"][1] == parts["test"][0]


@pytest.mark.unit
def test_the_period_ends_are_not_rounded() -> None:
    parts = FractionSplit(validation=0.2, test=0.2).parts((day(1, 1, 2), day(1, 11, 2)))

    assert parts["train"][0] == day(1, 1, 2)
    assert parts["test"] == (day(1, 9), day(1, 11, 2))


@pytest.mark.unit
def test_dates_set_the_part_boundaries() -> None:
    split = DateSplit(validation_start="2020-03-01", test_start=date(2020, 4, 1))

    parts = split.parts((day(1, 1), day(5, 1)))

    assert parts == {
        "train": (day(1, 1), day(3, 1)),
        "validation": (day(3, 1), day(4, 1)),
        "test": (day(4, 1), day(5, 1)),
    }


@pytest.mark.unit
def test_date_boundaries_are_floored_to_their_utc_day() -> None:
    split = DateSplit(
        validation_start=datetime.fromisoformat("2020-03-01T13:00:00+02:00"),
        test_start="2020-04-01",
    )

    parts = split.parts((day(1, 1), day(5, 1)))

    assert parts["validation"][0] == day(3, 1)


@pytest.mark.unit
@pytest.mark.parametrize("validation", [0, -0.1])
def test_fractions_that_are_not_positive_are_refused(validation: float) -> None:
    with pytest.raises(SplitFractionError, match="positive"):
        FractionSplit(validation=validation, test=0.2)


@pytest.mark.unit
@pytest.mark.parametrize(("validation", "test"), [(0.5, 0.5), (0.6, 0.5)])
def test_fractions_adding_up_to_one_or_more_are_refused(
    validation: float, test: float
) -> None:
    with pytest.raises(SplitFractionError, match="less than 1"):
        FractionSplit(validation=validation, test=test)


@pytest.mark.unit
def test_a_part_that_rounds_to_nothing_is_refused() -> None:
    split = FractionSplit(validation=0.01, test=0.2)

    with pytest.raises(SplitFractionError, match="validation"):
        split.parts((day(1, 1), day(1, 11)))


@pytest.mark.unit
@pytest.mark.parametrize("test_start", ["2020-03-01", "2020-02-01"])
def test_dates_out_of_order_are_refused(test_start: str) -> None:
    with pytest.raises(SplitDateError, match="before"):
        DateSplit(validation_start="2020-03-01", test_start=test_start)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("validation_start", "test_start"),
    [
        ("2019-12-01", "2020-03-01"),
        ("2020-01-01", "2020-03-01"),
        ("2020-02-01", "2020-05-01"),
        ("2020-02-01", "2020-06-01"),
    ],
)
def test_dates_outside_the_period_are_refused(
    validation_start: str, test_start: str
) -> None:
    split = DateSplit(validation_start=validation_start, test_start=test_start)

    with pytest.raises(SplitDateError, match="inside the period"):
        split.parts((day(1, 1), day(5, 1)))


@pytest.mark.unit
def test_the_document_names_the_kind_and_its_arguments() -> None:
    by_date = DateSplit(validation_start="2020-03-01", test_start="2020-04-01")

    assert FractionSplit(validation=0.2, test=0.1).document() == {
        "kind": "Split",
        "validation": 0.2,
        "test": 0.1,
    }
    assert by_date.document() == {
        "kind": "Split",
        "validation_start": day(3, 1),
        "test_start": day(4, 1),
    }
