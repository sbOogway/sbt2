from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from fake_source import (
    FakeApi,
    FakeSource,
    funding_key,
    instrument_id,
    instrument_key,
    trades_path,
)
from file_server import FileServer
from nautilus_trader.model import TradeTick

from sbt2.data import (
    INSTRUMENT,
    DayRange,
    DownloadOptions,
    DownloadRequest,
    FileResult,
    Outcome,
    Report,
    download,
)
from sbt2.data.sources import Gap, UnsupportedDataTypeError

DAY = date(2025, 1, 1)
NEXT_DAY = DAY + timedelta(days=1)
TODAY = date(2026, 9, 28)
TRADES = b"timestamp,price,size\n" * 100


class Recorder:
    def __init__(self) -> None:
        self.files = 0
        self.size = 0
        self.results: list[FileResult] = []

    def planned(self, files: int) -> None:
        self.files = files

    def received(self, size: int) -> None:
        self.size += size

    def finished(self, result: FileResult) -> None:
        self.results.append(result)


def request(end: date = DAY, *data: str) -> DownloadRequest:
    return DownloadRequest(DayRange(("BTCUSDT",), DAY, end, data), taken_on=TODAY)


def options(raw: Path) -> DownloadOptions:
    return DownloadOptions(raw, backoff=0.0)


def serve_day(files: FileServer, api: FakeApi, day: date = DAY) -> None:
    files.serve(trades_path("BTCUSDT", day), TRADES)
    api.serve(funding_key("BTCUSDT", day), b"[]")
    api.serve(instrument_key("BTCUSDT", TODAY), b"{}")


def outcomes(report: Report[FileResult]) -> dict[tuple[str, date], Outcome]:
    return {(each.item.data, each.item.day): each.outcome for each in report.results}


@pytest.mark.unit
def test_fetches_each_days_files_and_todays_instrument_snapshot(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)

    report = download(FakeSource(files, api), request(), options(tmp_path))

    assert outcomes(report) == {
        (INSTRUMENT, TODAY): Outcome.FETCHED,
        ("TradeTick", DAY): Outcome.FETCHED,
        ("FundingRateUpdate", DAY): Outcome.FETCHED,
    }
    assert (tmp_path / "fake/trades/BTCUSDT/2025-01-01.csv").read_bytes() == TRADES
    assert (tmp_path / "fake/funding/BTCUSDT/2025-01-01.json").read_bytes() == b"[]"
    assert (tmp_path / "fake/instrument/BTCUSDT/2026-09-28.json").read_bytes() == b"{}"


@pytest.mark.unit
def test_the_end_day_is_included(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)
    serve_day(files, api, NEXT_DAY)

    report = download(FakeSource(files, api), request(NEXT_DAY), options(tmp_path))

    assert ("TradeTick", NEXT_DAY) in outcomes(report)
    assert len(report.having(Outcome.FETCHED)) == 5


@pytest.mark.unit
def test_a_rerun_skips_complete_files_without_asking_the_source(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)
    source = FakeSource(files, api)
    download(source, request(), options(tmp_path))

    report = download(source, request(), options(tmp_path))

    assert len(report.having(Outcome.SKIPPED)) == 3
    assert files.requests[trades_path("BTCUSDT", DAY)] == 1
    assert api.calls[funding_key("BTCUSDT", DAY)] == 1


@pytest.mark.unit
def test_a_stale_part_file_is_replaced(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)
    part = tmp_path / "fake/trades/BTCUSDT/2025-01-01.csv.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"left by a crash")

    download(FakeSource(files, api), request(), options(tmp_path))

    assert (tmp_path / "fake/trades/BTCUSDT/2025-01-01.csv").read_bytes() == TRADES
    assert not part.exists()


@pytest.mark.unit
def test_a_truncated_body_is_retried(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)
    files.fail(trades_path("BTCUSDT", DAY), "truncate")

    report = download(FakeSource(files, api), request(), options(tmp_path))

    assert outcomes(report)[("TradeTick", DAY)] is Outcome.FETCHED
    assert (tmp_path / "fake/trades/BTCUSDT/2025-01-01.csv").read_bytes() == TRADES


@pytest.mark.unit
def test_a_body_still_truncated_after_the_retries_leaves_no_file(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)
    files.fail(trades_path("BTCUSDT", DAY), "truncate", "truncate", "truncate")

    report = download(
        FakeSource(files, api),
        request(),
        DownloadOptions(tmp_path, retries=2, backoff=0.0),
    )

    assert outcomes(report)[("TradeTick", DAY)] is Outcome.FAILED
    assert not (tmp_path / "fake/trades/BTCUSDT/2025-01-01.csv").exists()


