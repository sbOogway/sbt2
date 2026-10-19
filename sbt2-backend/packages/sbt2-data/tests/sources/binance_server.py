"""Binance's hosts answering with the files recorded next to this module."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from file_server import file_server

from sbt2.data.sources.binance import BinanceSource, Endpoints

HERE = Path(__file__).parent
KLINES = "/data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2025-01-01.zip"
ZIP = HERE / "BTCUSDT-1m-2025-01-01.zip"
CHECKSUM = HERE / "BTCUSDT-1m-2025-01-01.zip.CHECKSUM"
EXCHANGE_INFO = HERE / "binance_exchange_info.json"


@contextmanager
def binance_replay(checksum: bytes | None = None) -> Generator[BinanceSource]:
    """Binance with the recorded BTCUSDT day of 2025-01-01; ``checksum`` replaces
    the recorded checksum file."""
    with file_server() as files:
        files.serve(KLINES, ZIP.read_bytes())
        files.serve(f"{KLINES}.CHECKSUM", checksum or CHECKSUM.read_bytes())
        files.serve("/fapi/v1/exchangeInfo", EXCHANGE_INFO.read_bytes())
        yield BinanceSource(
            frozenset(), Endpoints(api=files.base_url, dumps=files.base_url)
        )
