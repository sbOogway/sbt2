import json
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self, override

import duckdb
import pandas as pd

from sbt2.core.data import Gap
from sbt2.core.results.metrics import RunTables
from sbt2.core.results.store.base import (
    MissingTableError,
    ResultStore,
    RunFilter,
    RunIds,
    StoredRun,
    StoredStudy,
    Table,
    UnknownRunError,
    UnknownStudyError,
)
from sbt2.core.results.store.parquet.sink import (
    SUMMARY,
    SUMMARY_SCHEMA,
    NewRun,
    ParquetSink,
)
from sbt2.core.results.store.parquet.tables import read_table
from sbt2.core.results.store.sink import OutputSink
from sbt2.core.spec import ResolvedRunSpec

_SUMMARIES = f"*/{SUMMARY}.parquet"
_SPEC = "spec.json"
_CONTEXT = "context.json"
_SOURCE = "strategy.py"
_RUNS = """
SELECT * FROM (
    SELECT * FROM summary_schema
    UNION ALL BY NAME
    SELECT * FROM read_parquet($1, union_by_name = true)
)
WHERE ($2 IS NULL OR strategy = $2)
    AND ($3 IS NULL OR part = $3)
    AND ($4 IS NULL OR batch_id = $4)
    AND ($5 IS NULL OR list_contains($5::VARCHAR[], run_id))
    AND ($6 IS NULL OR study = $6)
ORDER BY run_id
"""
_EVERY_RUN = RunFilter()


class ParquetResultStore(ResultStore):
    """Each run is a folder of parquet tables under ``root/runs/{run_id}``; each
    study a folder under ``root/studies/{name}`` holding its context and its
    strategy module's source."""

    kind = "parquet"

    def __init__(self, root: Path) -> None:
        self._root = root
        self._runs = root / "runs"
        self._studies = root / "studies"

    @classmethod
    @override
    def from_location(cls, location: Mapping[str, Any]) -> Self:
        return cls(Path(location["root"]))

    @override
    def _location(self) -> dict[str, Any]:
        return {"root": str(self._root)}

    @override
    def new_run(
        self,
        spec: ResolvedRunSpec,
        known_gaps: tuple[Gap, ...] = (),
        ids: RunIds | None = None,
    ) -> OutputSink:
        ids = ids or RunIds()
        run_id = ids.run_id or str(uuid.uuid7())
        run = NewRun(run_id, ids.batch_id, spec, known_gaps)
        folder = self.folder(run.run_id)
        folder.mkdir(parents=True)
        (folder / _SPEC).write_text(spec.to_json())
        return ParquetSink(folder, run)

    @override
    def runs(self, where: RunFilter = _EVERY_RUN) -> pd.DataFrame:
        if not any(self._runs.glob(_SUMMARIES)):
            return SUMMARY_SCHEMA.empty_table().to_pandas()
        summaries = str(self._runs / _SUMMARIES)
        with duckdb.connect() as db:
            db.execute("SET TimeZone = 'UTC'")
            db.register("summary_schema", SUMMARY_SCHEMA.empty_table())
            found = db.execute(_RUNS, [summaries, *_parameters(where)])
            return found.arrow().read_all().to_pandas()

    @override
    def load(self, run_id: str, table: Table) -> pd.DataFrame:
        path = self._folder(run_id) / f"{table}.parquet"
        if not path.exists():
            raise MissingTableError(f"run {run_id} has no {table} table")
        return read_table(path)

    @override
    def stored_run(self, run_id: str) -> StoredRun:
        [summary] = self.load(run_id, "summary").to_dict("records")
        return StoredRun(
            spec=ResolvedRunSpec.from_document(self.spec(run_id)),
            tables=RunTables(
                equity=self.load(run_id, "equity"),
                fills=self.load(run_id, "fills"),
                carry=self.load(run_id, "carry"),
                currency=summary["currency"],
                positions=self.load(run_id, "positions"),
            ),
            known_gaps=frozenset(Gap.from_str(each) for each in summary["known_gaps"]),
        )

    @override
    def spec(self, run_id: str) -> dict[str, Any]:
        return json.loads((self._folder(run_id) / _SPEC).read_text())

    @override
    def delete(self, run_id: str) -> None:
        shutil.rmtree(self._folder(run_id))

    @override
    def folder(self, run_id: str) -> Path:
        return self._runs / run_id

    @override
    def new_study(self, study: StoredStudy) -> None:
        folder = self._studies / study.name
        folder.mkdir(parents=True)
        (folder / _CONTEXT).write_text(json.dumps(study.context, indent=2))
        (folder / _SOURCE).write_text(study.source)

    @override
    def study(self, name: str) -> StoredStudy:
        known = self.studies()
        if name not in known:
            raise UnknownStudyError(
                f"no study {name} in {self._studies}; known: {', '.join(known) or 'none'}"
            )
        folder = self._studies / name
        context = json.loads((folder / _CONTEXT).read_text())
        return StoredStudy(name, context, (folder / _SOURCE).read_text())

    @override
    def studies(self) -> tuple[str, ...]:
        if not self._studies.is_dir():
            return ()
        return tuple(sorted(each.name for each in self._studies.iterdir()))

    def _folder(self, run_id: str) -> Path:
        folder = self._runs / _canonical_uuid(run_id)
        if not folder.is_dir():
            raise UnknownRunError(f"no run {run_id} in {self._runs}")
        return folder


def _parameters(where: RunFilter) -> list[object]:
    run_ids = None if where.run_ids is None else list(where.run_ids)
    return [where.strategy, where.part, where.batch, run_ids, where.study]


def _canonical_uuid(run_id: str) -> str:
    """Guards the store against run ids that would reach outside it."""
    try:
        return str(uuid.UUID(run_id))
    except ValueError:
        raise UnknownRunError(f"{run_id!r} is not a run id") from None
