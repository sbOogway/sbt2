from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sbt2.sources import Gap, Source
from sbt2.spec import ResolvedRunSpec

# Nautilus keeps at most this many portfolio snapshots per account, in a ring buffer.
SNAPSHOT_BUFFER = 1_000_000


@dataclass(frozen=True)
class DataFolders:
    raw: Path
    catalog: Path


class PreflightError(RuntimeError):
    pass


class SnapshotBufferError(PreflightError):
    pass


def preflight(
    spec: ResolvedRunSpec, source: Source, folders: DataFolders
) -> tuple[Gap, ...]:
    """Check that ``spec`` can run, fetching the data it lacks from ``source``.

    Returns the known-gap days the run will skip.
    """
    _check_snapshots(spec)
    return ()


def _check_snapshots(spec: ResolvedRunSpec) -> None:
    interval = timedelta(milliseconds=spec.equity_interval_ms)
    snapshots = -((spec.start - spec.end) // interval)
    if snapshots > SNAPSHOT_BUFFER:
        raise SnapshotBufferError(
            f"the run from {spec.start} to {spec.end} takes {snapshots:,} snapshots "
            f"at {interval}; nautilus keeps at most {SNAPSHOT_BUFFER:,}"
        )
