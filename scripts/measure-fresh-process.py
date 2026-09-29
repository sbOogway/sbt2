"""Times what a fresh process costs a run: interpreter, imports, one small run.

Usage: uv run --locked python scripts/measure-fresh-process.py [repeats]

The run is the golden ma_cross spec: five days of one-minute data, one
BacktestNode, through ``sbt2 run``.
"""

import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "golden"
SBT2 = Path(sys.executable).parent / "sbt2"
# Built in a child: a child's peak RSS starts from its parent's, so this
# process must never import nautilus itself.
BUILD_CATALOG = """
import sys
from pathlib import Path
from golden_catalog import build_catalog
build_catalog(Path(sys.argv[1]))
"""


def build_golden_catalog(path: Path) -> None:
    command = [sys.executable, "-c", BUILD_CATALOG, str(path)]
    env = {**os.environ, "PYTHONPATH": str(GOLDEN)}
    subprocess.run(command, env=env, check=True)


def commands(data: Path) -> dict[str, list[str]]:
    python = [sys.executable, "-c"]
    return {
        "bare interpreter": [*python, "pass"],
        "import nautilus backtest": [*python, "import nautilus_trader.backtest"],
        "import sbt2 cli": [*python, "import sbt2.cli"],
        "sbt2 run ma_cross": run_golden_spec(data),
    }


def run_golden_spec(data: Path) -> list[str]:
    spec = str(GOLDEN / "ma_cross.toml")
    return [str(SBT2), "--log-level", "WARNING", "run", spec, "--data", str(data)]


def measure_once(command: list[str]) -> tuple[float, int]:
    """Wall seconds and peak RSS in MB of one child."""
    started = time.perf_counter()
    child = subprocess.Popen(command, cwd=REPO, stdout=subprocess.DEVNULL)
    _, status, usage = os.wait4(child.pid, 0)
    elapsed = time.perf_counter() - started
    if os.waitstatus_to_exitcode(status) != 0:
        raise SystemExit(f"{command} failed")
    return elapsed, usage.ru_maxrss // 1024


def report(name: str, command: list[str], repeats: int) -> None:
    samples = [measure_once(command) for _ in range(repeats)]
    wall = statistics.median(seconds for seconds, _ in samples)
    rss = max(megabytes for _, megabytes in samples)
    print(f"{name:<26} median {wall:6.2f} s   peak RSS {rss:5d} MB")


def main() -> None:
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    with tempfile.TemporaryDirectory() as folder:
        data = Path(folder)
        build_golden_catalog(data / "catalog")
        for name, command in commands(data).items():
            report(name, command, repeats)


if __name__ == "__main__":
    main()
