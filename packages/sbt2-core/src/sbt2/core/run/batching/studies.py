import inspect
from collections.abc import Sequence
from pathlib import Path

from sbt2.core.results import ResultStore, StoredStudy
from sbt2.core.spec import ResolvedRunSpec
from sbt2.core.strategy import import_strategy


def new_studies(
    specs: Sequence[ResolvedRunSpec], store: ResultStore
) -> list[StoredStudy]:
    """The studies of ``specs`` the store lacks, each fixed by its first run."""
    new: dict[str, StoredStudy] = {}
    known = set(store.studies())
    for spec in specs:
        study = spec.study
        if study is not None and study.name not in known | set(new):
            new[study.name] = StoredStudy(
                study.name, study.context, _module_source(spec)
            )
    return list(new.values())


def _module_source(spec: ResolvedRunSpec) -> str:
    """The source of the module that defines the run's strategy."""
    strategy = import_strategy(spec.strategy.strategy)
    path = inspect.getsourcefile(strategy)
    if path is None:
        raise TypeError(f"{spec.strategy.strategy} has no source file to pin")
    return Path(path).read_text()
