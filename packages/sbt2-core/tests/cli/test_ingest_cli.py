import gzip
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model import (
    CryptoPerpetual,
    Currency,
    InstrumentId,
    NautilusDataType,
    Price,
    Quantity,
    Symbol,
)
from nautilus_trader.persistence import ParquetDataCatalog
from typer.testing import CliRunner

from sbt2.core.cli import app

runner = CliRunner()

INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT")
SYMBOL_DIR = Path("raw/bybit/linear/BTCUSDT")
DAYS = ["--start", "2025-01-01", "--end", "2025-01-02"]
TRADES = """\
timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional
1735693200.5,BTCUSDT,Buy,0.5,93000.5,PlusTick,a,0,0,0
1735693201.25,BTCUSDT,Sell,0.25,93000.0,MinusTick,b,0,0,0
"""


def write_snapshot(data: Path, taken_on: str, margin_init: str = "0.0066") -> None:
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
        margin_init=Decimal(margin_init),
        margin_maint=Decimal("0.0033"),
        info={"fundingInterval": 480},
    )
    path = data / SYMBOL_DIR / "instrument" / f"BTCUSDT{taken_on}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(instrument.to_dict()))


@pytest.fixture
def data(tmp_path: Path) -> Path:
    write_snapshot(tmp_path, "2025-01-01")
    trades = tmp_path / SYMBOL_DIR / "trading" / "BTCUSDT2025-01-01.csv.gz"
    trades.parent.mkdir(parents=True)
    trades.write_bytes(gzip.compress(TRADES.encode()))
    return tmp_path


def ingest(data: Path, *options: str) -> Any:
    return runner.invoke(
        app,
        ["ingest", "--source", "bybit", "--symbol", "BTCUSDT", *DAYS]
        + ["--type", "TradeTick", "--data", str(data), *options],
    )


@pytest.mark.e2e
def test_ingests_bybit_trades_into_the_catalog(data: Path) -> None:
    result = ingest(data)

    assert result.exit_code == 0
    catalog = ParquetDataCatalog(str(data / "catalog"))
    trades = catalog.query(NautilusDataType.TradeTick)
    assert [str(each.price) for each in trades] == ["93000.50", "93000.00"]
    assert "no raw file: BTCUSDT TradeTick 2025-01-02" in result.output
    assert "days: 1 written, 0 empty, 0 skipped, 1 missing" in result.output


@pytest.mark.e2e
def test_a_changed_snapshot_fails_unless_reingested(data: Path) -> None:
    ingest(data)
    write_snapshot(data, "2025-02-01", margin_init="0.01")

    refused = ingest(data)
    reingested = ingest(data, "--reingest")

    assert refused.exit_code == 1
    assert "re-ingest to replace it" in refused.output
    assert reingested.exit_code == 0
    assert "days: 1 written" in reingested.output


@pytest.mark.e2e
def test_a_reversed_range_fails_the_command(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["ingest", "--source", "bybit", "--symbol", "BTCUSDT"]
        + ["--start", "2025-01-02", "--end", "2025-01-01", "--data", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "before 2025-01-02" in result.output
