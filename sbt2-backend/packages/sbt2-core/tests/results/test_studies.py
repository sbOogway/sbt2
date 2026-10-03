import inspect
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import run_strategies
from batch_kit import resolved, setup
from launchers import PlainLauncher

from sbt2.core.results import (
    ParquetResultStore,
    RunFilter,
    StoredStudy,
    UnknownStudyError,
)
from sbt2.core.run import batch

STUDY = "buy-then-sell"


def store(tmp_path: Path) -> ParquetResultStore:
    return ParquetResultStore(tmp_path / "results")


@pytest.mark.integration
def test_the_first_run_creates_the_study_with_its_context_and_code(
    tmp_path: Path,
) -> None:
    batch([resolved(tmp_path, study=STUDY)], setup(tmp_path, PlainLauncher()))

    study = store(tmp_path).study(STUDY)

    assert study.name == STUDY
    assert study.strategy == "run_strategies:BuyThenSell"
    assert study.context["period"] == [
        "2024-01-01T02:00:00+00:00",
        "2024-01-05T00:00:00+00:00",
    ]
    assert study.context["capital"] == "10000 USDT"
    assert not {"params", "part", "study"} & set(study.context)
    assert study.source == inspect.getsource(run_strategies)


@pytest.mark.integration
def test_a_studys_runs_are_selected_by_its_name(tmp_path: Path) -> None:
    studied = batch(
        [
            resolved(tmp_path, study=STUDY, params={"hold_bars": 2}),
            resolved(tmp_path, study=STUDY, params={"hold_bars": 3}),
        ],
        setup(tmp_path, PlainLauncher()),
    )
    batch([resolved(tmp_path)], setup(tmp_path, PlainLauncher()))

    runs = store(tmp_path).runs(RunFilter(study=STUDY))

    assert sorted(runs["run_id"]) == sorted(studied)
    assert set(runs["study"]) == {STUDY}


@pytest.mark.unit
def test_an_unknown_study_names_the_known_ones(tmp_path: Path) -> None:
    results = store(tmp_path)
    for name in ("ma-eth", "ma-btc"):
        results.new_study(StoredStudy(name, {"strategy": "crossover:Cross"}, ""))

    with pytest.raises(UnknownStudyError, match=r"nope.* known: ma-btc, ma-eth"):
        results.study("nope")


@pytest.mark.integration
def test_a_run_stored_before_studies_is_in_none(tmp_path: Path) -> None:
    [run_id] = batch([resolved(tmp_path)], setup(tmp_path, PlainLauncher()))
    summary = store(tmp_path).folder(run_id) / "summary.parquet"
    pq.write_table(pq.read_table(summary).drop_columns("study"), summary)

    runs = store(tmp_path).runs()

    assert list(runs["run_id"]) == [run_id]
    assert runs["study"].isna().tolist() == [True]
    assert store(tmp_path).runs(RunFilter(study=STUDY)).empty
