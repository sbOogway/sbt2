import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from nautilus_run import RunOutput, round_trip_with_funding, spec

from sbt2.results import ParquetResultStore, UnknownRunError, compare_parts
from sbt2.spec import ResolvedRunSpec


@pytest.fixture(scope="module")
def output() -> RunOutput:
    return round_trip_with_funding()


@pytest.fixture
def store(tmp_path: Path) -> ParquetResultStore:
    return ParquetResultStore(tmp_path)


def finished(
    store: ParquetResultStore, output: RunOutput, run_spec: ResolvedRunSpec
) -> str:
    sink = store.new_run(run_spec)
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
