"""Binance's hosts answering with the files recorded next to this module."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from file_server import file_server
from synthetic_klines import binance_zip

from sbt2.data.sources.binance import BinanceSource, Endpoints

HERE = Path(__file__).parent
KLINES = "/data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2025-01-01.zip"
EXCHANGE_INFO = HERE / "binance_exchange_info.json"


@contextmanager
def binance_replay(checksum: bytes | None = None) -> Generator[BinanceSource]:
    """Binance with a synthetic BTCUSDT day of 2025-01-01; ``checksum`` replaces
    its checksum file."""
    dump, own_checksum = binance_zip()
    with file_server() as files:
        files.serve(KLINES, dump)
        files.serve(f"{KLINES}.CHECKSUM", checksum or own_checksum)
        files.serve("/fapi/v1/exchangeInfo", EXCHANGE_INFO.read_bytes())
        yield BinanceSource(
            frozenset(), Endpoints(api=files.base_url, dumps=files.base_url)
        )
