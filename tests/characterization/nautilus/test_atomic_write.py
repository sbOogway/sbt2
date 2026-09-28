import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from catalog_kit import catalog_file_name, day_bounds, new_catalog
from kit import HOUR, INSTRUMENT_ID, trade
from nautilus_trader.model import NautilusDataType

pytestmark = pytest.mark.characterization

# Large enough that encoding the file takes milliseconds, so the poll below
# sees it while it is still being written.
TICKS = 3_000_000
WRITER = """
import sys
from catalog_kit import day_bounds
from kit import START, trade
from nautilus_trader.persistence import ParquetDataCatalog

ticks = [trade(START + i) for i in range(int(sys.argv[2]))]
ParquetDataCatalog(sys.argv[1]).write_trade_ticks(ticks, *day_bounds(0))
"""


def kill_while_writing(catalog: Path) -> Path:
    """Starts a large trades write in a child, kills it at its first file, returns that file."""
    directory = catalog / "data" / "trades" / str(INSTRUMENT_ID)
    kit = str(Path(__file__).parent)
    child = subprocess.Popen(
        [sys.executable, "-c", WRITER, str(catalog), str(TICKS)],
        env={**os.environ, "PYTHONPATH": kit},
    )
    try:
        while child.poll() is None:
            files = list(directory.iterdir()) if directory.is_dir() else []
            if files:
                child.send_signal(signal.SIGKILL)
                return files[0]
        pytest.fail("the write finished before any file was seen")
    finally:
        child.kill()
        child.wait()


@pytest.fixture(scope="module")
def killed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    catalog = tmp_path_factory.mktemp("catalog")
    return catalog, kill_while_writing(catalog)


def test_writer_writes_under_a_temporary_name_and_renames_when_done(
    killed: tuple[Path, Path],
) -> None:
    _, first = killed

    assert first.name.startswith(catalog_file_name(day_bounds(0)) + "#")


def test_a_write_killed_midway_leaves_no_covered_day(
    killed: tuple[Path, Path],
) -> None:
    catalog, _ = killed

    intervals = new_catalog(catalog).get_intervals(
        NautilusDataType.TradeTick, str(INSTRUMENT_ID)
    )

    assert intervals == []


def test_a_leftover_temporary_file_does_not_block_the_next_write(
    killed: tuple[Path, Path],
) -> None:
    catalog, _ = killed
    start, end = day_bounds(0)
    ticks = [trade(ts) for ts in range(start, end, HOUR)]

    new_catalog(catalog).write_trade_ticks(ticks, start, end)

    stored = new_catalog(catalog)
    assert stored.get_intervals(NautilusDataType.TradeTick, str(INSTRUMENT_ID)) == [
        (start, end)
    ]
    assert stored.query(NautilusDataType.TradeTick) == ticks
