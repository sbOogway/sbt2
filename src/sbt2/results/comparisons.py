from typing import Any

import pandas as pd

from sbt2.results.store import ResultStore, UnknownRunError
from sbt2.spec import PARTS


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
