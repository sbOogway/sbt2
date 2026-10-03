import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from batch_kit import resolved, setup, summaries
from launchers import PlainLauncher

from sbt2.core.results import ParquetResultStore, RunFilter
from sbt2.core.run import (
    DuplicateStudyRunError,
    StudyCodeError,
    StudyContextError,
    batch,
)
from sbt2.core.spec import ResolvedRunSpec

STUDY = "studied"
STRATEGY = '''
from run_strategies import BuyThenSell


class Studied(BuyThenSell):
    """Buys 1 BTC, then sells it."""
'''
CHANGED = '''
from run_strategies import BuyThenSell


class Studied(BuyThenSell):
    """Buys 1 BTC, then sells it."""

    def on_start(self) -> None:
        super().on_start()
        self.bars = 1
'''
REFORMATTED = '''"""The studied strategy."""
# what the study runs
from run_strategies import BuyThenSell  # bought, then sold

class Studied( BuyThenSell ):
    """Another docstring,
    over two lines."""
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


def in_study(
    tmp_path: Path, strategy: str, hold_bars: int, **overrides: Any
) -> ResolvedRunSpec:
    return resolved(
        tmp_path,
        strategy=strategy,
        study=STUDY,
        params={"hold_bars": hold_bars},
        **overrides,
    )


def study_runs(tmp_path: Path) -> pd.DataFrame:
    return ParquetResultStore(tmp_path / "results").runs(RunFilter(study=STUDY))


@pytest.mark.integration
def test_a_run_with_another_context_is_refused_naming_the_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = studied(tmp_path, monkeypatch)
    first = batch([in_study(tmp_path, strategy, 2)], setup(tmp_path, PlainLauncher()))
    later = ["2024-01-01T03:00:00", "2024-01-05"]
    elsewhere = in_study(tmp_path, strategy, 3, period=later)
    launcher = PlainLauncher()

    with pytest.raises(StudyContextError, match=r"\bperiod\b"):
        batch([elsewhere], setup(tmp_path, launcher))

    assert launcher.pids == []
    assert list(study_runs(tmp_path)["run_id"]) == list(first)


@pytest.mark.integration
def test_a_run_with_changed_code_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = studied(tmp_path, monkeypatch)
    first = batch([in_study(tmp_path, strategy, 2)], setup(tmp_path, PlainLauncher()))
    studied(tmp_path, monkeypatch, CHANGED)
    launcher = PlainLauncher()

    with pytest.raises(StudyCodeError, match=STUDY):
        batch([in_study(tmp_path, strategy, 3)], setup(tmp_path, launcher))

    assert launcher.pids == []
    assert list(study_runs(tmp_path)["run_id"]) == list(first)


@pytest.mark.integration
def test_comments_formatting_and_docstrings_do_not_change_the_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = studied(tmp_path, monkeypatch)
    first = batch([in_study(tmp_path, strategy, 2)], setup(tmp_path, PlainLauncher()))
    studied(tmp_path, monkeypatch, REFORMATTED)

    second = batch([in_study(tmp_path, strategy, 3)], setup(tmp_path, PlainLauncher()))

    assert sorted(study_runs(tmp_path)["run_id"]) == sorted(first + second)


@pytest.mark.integration
def test_a_repeated_run_is_refused_naming_the_stored_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = studied(tmp_path, monkeypatch)
    [stored] = batch(
        [in_study(tmp_path, strategy, 2)], setup(tmp_path, PlainLauncher())
    )
    launcher = PlainLauncher()

    with pytest.raises(DuplicateStudyRunError, match=stored):
        batch(
            [in_study(tmp_path, strategy, 3), in_study(tmp_path, strategy, 2)],
            setup(tmp_path, launcher),
        )

    assert launcher.pids == []
    assert list(study_runs(tmp_path)["run_id"]) == [stored]


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
