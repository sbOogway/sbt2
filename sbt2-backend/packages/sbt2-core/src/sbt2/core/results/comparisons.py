import json
from dataclasses import fields
from itertools import pairwise
from typing import Any

import pandas as pd

from sbt2.core.results.metrics import HeadlineMetrics
from sbt2.core.results.store import ResultStore, RunFilter, UnknownRunError
from sbt2.core.spec import PARTS

_HEADLINE = [each.name for each in fields(HeadlineMetrics)]


def compare_parts(store: ResultStore, run_id: str) -> pd.DataFrame:
    """The summaries of the runs sharing ``run_id``'s strategy, parameters,
    instruments and split, one per part, indexed by part in split order.

    A rerun part shows its latest run; a part never run is absent.
    """
    run = _summary(store, run_id)
    runs = store.runs(RunFilter(strategy=run["strategy"]))
    same = runs.loc[_same_parameters_as(runs, run)]
    latest = same.drop_duplicates(subset=["part"], keep="last").set_index("part")
    return latest.loc[[part for part in PARTS if part in latest.index]]


def degradation(parts: pd.DataFrame) -> pd.DataFrame:
    """The headline metrics of ``compare_parts``'s parts, one column each, then
    the change from each part to the next, as a difference and as a percentage
    of a positive base.

    Only consecutive parts that were both run have a change.
    """
    table = parts[_HEADLINE].T.astype(float)
    for before, after in pairwise(PARTS):
        if before in table and after in table:
            table = _with_change(table, before, after)
    return table


def _with_change(table: pd.DataFrame, before: str, after: str) -> pd.DataFrame:
    change = table[after] - table[before]
    base = table[before].where(table[before] > 0)
    label = f"{before} → {after}"
    return table.assign(**{label: change, f"{label} %": change / base * 100})


class UnknownBatchError(LookupError):
    pass


def batch_table(store: ResultStore, batch_id: str) -> pd.DataFrame:
    """One row per run of the batch, by run_id: the strategy, parameter and
    instrument columns whose values vary across it, then the headline metrics."""
    runs = store.runs(RunFilter(batch=batch_id))
    if runs.empty:
        raise UnknownBatchError(f"no batch {batch_id} in the store")
    described = _described(runs)
    table = pd.concat([_varying(described), runs[_HEADLINE]], axis=1)
    return table.set_index(runs["run_id"])


def study_list(store: ResultStore) -> pd.DataFrame:
    """One row per study, by name: its strategy and how many runs it holds."""
    rows = [
        {"study": name, "strategy": store.study(name).strategy, "runs": count}
        for name in store.studies()
        for count in [len(store.runs(RunFilter(study=name)))]
    ]
    return pd.DataFrame(rows, columns=["study", "strategy", "runs"])


def study_table(store: ResultStore, name: str) -> pd.DataFrame:
    """One row per run of the study, by run_id: its part, the parameters whose
    values vary across the study, then the headline metrics.

    An unknown study raises ``UnknownStudyError``, naming the known ones."""
    store.study(name)
    runs = store.runs(RunFilter(study=name))
    described = _varying(_described(runs))
    table = pd.concat([runs["part"], described, runs[_HEADLINE]], axis=1)
    return table.set_index(runs["run_id"])


def _described(runs: pd.DataFrame) -> pd.DataFrame:
    params = pd.DataFrame([json.loads(each) for each in runs["params"]], runs.index)
    instruments = runs["instruments"].map(", ".join)
    return pd.concat([runs["strategy"], params, instruments], axis=1)


def _varying(described: pd.DataFrame) -> pd.DataFrame:
    varies = [
        column
        for column in described.columns
        if described[column].map(_comparable).nunique() > 1
    ]
    return described.loc[:, varies]


def _comparable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _summary(store: ResultStore, run_id: str) -> dict[str, Any]:
    found = store.runs(RunFilter(run_ids=(run_id,))).to_dict("records")
    if not found:
        raise UnknownRunError(f"no finished run {run_id}")
    return found[0]


def _same_parameters_as(runs: pd.DataFrame, run: dict[str, Any]) -> pd.Series:
    instruments = tuple(run["instruments"])
    return (
        (runs["params"] == run["params"])
        & (runs["split"] == run["split"])
        & runs["instruments"].map(lambda each: tuple(each) == instruments)
    )
