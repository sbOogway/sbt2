import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "generate-protocol.sh"
GENERATED = ROOT / "sbt2-backend/packages/sbt2-server/src/sbt2/protocol"


@pytest.mark.integration
def test_up_to_date_protocol_modules_are_left_in_place() -> None:
    # CI's test steps import the modules while this script runs beside them
    before = GENERATED.stat().st_ino

    subprocess.run([str(SCRIPT)], cwd=ROOT, check=True, capture_output=True)

    assert GENERATED.stat().st_ino == before
