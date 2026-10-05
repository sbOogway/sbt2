import ast
from collections.abc import Sequence

from sbt2.core.results import ResultStore, RunFilter, StoredStudy
from sbt2.core.run.batching.errors import (
    DuplicateStudyRunError,
    StudyCodeError,
    StudyContextError,
)
from sbt2.core.spec import ResolvedRunSpec, Study
from sbt2.core.strategy import strategy_source

_DOCUMENTED = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def checked_studies(
    specs: Sequence[ResolvedRunSpec], store: ResultStore
) -> list[StoredStudy]:
    """Check each run of ``specs`` against the study it names, and return the
    studies the store lacks, each fixed by its first run."""
    studies = _Studies(store)
    for spec in specs:
        if spec.study is not None:
            studies.check(spec, spec.study)
    return studies.new()


class _Studies:
    """The studies a batch's runs name, each read from the store once."""

    def __init__(self, store: ResultStore) -> None:
        self._store = store
        self._known = set(store.studies())
        self._studies: dict[str, StoredStudy] = {}
        self._run_ids: dict[str, dict[str, str]] = {}

    def check(self, spec: ResolvedRunSpec, study: Study) -> None:
        stored = self._study(spec, study)
        _check_context(study, stored)
        _check_code(spec, stored)
        self._check_new_run(spec, study.name)

    def new(self) -> list[StoredStudy]:
        return [
            study for name, study in self._studies.items() if name not in self._known
        ]

    def _study(self, spec: ResolvedRunSpec, study: Study) -> StoredStudy:
        if study.name not in self._studies:
            self._studies[study.name] = (
                self._store.study(study.name)
                if study.name in self._known
                else StoredStudy(
                    study.name, study.context, strategy_source(spec.strategy.strategy)
                )
            )
        return self._studies[study.name]

    def _check_new_run(self, spec: ResolvedRunSpec, name: str) -> None:
        if name not in self._run_ids:
            runs = self._store.runs(RunFilter(study=name))
            self._run_ids[name] = dict(
                zip(runs["spec_hash"], runs["run_id"], strict=True)
            )
        stored = self._run_ids[name].get(spec.hash)
        if stored is not None:
            raise DuplicateStudyRunError(
                f"study {name} already holds the {spec.part} run with "
                f"{dict(spec.strategy.params)}: run {stored}"
            )


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
    if _normalised(strategy_source(spec.strategy.strategy)) != _normalised(
        stored.source
    ):
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
