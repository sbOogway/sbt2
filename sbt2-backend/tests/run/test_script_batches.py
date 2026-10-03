import os
import subprocess
import sys
from pathlib import Path

import pytest

from sbt2.core.results import ParquetResultStore

PREAMBLE = """
import sys
from pathlib import Path

from batch_kit import resolved, setup

from sbt2.core.run import Uncapped, batch

FOLDER = Path(sys.argv[1])
"""
BATCH = "batch([resolved(FOLDER)], setup(FOLDER, Uncapped()))\n"
GUARDED = f'{PREAMBLE}\nif __name__ == "__main__":\n    {BATCH}'
UNGUARDED = f"{PREAMBLE}\n{BATCH}"
TIMEOUT_SECONDS = 120


def ran(tmp_path: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run ``script`` with the test's ``sys.path``, its runs stored under
    ``tmp_path``."""
    path = tmp_path / "script.py"
    path.write_text(script)
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    return subprocess.run(
        [sys.executable, str(path), str(tmp_path)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def stored_runs(tmp_path: Path) -> int:
    return len(ParquetResultStore(tmp_path / "results").runs())


@pytest.mark.e2e
def test_a_guarded_script_runs_its_batch(tmp_path: Path) -> None:
    result = ran(tmp_path, GUARDED)

    assert result.returncode == 0, result.stderr
    assert stored_runs(tmp_path) == 1


@pytest.mark.e2e
def test_an_unguarded_script_fails_instead_of_starting_children(
    tmp_path: Path,
) -> None:
    result = ran(tmp_path, UNGUARDED)

    assert result.returncode != 0
    assert stored_runs(tmp_path) == 0
