import json
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from feed_strategies import HEARD
from feeds_catalog import (
    BINANCE,
    BINANCE_VOLUME,
    OKX,
    OKX_COIN_PER_CONTRACT,
    OKX_CONTRACTS,
    build_catalog,
    feed_perpetual,
    price_of,
)
from nautilus_trader.model import Bar, InstrumentId
from synthetic_catalog import START

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import (
    DataFolders,
    MissingDataError,
    RunSettings,
    execute,
    preflight,
)
from sbt2.core.spec import ResolvedRunSpec, load
from sbt2.data import Gap
from sbt2.data.testing import ServedSource

SPEC = """
strategy = "feed_strategies:{strategy}"
instruments = ["BTC-PERPETUAL.DERIBIT"]
period = [2024-01-01T00:00:00, 2024-01-05]
split = {{ validation_start = 2024-01-03, test_start = 2024-01-04 }}
part = "train"
bars = "candles"
execution = {{ fee_model = {{ kind = "maker_taker", config = {{ maker_rate = "0.00015", taker_rate = "0.00035" }} }} }}
capital = "1 BTC"
{extra}
"""
MINUTES = 2 * 1440
BASE_COIN_OF_OKX = float(OKX_CONTRACTS * OKX_COIN_PER_CONTRACT)


class OkxSource(ServedSource):
    """Serves OKX's perpetual under its own symbol and venue."""

    def instrument_id(self, symbol: str) -> InstrumentId:
        return InstrumentId.from_str(f"{symbol}.OKX")

    def symbol(self, instrument_id: InstrumentId) -> str:
        return instrument_id.symbol.value


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("catalog")
    build_catalog(path)
    return path


@pytest.fixture(autouse=True)
def clear_heard() -> Iterator[None]:
    HEARD.clear()
    yield
    HEARD.clear()


def resolved(tmp_path: Path, strategy: str, extra: str = "") -> ResolvedRunSpec:
    spec = tmp_path / "spec.toml"
    spec.write_text(SPEC.format(strategy=strategy, extra=extra))
    [only] = load(spec)
    return only


def run(tmp_path: Path, catalog: Path, strategy: str) -> None:
    resolved_spec = resolved(tmp_path, strategy)
    sink = ParquetResultStore(tmp_path / "results").new_run(resolved_spec)
    execute(resolved_spec, sink, RunSettings(catalog))


@pytest.mark.integration
def test_strategy_receives_the_bars_of_its_feeds(tmp_path: Path, catalog: Path) -> None:
    run(tmp_path, catalog, "Listener")

    assert HEARD.bars[str(BINANCE)] == MINUTES
    assert HEARD.bars[str(OKX)] == MINUTES
    assert HEARD.bars["BTC-PERPETUAL.DERIBIT"] == MINUTES


@pytest.mark.integration
def test_strategy_without_feeds_runs_as_before(tmp_path: Path, catalog: Path) -> None:
    run(tmp_path, catalog, "Plain")

    assert set(HEARD.bars) == {"BTC-PERPETUAL.DERIBIT"}
    assert HEARD.bars["BTC-PERPETUAL.DERIBIT"] == MINUTES


@pytest.mark.integration
def test_vwap_of_a_run_matches_the_feed_bars(tmp_path: Path, catalog: Path) -> None:
    run(tmp_path, catalog, "VwapListener")

    first_day = [START + timedelta(minutes=each) for each in range(1440)]
    last_minute = int((first_day[-1] + timedelta(minutes=1)).timestamp() * 10**9) - 1
    minutes = range(1440)
    by_hand = sum(
        BINANCE_VOLUME * price_of(BINANCE, minute)
        + BASE_COIN_OF_OKX * price_of(OKX, minute)
        for minute in minutes
    ) / (len(minutes) * (BINANCE_VOLUME + BASE_COIN_OF_OKX))
    assert HEARD.vwaps[last_minute] == pytest.approx(by_hand)


@pytest.mark.unit
def test_feeds_enter_the_hash_and_survive_the_document(tmp_path: Path) -> None:
    plain = resolved(tmp_path, "Plain")
    listening = resolved(tmp_path, "Listener")
    swapped = resolved(
        tmp_path, "Listener", 'params = { second = "ETHUSDT-PERP.BINANCE" }'
    )

    assert plain.feeds == ()
    assert listening.feeds == (BINANCE, OKX)
    assert len({listening.hash, swapped.hash}) == 2
    document = json.loads(listening.to_json())
    assert ResolvedRunSpec.from_document(document).feeds == (BINANCE, OKX)


@pytest.mark.integration
def test_feed_days_the_source_lacks_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "catalog"
    build_catalog(path, okx_days=1)
    folders = DataFolders(raw=tmp_path / "raw", catalog=path)
    spec = resolved(tmp_path, "VwapListener")

    source = OkxSource()
    source.serve_instrument(feed_perpetual(OKX, "0.01"))

    gaps = preflight(spec, lambda _: source, folders)

    assert gaps == (Gap(OKX, Bar, date(2024, 1, 2)),)
    sink = ParquetResultStore(tmp_path / "results").new_run(spec, gaps)
    execute(spec, sink, RunSettings(path))
    second_day_end = int((START + timedelta(days=2)).timestamp() * 10**9) - 1
    by_hand = sum(price_of(BINANCE, minute) for minute in range(1440, 2880)) / 1440
    assert HEARD.vwaps[second_day_end] == pytest.approx(by_hand)


@pytest.mark.integration
def test_own_instrument_days_the_source_lacks_still_fail_preflight(
    tmp_path: Path,
) -> None:
    folders = DataFolders(raw=tmp_path / "raw", catalog=tmp_path / "catalog")
    spec = resolved(tmp_path, "Listener")

    with pytest.raises(MissingDataError, match=r"BTC-PERPETUAL\.DERIBIT"):
        preflight(spec, lambda _: ServedSource(), folders)


@pytest.mark.integration
def test_covered_feeds_pass_preflight_without_fetching(
    tmp_path: Path, catalog: Path
) -> None:
    folders = DataFolders(raw=tmp_path / "raw", catalog=catalog)
    source = ServedSource()
    spec = resolved(tmp_path, "Listener")

    assert preflight(spec, lambda _: source, folders) == ()
    assert source.fetched == []
