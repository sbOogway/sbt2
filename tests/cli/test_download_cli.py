from collections.abc import Iterator, Mapping
from datetime import date
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from nautilus_trader.model import InstrumentId, TradeTick
from typer.testing import CliRunner

from sbt2 import sources
from sbt2.cli import SOURCES, app
from sbt2.sources import Gap, MissingAtSourceError, RawFile

runner = CliRunner()

type Answers = Mapping[str, bytes | Exception]

DAYS = ["--start", "2025-01-01", "--end", "2025-01-02"]


class ApiSource:
    """Serves every raw file from ``answers``, keyed by path; the rest are missing."""

    def __init__(self, answers: Answers) -> None:
        self._answers = answers

    @property
    def data_types(self) -> tuple[type, ...]:
        return (TradeTick,)

    @property
    def known_gaps(self) -> frozenset[Gap]:
        return frozenset()

    def instrument_id(self, symbol: str) -> InstrumentId:
        return InstrumentId.from_str(f"{symbol}.FAKE")

    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        return self._raw(f"{symbol}/trades/{day.isoformat()}.csv")

    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        return self._raw(f"{symbol}/instrument.json")

    def parse(self, path: Path, data_type: type, instrument: Any) -> Iterator[Any]:
        raise NotImplementedError

    def parse_instrument(self, path: Path) -> Any:
        raise NotImplementedError

    def _raw(self, path: str) -> RawFile:
        return RawFile(PurePosixPath(path), partial(self._answer, path))

    async def _answer(self, path: str) -> bytes:
        answer = self._answers.get(path, MissingAtSourceError(f"no {path}"))
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes | Exception]:
    """What the source named ``fake`` answers, when looked up in the repo's config."""
    served: dict[str, bytes | Exception] = {}

    def source(name: str, config: Path) -> ApiSource:
        assert (name, config) == ("fake", SOURCES)
        return ApiSource(served)

    monkeypatch.setattr(sources, "source", source)
    return served


def download(tmp_path: Path, *options: str) -> Any:
    return runner.invoke(
        app,
        ["download", "--source", "fake", "--symbol", "BTCUSDT", *DAYS]
        + ["--data", str(tmp_path), "--retries", "0", *options],
    )


def test_downloads_into_the_raw_folder(
    tmp_path: Path, answers: dict[str, bytes | Exception]
) -> None:
    answers.update(
        {
            "BTCUSDT/instrument.json": b"{}",
            "BTCUSDT/trades/2025-01-01.csv": b"a",
            "BTCUSDT/trades/2025-01-02.csv": b"b",
        }
    )

    result = download(tmp_path)

    assert result.exit_code == 0
    assert (tmp_path / "raw/BTCUSDT/trades/2025-01-02.csv").read_bytes() == b"b"
    assert "files: 3 fetched, 0 skipped, 0 missing, 0 failed" in result.output


def test_missing_days_are_listed_and_do_not_fail_the_command(
    tmp_path: Path, answers: dict[str, bytes | Exception]
) -> None:
    answers["BTCUSDT/instrument.json"] = b"{}"
    answers["BTCUSDT/trades/2025-01-01.csv"] = b"a"

    result = download(tmp_path)

    assert result.exit_code == 0
    assert "missing at the source: BTCUSDT TradeTick 2025-01-02" in result.output


def test_a_failed_file_fails_the_command_after_the_rest_are_done(
    tmp_path: Path, answers: dict[str, bytes | Exception]
) -> None:
    answers["BTCUSDT/instrument.json"] = RuntimeError("rate limited")
    answers["BTCUSDT/trades/2025-01-01.csv"] = b"a"
    answers["BTCUSDT/trades/2025-01-02.csv"] = b"b"

    result = download(tmp_path)

    assert result.exit_code == 1
    assert "failed: BTCUSDT instrument" in result.output
    assert "rate limited" in result.output
    assert (tmp_path / "raw/BTCUSDT/trades/2025-01-02.csv").exists()


def test_a_data_type_the_source_does_not_serve_fails_before_any_fetch(
    tmp_path: Path, answers: dict[str, bytes | Exception]
) -> None:
    result = download(tmp_path, "--type", "OrderBookDelta")

    assert result.exit_code == 1
    assert "serves no OrderBookDelta" in result.output
    assert not (tmp_path / "raw").exists()


def test_an_unknown_source_fails_the_command(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["download", "--source", "nope", "--symbol", "BTCUSDT", *DAYS]
        + ["--data", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "no source nope" in result.output
