import gzip
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model import (
    CryptoPerpetual,
    Currency,
    InstrumentId,
    Price,
    Quantity,
    Symbol,
)
from typer.testing import CliRunner

from sbt2.core.cli import app

runner = CliRunner()

INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT")
SYMBOL_DIR = Path("raw/bybit/linear/BTCUSDT")
HEADER = "timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional\n"


def write_snapshot(data: Path) -> None:
    instrument = CryptoPerpetual(
        INSTRUMENT_ID,
        Symbol("BTCUSDT"),
        Currency.from_str("BTC"),
        Currency.from_str("USDT"),
        Currency.from_str("USDT"),
        False,
        2,
        3,
        Price.from_str("0.10"),
        Quantity.from_str("0.001"),
        0,
        0,
        margin_init=Decimal("0.0066"),
        margin_maint=Decimal("0.0033"),
        info={"fundingInterval": 480},
    )
    path = data / SYMBOL_DIR / "instrument" / "BTCUSDT2025-01-01.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(instrument.to_dict()))


def write_trades(data: Path, day: date) -> None:
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp()
    row = f"{noon},BTCUSDT,Buy,0.5,93000.5,PlusTick,a,0,0,0\n"
    path = data / SYMBOL_DIR / "trading" / f"BTCUSDT{day.isoformat()}.csv.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress((HEADER + row).encode()))


def ingested(data: Path, *days: date) -> Path:
    write_snapshot(data)
    for day in days:
        write_trades(data, day)
        result = runner.invoke(
            app,
            ["ingest", "--source", "bybit", "--symbol", "BTCUSDT"]
            + ["--start", day.isoformat(), "--end", day.isoformat()]
            + ["--type", "TradeTick", "--data", str(data)],
        )
        assert result.exit_code == 0, result.output
    return data


def status(data: Path, *options: str) -> Any:
    return runner.invoke(app, ["data", "status", "--data", str(data), *options])


@pytest.mark.e2e
def test_status_prints_a_row_per_instrument_and_data_type(tmp_path: Path) -> None:
    data = ingested(tmp_path, date(2025, 1, 1), date(2025, 1, 2))

    result = status(data)

    assert result.exit_code == 0, result.output
    (row,) = [line for line in result.stdout.splitlines() if "TradeTick" in line]
    assert row.split() == [
        str(INSTRUMENT_ID),
        "TradeTick",
        "2025-01-01",
        "2025-01-02",
        "2",
        "-",
        "-",
    ]


@pytest.mark.e2e
def test_status_shows_gaps_as_day_ranges(tmp_path: Path) -> None:
    data = ingested(tmp_path, date(2025, 1, 1), date(2025, 1, 4))

    result = status(data)

    assert "2025-01-02..2025-01-03" in result.stdout


@pytest.mark.e2e
def test_status_with_a_window_flags_days_outside_the_catalog(tmp_path: Path) -> None:
    data = ingested(tmp_path, date(2025, 1, 2))

    result = status(data, "--start", "2025-01-01", "--end", "2025-01-03")

    assert result.exit_code == 0, result.output
    assert "2025-01-01,2025-01-03" in result.stdout


@pytest.mark.e2e
def test_status_of_an_empty_catalog_says_so(tmp_path: Path) -> None:
    result = status(tmp_path)

    assert result.exit_code == 0
    assert "the catalog is empty" in result.stdout
