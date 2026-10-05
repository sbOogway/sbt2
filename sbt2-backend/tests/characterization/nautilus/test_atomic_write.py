import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from catalog_kit import catalog_file_name, day_bounds, new_catalog
from kit import HOUR, INSTRUMENT_ID, trade
from nautilus_trader.model import NautilusDataType

TICKS = 20_000
FILE_SIZE_LIMIT = 4096
WRITER = """
import resource, signal, sys
from catalog_kit import day_bounds
from kit import START, trade
from nautilus_trader.persistence import ParquetDataCatalog

# Python ignores SIGXFSZ; the default action kills the process at the limit.
signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
limit = int(sys.argv[3])
resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
ticks = [trade(START + i) for i in range(int(sys.argv[2]))]
ParquetDataCatalog(sys.argv[1]).write_trade_ticks(ticks, *day_bounds(0))
"""


def kill_while_writing(catalog: Path) -> Path:
    """Runs a trades write in a child that the kernel kills at a file size limit.

    The limit stops the child while it writes the temporary file, before the
    rename. Returns that file.
    """
    directory = catalog / "data" / "trades" / str(INSTRUMENT_ID)
    kit = str(Path(__file__).parent)
    child = subprocess.run(
        [sys.executable, "-c", WRITER, str(catalog), str(TICKS), str(FILE_SIZE_LIMIT)],
        env={**os.environ, "PYTHONPATH": kit},
        check=False,
    )
    assert child.returncode == -signal.SIGXFSZ
    return next(directory.iterdir())


@pytest.fixture(scope="module")
def killed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    catalog = tmp_path_factory.mktemp("catalog")
    return catalog, kill_while_writing(catalog)


@pytest.mark.characterization
@pytest.mark.unit
def test_writer_writes_under_a_temporary_name_and_renames_when_done(
    killed: tuple[Path, Path],
) -> None:
    _, first = killed

    assert first.name.startswith(catalog_file_name(day_bounds(0)) + "#")


@pytest.mark.characterization
@pytest.mark.unit
def test_a_write_killed_midway_leaves_no_covered_day(
    killed: tuple[Path, Path],
) -> None:
    catalog, _ = killed

    intervals = new_catalog(catalog).get_intervals(
        NautilusDataType.TradeTick, str(INSTRUMENT_ID)
    )

    assert intervals == []


@pytest.mark.characterization
@pytest.mark.unit
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
