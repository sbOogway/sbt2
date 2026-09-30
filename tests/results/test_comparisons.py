import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from nautilus_run import RunOutput, round_trip_with_funding, spec
from nautilus_trader.model import InstrumentId

from sbt2.results import (
    ParquetResultStore,
    RunIds,
    UnknownBatchError,
    UnknownRunError,
    batch_table,
    compare_parts,
    degradation,
)
from sbt2.spec import ResolvedRunSpec


@pytest.fixture(scope="module")
def output() -> RunOutput:
    return round_trip_with_funding()


@pytest.fixture
def store(tmp_path: Path) -> ParquetResultStore:
    return ParquetResultStore(tmp_path)


def finished(
    store: ParquetResultStore,
    output: RunOutput,
    run_spec: ResolvedRunSpec,
    ids: RunIds | None = None,
) -> str:
    sink = store.new_run(run_spec, ids=ids)
    sink.write_equity(output.snapshots)
    sink.write_carry(output.carry)
    sink.write_reports(output.reports)
    sink.finalize()
    return sink.run_id


def run_spec(part: str, params: dict[str, Any] | None = None) -> ResolvedRunSpec:
    base = spec()
    strategy = replace(base.strategy, params=params or {"lots": 1})
    return replace(base, strategy=strategy, part=part)


@pytest.mark.unit
def test_parts_are_matched_by_strategy_params_instruments_and_split(
    store: ParquetResultStore, output: RunOutput
) -> None:
    train = finished(store, output, run_spec("train"))
    validation = finished(store, output, run_spec("validation"))
    test = finished(store, output, run_spec("test"))
    finished(store, output, run_spec("train", {"lots": 2}))

    parts = compare_parts(store, validation)

    assert list(parts.index) == ["train", "validation", "test"]
    assert list(parts["run_id"]) == [train, validation, test]


@pytest.mark.unit
def test_a_rerun_part_compares_its_latest_run(
    store: ParquetResultStore, output: RunOutput
) -> None:
    train = finished(store, output, run_spec("train"))
    finished(store, output, run_spec("validation"))
    rerun = finished(store, output, run_spec("validation"))

    parts = compare_parts(store, train)

    assert list(parts["run_id"]) == [train, rerun]


@pytest.mark.unit
def test_missing_parts_are_absent_from_the_comparison(
    store: ParquetResultStore, output: RunOutput
) -> None:
    train = finished(store, output, run_spec("train"))
    test = finished(store, output, run_spec("test"))

    parts = compare_parts(store, test)

    assert list(parts.index) == ["train", "test"]
    assert list(parts["run_id"]) == [train, test]


@pytest.mark.unit
def test_comparing_the_parts_of_an_unknown_run_fails(
    store: ParquetResultStore,
) -> None:
    with pytest.raises(UnknownRunError):
        compare_parts(store, str(uuid.uuid7()))


HEADLINE = [
    "net_return",
    "annualized_return",
    "sharpe",
    "max_drawdown",
    "trade_count",
    "total_fees",
    "total_carry",
]


def parts_with_sharpe(sharpe: dict[str, float]) -> pd.DataFrame:
    metrics = dict.fromkeys(HEADLINE, 1.0)
    rows = [
        {"run_id": part, **metrics, "sharpe": value} for part, value in sharpe.items()
    ]
    return pd.DataFrame(rows, index=pd.Index(list(sharpe), name="part"))


@pytest.mark.unit
def test_degradation_is_the_change_from_each_part_to_the_next() -> None:
    parts = parts_with_sharpe({"train": 2.0, "validation": 1.0, "test": -0.5})

    table = degradation(parts)

    assert list(table.index) == HEADLINE
    assert list(table.columns) == [
        "train",
        "validation",
        "test",
        "train → validation",
        "train → validation %",
        "validation → test",
        "validation → test %",
    ]
    sharpe = table.loc["sharpe"]
    assert sharpe["train → validation"] == pytest.approx(-1.0)
    assert sharpe["train → validation %"] == pytest.approx(-50.0)
    assert sharpe["validation → test"] == pytest.approx(-1.5)
    assert sharpe["validation → test %"] == pytest.approx(-150.0)


@pytest.mark.unit
def test_degradation_has_no_percentage_from_a_base_of_zero_or_below() -> None:
    parts = parts_with_sharpe({"train": 0.0, "validation": -1.0, "test": 0.5})

    sharpe = degradation(parts).loc["sharpe"]

    assert sharpe["train → validation"] == pytest.approx(-1.0)
    assert sharpe["validation → test"] == pytest.approx(1.5)
    assert pd.isna(sharpe["train → validation %"])
    assert pd.isna(sharpe["validation → test %"])


@pytest.mark.unit
def test_degradation_skips_the_changes_of_a_missing_part() -> None:
    parts = parts_with_sharpe({"train": 2.0, "test": 1.0})

    table = degradation(parts)

    assert list(table.columns) == ["train", "test"]


@pytest.mark.unit
def test_a_batch_table_shows_what_varies_and_the_headline_metrics(
    store: ParquetResultStore, output: RunOutput
) -> None:
    batch_id = str(uuid.uuid7())
    run_ids = [
        finished(
            store, output, run_spec("train", {"lots": lots}), RunIds(batch_id=batch_id)
        )
        for lots in (1, 2, 3)
    ]
    finished(store, output, run_spec("train", {"lots": 4}))

    table = batch_table(store, batch_id)

    assert list(table.index) == run_ids
    assert list(table.columns) == ["lots", *HEADLINE]
    assert list(table["lots"]) == [1, 2, 3]


@pytest.mark.unit
def test_an_unknown_batch_fails(store: ParquetResultStore, output: RunOutput) -> None:
    finished(store, output, run_spec("train"))
    batch_id = str(uuid.uuid7())

    with pytest.raises(UnknownBatchError, match=batch_id):
        batch_table(store, batch_id)


@pytest.mark.unit
def test_a_batch_table_shows_the_strategies_and_instruments_that_vary(
    store: ParquetResultStore, output: RunOutput
) -> None:
    ids = RunIds(batch_id=str(uuid.uuid7()))
    base = run_spec("train")
    eth = InstrumentId.from_str("ETHUSDT-LINEAR.BYBIT")
    other = replace(base.strategy, strategy="toy:Other", instruments=[eth])
    finished(store, output, base, ids)
    finished(store, output, replace(base, strategy=other), ids)

    table = batch_table(store, str(ids.batch_id))

    assert list(table.columns) == ["strategy", "instruments", *HEADLINE]
    assert list(table["instruments"]) == [
        "BTCUSDT-LINEAR.BYBIT",
        "ETHUSDT-LINEAR.BYBIT",
    ]
