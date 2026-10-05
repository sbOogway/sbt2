from decimal import Decimal

import pytest
from pydantic import ValidationError

from sbt2.papers.schema import (
    AssetClass,
    Field,
    FieldStatus,
    Frequency,
    Parameter,
    ReportedResult,
)


@pytest.mark.unit
def test_a_missing_field_has_no_value() -> None:
    assert Field[str](status=FieldStatus.MISSING).value is None
    with pytest.raises(ValidationError):
        Field[str](value="x", status=FieldStatus.MISSING)


@pytest.mark.unit
@pytest.mark.parametrize("status", [FieldStatus.STATED, FieldStatus.INFERRED])
def test_a_stated_or_inferred_field_needs_a_value(status: FieldStatus) -> None:
    assert Field[str](value="x", status=status).value == "x"
    with pytest.raises(ValidationError):
        Field[str](status=status)


@pytest.mark.unit
def test_a_field_holds_a_list_of_values() -> None:
    field = Field[list[str]](value=["AAPL", "MSFT"], status=FieldStatus.STATED)
    assert field.value == ["AAPL", "MSFT"]


@pytest.mark.unit
def test_a_field_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        Field[str].model_validate(
            {"value": "x", "status": "stated", "evidence": "p. 3"}
        )


@pytest.mark.unit
def test_parameters_and_results_follow_the_same_status_rule() -> None:
    missing, stated = FieldStatus.MISSING, FieldStatus.STATED
    Parameter(name="n", status=missing)
    Parameter(name="n", value=Decimal(5), status=stated)
    ReportedResult(metric="Sharpe ratio", status=missing)
    ReportedResult(metric="Sharpe ratio", value=Decimal("1.2"), status=stated)
    with pytest.raises(ValidationError):
        Parameter(name="n", value=5, status=missing)
    with pytest.raises(ValidationError):
        Parameter(name="n", status=stated)
    with pytest.raises(ValidationError):
        ReportedResult(metric="m", value=Decimal(1), status=missing)
    with pytest.raises(ValidationError):
        ReportedResult(metric="m", status=stated)


@pytest.mark.unit
def test_unknown_enum_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Field[Frequency].model_validate({"value": "fortnightly", "status": "stated"})
    with pytest.raises(ValidationError):
        Field[AssetClass].model_validate({"value": "art", "status": "stated"})


@pytest.mark.unit
def test_a_parameter_keeps_its_value_type_and_its_tried_values() -> None:
    parameter = Parameter(
        name="lookback",
        value=12,
        status=FieldStatus.STATED,
        tried=[6, 12, Decimal("0.5"), True, "ema"],
    )
    loaded = Parameter.model_validate_json(parameter.model_dump_json())
    assert loaded == parameter
    assert type(loaded.value) is int
