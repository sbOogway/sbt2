import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from record_kit import make_paper, make_record

from sbt2.papers.schema import PaperRecord


def dump() -> dict[str, Any]:
    return json.loads(make_record().model_dump_json())


@pytest.mark.unit
def test_a_full_record_round_trips_through_json() -> None:
    record = make_record()
    assert PaperRecord.model_validate_json(record.model_dump_json()) == record


@pytest.mark.unit
def test_decimals_are_strings_in_json() -> None:
    record = make_record()
    dumped = json.loads(record.model_dump_json())
    assert dumped["strategies"][0]["results"][0]["value"] == "1.25"
    loaded = PaperRecord.model_validate_json(record.model_dump_json())
    assert loaded.strategies[0].results[0].value == Decimal("1.25")


@pytest.mark.unit
def test_a_record_without_strategies_is_valid() -> None:
    record = PaperRecord(schema_version=1, paper=make_paper(), strategies=[])
    assert record.strategies == []


@pytest.mark.unit
def test_other_schema_versions_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PaperRecord.model_validate(dump() | {"schema_version": 2})


@pytest.mark.unit
def test_unknown_keys_are_rejected() -> None:
    top = dump() | {"extra": 1}
    with pytest.raises(ValidationError):
        PaperRecord.model_validate(top)
    nested = dump()
    nested["strategies"][0]["extra"] = 1
    with pytest.raises(ValidationError):
        PaperRecord.model_validate(nested)


@pytest.mark.unit
def test_records_are_frozen() -> None:
    record = make_record()
    with pytest.raises(ValidationError):
        record.schema_version = 1
    with pytest.raises(ValidationError):
        record.strategies[0].name = "other"
