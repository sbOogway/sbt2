from datetime import date

import pytest
from pydantic import ValidationError

from sbt2.papers.schema import Paper, Period


def make_paper(**identifiers: str) -> Paper:
    return Paper(
        title="Momentum",
        authors=["A. Author"],
        first_published=date(2020, 1, 31),
        **identifiers,
    )


@pytest.mark.unit
def test_a_paper_needs_at_least_one_identifier() -> None:
    with pytest.raises(ValidationError):
        make_paper()
    assert make_paper(arxiv_id="2001.00001").arxiv_id == "2001.00001"
    assert make_paper(ssrn_id="123456").ssrn_id == "123456"
    assert make_paper(doi="10.1000/xyz").doi == "10.1000/xyz"


@pytest.mark.unit
def test_a_period_cannot_end_before_it_starts() -> None:
    with pytest.raises(ValidationError):
        Period(start=date(2020, 1, 2), end=date(2020, 1, 1))
    assert Period(start=date(2020, 1, 1), end=date(2020, 1, 1)).end == date(2020, 1, 1)
