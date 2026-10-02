import ast
import inspect
from collections.abc import Sequence
from pathlib import Path

from sbt2.core.results import ResultStore, StoredStudy
from sbt2.core.run.batching.errors import StudyCodeError, StudyContextError
from sbt2.core.spec import ResolvedRunSpec, Study
from sbt2.core.strategy import import_strategy

_DOCUMENTED = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


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
        _check(spec, study, studies[study.name])
    return [study for name, study in studies.items() if name not in known]


def _new(spec: ResolvedRunSpec, study: Study) -> StoredStudy:
    return StoredStudy(study.name, study.context, _module_source(spec))


def _check(spec: ResolvedRunSpec, study: Study, stored: StoredStudy) -> None:
    _check_context(study, stored)
    _check_code(spec, stored)


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


def _check_code(spec: ResolvedRunSpec, stored: StoredStudy) -> None:
    if _normalised(_module_source(spec)) != _normalised(stored.source):
        raise StudyCodeError(
            f"the module of {spec.strategy.strategy} changed since study "
            f"{stored.name} pinned it"
        )


def _normalised(source: str) -> str:
    """The module's syntax tree without its docstrings, so that comments,
    formatting and docstrings change nothing."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, _DOCUMENTED) and _docstring(node.body):
            node.body = node.body[1:]
    return ast.dump(tree)


def _docstring(body: list[ast.stmt]) -> bool:
    match body:
        case [ast.Expr(value=ast.Constant(value=str())), *_]:
            return True
        case _:
            return False


def _module_source(spec: ResolvedRunSpec) -> str:
    """The source of the module that defines the run's strategy."""
    strategy = import_strategy(spec.strategy.strategy)
    path = inspect.getsourcefile(strategy)
    if path is None:
        raise TypeError(f"{spec.strategy.strategy} has no source file to pin")
    return Path(path).read_text()
