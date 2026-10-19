from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    CryptoOption,
    MarkPriceUpdate,
    NautilusDataType,
    OptionGreeks,
    OptionKind,
    Price,
)
from nautilus_trader.persistence import ParquetDataCatalog
from option_catalog import (
    INDEX_PRICE,
    START,
    Terms,
    build_ladder_catalog,
    contract_id_of,
    listed_option,
)
from option_runs import SPEC, VENUES

from sbt2.core.run.chain_history import read_histories
from sbt2.core.spec import ResolvedRunSpec, load
from sbt2.data import Catalog, Window

RUN_START = START + timedelta(hours=36)
PERIOD = "period = [2024-01-02T12:00:00, 2024-01-05]"
STALE = listed_option(
    contract_id_of("BTC", "12JAN24-47000-C"),
    Terms(OptionKind.CALL, datetime(2024, 1, 12, 8, tzinfo=UTC), "47000"),
)
STALE_HOURS = 6


def nanos(hour: int) -> int:
    return dt_to_unix_nanos(START + timedelta(hours=hour))


def add_stale_contract(path: Path) -> None:
    """A call marked every hour whose last IV record is a day before the run."""
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([STALE])
    marks = [
        MarkPriceUpdate(STALE.id, Price(0.05, 4), nanos(hour), nanos(hour))
        for hour in range(48)
    ]
    catalog.write_mark_price_updates(marks, nanos(0), nanos(47))
    greeks = [
        OptionGreeks(
            STALE.id,
            0.3,
            0.0001,
            10.0,
            -50.0,
            mark_iv=0.5 + 0.01 * hour,
            underlying_price=INDEX_PRICE,
            ts_event=nanos(hour),
            ts_init=nanos(hour),
        )
        for hour in range(STALE_HOURS)
    ]
    catalog.write_option_greeks(greeks, nanos(0), nanos(STALE_HOURS - 1))


def loaded_spec(tmp_path: Path, catalog: Path) -> ResolvedRunSpec:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    period = next(line for line in SPEC.splitlines() if line.startswith("period"))
    spec.write_text(SPEC.replace(period, PERIOD))
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    return resolved.with_contracts(Catalog(catalog))


@pytest.fixture
def ladder(tmp_path: Path) -> Path:
    path = tmp_path / "catalog"
    build_ladder_catalog(path)
    return path


@pytest.fixture
def catalog(ladder: Path) -> Path:
    add_stale_contract(ladder)
    return ladder


@pytest.fixture
def queries(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    query = ParquetDataCatalog.query

    def counted(self: ParquetDataCatalog, *args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return query(self, *args, **kwargs)

    monkeypatch.setattr(ParquetDataCatalog, "query", counted)
    return calls


def latest_iv(catalog: Catalog, contract: CryptoOption) -> tuple[int, float] | None:
    activation = datetime.fromtimestamp(contract.activation_ns / 1e9, UTC)
    frame = catalog.frame(contract.id, OptionGreeks, Window(activation, RUN_START))
    ivs = frame["mark_iv"].dropna()
    if ivs.empty:
        return None
    return int(pd.DatetimeIndex(ivs.index).as_unit("ns").asi8[-1]), float(ivs.iloc[-1])


@pytest.mark.integration
def test_the_chain_histories_are_read_in_one_query_per_series_type(
    tmp_path: Path, ladder: Path, queries: list[Any]
) -> None:
    spec = loaded_spec(tmp_path, ladder)
    queries.clear()

    read_histories(spec, Catalog(ladder))

    greeks = [each for each in queries if each[0] == NautilusDataType.OptionGreeks]
    assert len(greeks) == 1
    assert len(greeks[0][1]) > 2


@pytest.mark.integration
def test_the_latest_ivs_are_those_of_each_contract_life(
    tmp_path: Path, catalog: Path
) -> None:
    spec = loaded_spec(tmp_path, catalog)
    reader = Catalog(catalog)
    contracts = reader.instruments(spec.strategy.instruments).values()
    expected = {
        each.id: iv
        for each in contracts
        if isinstance(each, CryptoOption) and (iv := latest_iv(reader, each))
    }

    [history] = read_histories(spec, reader).values()

    assert STALE.id in expected
    assert dict(history.ivs) == expected
