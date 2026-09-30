from dataclasses import fields
from itertools import pairwise
from typing import Any

import pandas as pd

from sbt2.results.metrics import HeadlineMetrics
from sbt2.results.store import ResultStore, UnknownRunError
from sbt2.spec import PARTS

_HEADLINE = [each.name for each in fields(HeadlineMetrics)]


def compare_parts(store: ResultStore, run_id: str) -> pd.DataFrame:
    """The summaries of the runs sharing ``run_id``'s strategy, parameters,
    instruments and split, one per part, indexed by part in split order.

    A rerun part shows its latest run; a part never run is absent.
    """
    run = _summary(store, run_id)
    runs = store.runs(strategy=run["strategy"])
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


def _summary(store: ResultStore, run_id: str) -> dict[str, Any]:
    runs = store.runs()
    found = runs.loc[runs["run_id"] == run_id].to_dict("records")
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
