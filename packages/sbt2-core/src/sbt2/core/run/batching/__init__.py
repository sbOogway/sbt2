import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from sbt2.core.data import Gap
from sbt2.core.run.batching.children import Children
from sbt2.core.run.batching.errors import (
    OutOfMemoryError,
    RunFailedError,
    StudyCodeError,
    StudyContextError,
    StudyError,
)
from sbt2.core.run.batching.memory import Memory
from sbt2.core.run.batching.setup import BatchProgress, BatchSetup
from sbt2.core.run.batching.studies import checked_studies
from sbt2.core.run.child import Order
from sbt2.core.run.preflighting import preflight
from sbt2.core.spec import ResolvedRunSpec


class _NoProgress:
    def planned(self, runs: int) -> None:
        pass

    def finished(self, run_id: str) -> None:
        pass


def batch(
    specs: Sequence[ResolvedRunSpec],
    setup: BatchSetup,
    progress: BatchProgress | None = None,
) -> tuple[str, ...]:
    """Check every run against its study and pre-flight it, then execute each
    in a fresh process, all under one fresh batch id; returns their run_ids, in
    the order of ``specs``.

    A study the store lacks is kept, fixed by its first run, once every run
    has passed its checks.
    """
    setup.launcher.check()
    studies = checked_studies(specs, setup.store)
    known_gaps = [_preflight(each, setup) for each in specs]
    for study in studies:
        setup.store.new_study(study)
    progress = progress or _NoProgress()
    progress.planned(len(specs))
    with TemporaryDirectory(prefix="sbt2-batch-") as errors:
        orders = _orders(zip(specs, known_gaps, strict=True), setup, Path(errors))
        Children(setup, progress).run(orders)
    return tuple(each.run_id for each in orders)


def _preflight(spec: ResolvedRunSpec, setup: BatchSetup) -> tuple[Gap, ...]:
    return preflight(spec, setup.sources(spec.source), setup.folders)


def _orders(
    runs: Iterable[tuple[ResolvedRunSpec, tuple[Gap, ...]]],
    setup: BatchSetup,
    errors: Path,
) -> list[Order]:
    batch_id = str(uuid.uuid7())
    orders = []
    for spec, known_gaps in runs:
        run_id = str(uuid.uuid7())
        orders.append(
            Order(
                run_id,
                batch_id,
                spec,
                known_gaps,
                setup.store,
                setup.settings,
                errors / run_id,
            )
        )
    return orders


__all__ = [
    "BatchProgress",
    "BatchSetup",
    "Memory",
    "OutOfMemoryError",
    "RunFailedError",
    "StudyCodeError",
    "StudyContextError",
    "StudyError",
    "batch",
]
