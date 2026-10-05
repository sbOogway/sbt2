import inspect
import sys
from pathlib import Path

import pytest
import run_strategies
from batch_kit import resolved, setup
from launchers import PlainLauncher

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import batch

MODULE = "run_strategies"
SOURCE = "strategy.py"


def stored(tmp_path: Path) -> tuple[ParquetResultStore, str]:
    [run_id] = batch([resolved(tmp_path)], setup(tmp_path, PlainLauncher()))
    return ParquetResultStore(tmp_path / "results"), run_id


@pytest.mark.integration
def test_a_new_run_keeps_its_strategy_module_source_beside_its_spec(
    tmp_path: Path,
) -> None:
    store, run_id = stored(tmp_path)

    folder = store.folder(run_id)

    assert (folder / "spec.json").exists()
    assert (folder / SOURCE).read_text() == inspect.getsource(run_strategies)


@pytest.mark.integration
def test_a_stored_run_loads_its_strategy_from_its_strategy_py(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, run_id = stored(tmp_path)
    monkeypatch.setitem(sys.modules, MODULE, None)

    run = store.stored_run(run_id)

    assert run.spec.strategy.strategy == "run_strategies:BuyThenSell"
    assert run.benchmark() is None


@pytest.mark.integration
def test_two_runs_of_one_module_name_with_different_sources_keep_their_own_classes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, first = stored(tmp_path)
    [second] = batch(
        [resolved(tmp_path, params={"hold_bars": 3})], setup(tmp_path, PlainLauncher())
    )
    source = store.folder(second) / SOURCE
    source.write_text(
        source.read_text().replace(
            "hold_bars: int = 20", "hold_bars: int = 20\n    extra: int = 5"
        )
    )
    monkeypatch.setitem(sys.modules, MODULE, None)

    assert store.stored_run(second).spec.strategy.params["extra"] == 5
    assert "extra" not in store.stored_run(first).spec.strategy.params


@pytest.mark.integration
def test_a_run_without_strategy_py_imports_its_strategy_by_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, run_id = stored(tmp_path)
    (store.folder(run_id) / SOURCE).unlink(missing_ok=True)

    assert store.stored_run(run_id).benchmark() is None

    monkeypatch.setitem(sys.modules, MODULE, None)
    with pytest.raises(ImportError):
        store.stored_run(run_id)
