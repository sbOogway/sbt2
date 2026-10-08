import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "generate-protocol.sh"
GENERATED = ROOT / "sbt2-backend/packages/sbt2-protocol/src/sbt2/protocol"


@pytest.mark.integration
def test_up_to_date_protocol_modules_are_left_in_place() -> None:
    # CI's test steps import the modules while this script runs beside them
    before = GENERATED.stat().st_ino

    subprocess.run([str(SCRIPT)], cwd=ROOT, check=True, capture_output=True)

    assert GENERATED.stat().st_ino == before


@pytest.mark.integration
def test_bytecode_beside_the_protocol_modules_does_not_make_them_stale() -> None:
    bytecode = GENERATED / "v1" / "__pycache__"
    created = not bytecode.exists()
    bytecode.mkdir(exist_ok=True)
    before = GENERATED.stat().st_ino
    try:
        subprocess.run([str(SCRIPT)], cwd=ROOT, check=True, capture_output=True)

        assert GENERATED.stat().st_ino == before
    finally:
        if created:
            shutil.rmtree(bytecode, ignore_errors=True)
