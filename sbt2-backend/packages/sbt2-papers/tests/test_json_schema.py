import json
from pathlib import Path

import pytest

import sbt2.papers.schema
from sbt2.papers.schema import PaperRecord

COMMITTED = Path(sbt2.papers.schema.__file__).parent / "paper_record.schema.json"


@pytest.mark.unit
@pytest.mark.golden
def test_the_json_schema_matches_the_committed_file(
    request: pytest.FixtureRequest,
) -> None:
    schema = PaperRecord.model_json_schema()
    if request.config.getoption("update_golden"):
        COMMITTED.write_text(json.dumps(schema, indent=2) + "\n")
    assert json.loads(COMMITTED.read_text()) == schema
