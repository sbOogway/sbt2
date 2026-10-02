import sys
from pathlib import Path

import pandas as pd
import pytest
from batch_kit import resolved, setup, summaries
from launchers import PlainLauncher

from sbt2.core.results import ParquetResultStore, RunFilter
from sbt2.core.run import batch
from sbt2.core.spec import ResolvedRunSpec

STUDY = "studied"
STRATEGY = '''
from run_strategies import BuyThenSell


class Studied(BuyThenSell):
    """Buys 1 BTC, then sells it."""
'''


def studied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str = STRATEGY
) -> str:
    """The import path of a strategy whose module, ``source``, lives in
    ``tmp_path``."""
    (tmp_path / "studied.py").write_text(source)
    monkeypatch.syspath_prepend(tmp_path)
    monkeypatch.delitem(sys.modules, "studied", raising=False)
    return "studied:Studied"


def in_study(tmp_path: Path, strategy: str, hold_bars: int) -> ResolvedRunSpec:
    return resolved(
        tmp_path, strategy=strategy, study=STUDY, params={"hold_bars": hold_bars}
    )


def study_runs(tmp_path: Path) -> pd.DataFrame:
    return ParquetResultStore(tmp_path / "results").runs(RunFilter(study=STUDY))


@pytest.mark.integration
def test_new_parameters_extend_the_study(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = studied(tmp_path, monkeypatch)
    first = batch([in_study(tmp_path, strategy, 2)], setup(tmp_path, PlainLauncher()))

    second = batch(
        [in_study(tmp_path, strategy, 3), in_study(tmp_path, strategy, 4)],
        setup(tmp_path, PlainLauncher()),
    )

    runs = study_runs(tmp_path)
    assert sorted(runs["run_id"]) == sorted(first + second)
    assert runs["batch_id"].nunique() == 2


@pytest.mark.integration
def test_a_spec_without_a_study_runs_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = studied(tmp_path, monkeypatch)

    run_ids = batch(
        [resolved(tmp_path, strategy=strategy)], setup(tmp_path, PlainLauncher())
    )

    stored = summaries(tmp_path)
    assert set(stored) == set(run_ids)
    assert [pd.isna(each["study"]) for each in stored.values()] == [True]
    assert ParquetResultStore(tmp_path / "results").studies() == ()
    assert not (tmp_path / "results" / "studies").exists()
