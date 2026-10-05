import pytest
from pydantic import ValidationError

from sbt2.papers.schema import Field, FieldStatus


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
