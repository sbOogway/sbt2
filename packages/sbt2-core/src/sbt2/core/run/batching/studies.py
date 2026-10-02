import inspect
from collections.abc import Sequence
from pathlib import Path

from sbt2.core.results import ResultStore, StoredStudy
from sbt2.core.run.batching.errors import StudyContextError
from sbt2.core.spec import ResolvedRunSpec, Study
from sbt2.core.strategy import import_strategy


def checked_studies(
    specs: Sequence[ResolvedRunSpec], store: ResultStore
) -> list[StoredStudy]:
    """Check each run of ``specs`` against the study it names, and return the
    studies the store lacks, each fixed by its first run."""
    known = set(store.studies())
    studies: dict[str, StoredStudy] = {}
    studied = [(spec, spec.study) for spec in specs if spec.study is not None]
    for spec, study in studied:
        if study.name not in studies:
            studies[study.name] = (
                store.study(study.name) if study.name in known else _new(spec, study)
            )
        _check_context(study, studies[study.name])
    return [study for name, study in studies.items() if name not in known]


def _new(spec: ResolvedRunSpec, study: Study) -> StoredStudy:
    return StoredStudy(study.name, study.context, _module_source(spec))


def _check_context(study: Study, stored: StoredStudy) -> None:
    keys = sorted(set(study.context) | set(stored.context))
    differing = [
        key for key in keys if study.context.get(key) != stored.context.get(key)
    ]
    if differing:
        described = "; ".join(
            f"{key} is {stored.context.get(key)!r} in the study, "
            f"{study.context.get(key)!r} in the run"
            for key in differing
        )
        raise StudyContextError(
            f"the run does not fit study {study.name}'s context: {described}"
        )


def _module_source(spec: ResolvedRunSpec) -> str:
    """The source of the module that defines the run's strategy."""
    strategy = import_strategy(spec.strategy.strategy)
    path = inspect.getsourcefile(strategy)
    if path is None:
        raise TypeError(f"{spec.strategy.strategy} has no source file to pin")
    return Path(path).read_text()