@pytest.mark.unit
def test_a_404_is_missing_and_the_other_files_still_come(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)
    api.serve(funding_key("BTCUSDT", NEXT_DAY), b"[]")

    report = download(FakeSource(files, api), request(NEXT_DAY), options(tmp_path))

    (missing,) = report.having(Outcome.MISSING)
    assert (missing.item.data, missing.item.day) == ("TradeTick", NEXT_DAY)
    assert "404" in missing.reason
    assert len(report.having(Outcome.FETCHED)) == 4
    assert files.requests[trades_path("BTCUSDT", NEXT_DAY)] == 1


@pytest.mark.unit
def test_a_source_error_saying_missing_is_missing(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)

    report = download(
        FakeSource(files, api),
        DownloadRequest(
            DayRange(("NOPEUSDT",), DAY, DAY, ("FundingRateUpdate",)), TODAY
        ),
        options(tmp_path),
    )

    assert {each.outcome for each in report.results} == {Outcome.MISSING}
    assert api.calls[instrument_key("NOPEUSDT", TODAY)] == 1


@pytest.mark.unit
@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_http_errors_are_retried(
    tmp_path: Path, files: FileServer, api: FakeApi, status: int
) -> None:
    serve_day(files, api)
    files.fail(trades_path("BTCUSDT", DAY), status, status)

    report = download(FakeSource(files, api), request(), options(tmp_path))

    assert outcomes(report)[("TradeTick", DAY)] is Outcome.FETCHED
    assert files.requests[trades_path("BTCUSDT", DAY)] == 3


@pytest.mark.unit
def test_other_http_errors_fail_without_a_retry(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)
    files.fail(trades_path("BTCUSDT", DAY), 403)

    report = download(FakeSource(files, api), request(), options(tmp_path))

    (failed,) = report.having(Outcome.FAILED)
    assert "HTTP 403" in failed.reason
    assert files.requests[trades_path("BTCUSDT", DAY)] == 1


@pytest.mark.unit
def test_source_errors_are_retried(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)
    api.fail(funding_key("BTCUSDT", DAY), httpx.ConnectError("reset"))

    report = download(FakeSource(files, api), request(), options(tmp_path))

    assert outcomes(report)[("FundingRateUpdate", DAY)] is Outcome.FETCHED
    assert api.calls[funding_key("BTCUSDT", DAY)] == 2


@pytest.mark.unit
def test_a_file_failing_every_retry_is_failed_with_the_last_error(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)
    api.fail(funding_key("BTCUSDT", DAY), *[RuntimeError("rate limited")] * 3)

    report = download(
        FakeSource(files, api),
        request(),
        DownloadOptions(tmp_path, retries=2, backoff=0.0),
    )

    (failed,) = report.having(Outcome.FAILED)
    assert "rate limited" in failed.reason
    assert api.calls[funding_key("BTCUSDT", DAY)] == 3


@pytest.mark.unit
def test_known_gaps_are_not_requested(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)
    gap = Gap(instrument_id("BTCUSDT"), TradeTick, DAY)

    report = download(
        FakeSource(files, api, frozenset({gap})), request(), options(tmp_path)
    )

    assert ("TradeTick", DAY) not in outcomes(report)
    assert files.requests[trades_path("BTCUSDT", DAY)] == 0


@pytest.mark.unit
def test_only_the_requested_data_types_are_fetched(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)

    report = download(
        FakeSource(files, api), request(DAY, "TradeTick"), options(tmp_path)
    )

    assert set(outcomes(report)) == {(INSTRUMENT, TODAY), ("TradeTick", DAY)}


@pytest.mark.unit
def test_a_data_type_the_source_does_not_serve_is_refused(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    with pytest.raises(UnsupportedDataTypeError, match="OrderBookDelta"):
        download(
            FakeSource(files, api), request(DAY, "OrderBookDelta"), options(tmp_path)
        )


@pytest.mark.unit
def test_fetches_run_at_most_the_concurrency_at_once(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    for offset in range(10):
        serve_day(files, api, DAY + timedelta(days=offset))

    download(
        FakeSource(files, api),
        request(DAY + timedelta(days=9), "FundingRateUpdate"),
        DownloadOptions(tmp_path, concurrency=3, backoff=0.0),
    )

    assert api.most_in_flight == 3


@pytest.mark.unit
def test_progress_hears_of_every_file_and_byte(
    tmp_path: Path, files: FileServer, api: FakeApi
) -> None:
    serve_day(files, api)
    progress = Recorder()

    report = download(
        FakeSource(files, api),
        request(),
        DownloadOptions(tmp_path, backoff=0.0, progress=progress),
    )

    assert progress.files == 3
    assert progress.size == len(TRADES) + len(b"[]") + len(b"{}")
    assert set(progress.results) == set(report.results)


@pytest.mark.unit
def test_a_range_ending_before_it_starts_is_refused() -> None:
    with pytest.raises(ValueError, match="before 2025-01-02"):
        DayRange(("BTCUSDT",), NEXT_DAY, DAY)
