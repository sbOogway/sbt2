from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from price_catalog import BTC, ETH, TAKER_RATE, PriceCatalog, run_on

from sbt2.results import (
    BenchmarkArgumentError,
    BenchmarkCoverageError,
    BuyAndHold,
    EqualWeight,
    External,
    UnknownBenchmarkError,
    benchmark_statistics,
    build_benchmark,
)

START = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)
KEPT = 1 - float(TAKER_RATE)


@pytest.fixture
def prices(tmp_path: Path) -> PriceCatalog:
    return PriceCatalog(tmp_path)


@pytest.mark.unit
def test_buy_and_hold_follows_the_valuation_price_after_the_entry_fee(
    prices: PriceCatalog,
) -> None:
    prices.add_marks(
        BTC, {START: 100.0, START + 30 * MINUTE: 110.0, START + 90 * MINUTE: 99.0}
    )
    prices.add_funding(BTC, {START: Decimal("0.01"), START + HOUR: Decimal("0.01")})

    returns = BuyAndHold().returns(
        run_on([BTC], START, START + 2 * HOUR), prices.catalog
    )

    assert list(returns.index) == [START + HOUR, START + 2 * HOUR]
    assert returns.iloc[0] == pytest.approx(KEPT * 1.10 - 1)
    assert returns.iloc[1] == pytest.approx(99 / 110 - 1)


@pytest.mark.unit
def test_buy_and_hold_defaults_to_the_run_first_instrument(
    prices: PriceCatalog,
) -> None:
    prices.add_marks(BTC, {START: 100.0, START + 30 * MINUTE: 110.0})
    prices.add_marks(ETH, {START: 100.0, START + 30 * MINUTE: 50.0})
    run = run_on([BTC, ETH], START, START + HOUR)

    held = BuyAndHold().returns(run, prices.catalog)

    assert held.equals(BuyAndHold(BTC).returns(run, prices.catalog))
    assert not held.equals(BuyAndHold(ETH).returns(run, prices.catalog))


@pytest.mark.unit
def test_prices_are_forward_filled_onto_the_run_grid(prices: PriceCatalog) -> None:
    prices.add_marks(BTC, {START: 100.0, START + 150 * MINUTE: 120.0})

    returns = BuyAndHold().returns(
        run_on([BTC], START, START + 4 * HOUR), prices.catalog
    )

    assert list(returns.index) == [START + k * HOUR for k in range(1, 5)]
    assert list(returns) == pytest.approx([KEPT - 1, 0.0, 0.2, 0.0])


@pytest.mark.unit
def test_equal_weight_basket_is_bought_at_the_start_and_held(
    prices: PriceCatalog,
) -> None:
    later = START + 90 * MINUTE
    prices.add_marks(BTC, {START: 100.0, START + 30 * MINUTE: 200.0, later: 300.0})
    prices.add_marks(ETH, {START: 50.0, later: 100.0})
    run = run_on([BTC, ETH], START, START + 2 * HOUR)

    returns = EqualWeight().returns(run, prices.catalog)

    value = (1 + returns).cumprod()
    assert list(value) == pytest.approx([KEPT * 1.5, KEPT * (3 + 2) / 2])


def price_file(path: Path, prices: dict[datetime, float]) -> Path:
    frame = pd.DataFrame({"timestamp": list(prices), "price": list(prices.values())})
    if path.suffix == ".csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_parquet(path)
    return path


@pytest.mark.unit
@pytest.mark.parametrize("suffix", [".csv", ".parquet"])
def test_external_series_is_read_from_prices_in_a_file(
    tmp_path: Path, prices: PriceCatalog, suffix: str
) -> None:
    path = price_file(
        tmp_path / f"index{suffix}",
        {START - HOUR: 200.0, START + 90 * MINUTE: 220.0, START + 2 * HOUR: 110.0},
    )

    returns = External(path).returns(
        run_on([BTC], START, START + 2 * HOUR), prices.catalog
    )

    assert list(returns.index) == [START + HOUR, START + 2 * HOUR]
    assert list(returns) == pytest.approx([0.0, 110 / 200 - 1])


@pytest.mark.unit
def test_an_external_series_starting_after_the_part_fails(
    tmp_path: Path, prices: PriceCatalog
) -> None:
    path = price_file(tmp_path / "late.csv", {START + HOUR: 100.0})

    with pytest.raises(
        BenchmarkCoverageError, match=r"late\.csv has no price at 2024-01-01 00:00:00"
    ):
        External(path).returns(run_on([BTC], START, START + 2 * HOUR), prices.catalog)


@pytest.mark.unit
def test_missing_valuation_prices_fail(prices: PriceCatalog) -> None:
    prices.add_marks(BTC, {START: 100.0})
    run = run_on([BTC], START, START + timedelta(days=2))

    with pytest.raises(
        BenchmarkCoverageError,
        match="MarkPriceUpdate for BTCUSDT-LINEAR.BYBIT on 2024-01-02",
    ):
        BuyAndHold().returns(run, prices.catalog)


@pytest.mark.unit
def test_benchmark_relative_statistics_come_from_nautilus() -> None:
    times = pd.date_range(START + 12 * HOUR, periods=8, freq="12h")
    returns = pd.Series(
        [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.0, 0.01], index=times
    )

    statistics = benchmark_statistics(returns, returns, days_per_year=365)

    assert statistics["Beta"] == pytest.approx(1.0)
    assert statistics["Alpha (365 days)"] == pytest.approx(0.0, abs=1e-9)
    assert statistics["Tracking Error (365 days)"] == pytest.approx(0.0, abs=1e-12)


@pytest.mark.unit
def test_no_benchmark_has_no_series() -> None:
    returns = pd.Series([0.01, -0.02], index=[START + HOUR, START + 2 * HOUR])

    none = build_benchmark("none")

    assert none is None
    assert benchmark_statistics(returns, none, days_per_year=365) == {}


@pytest.mark.unit
def test_the_factory_builds_each_benchmark_by_name() -> None:
    assert build_benchmark("buy-and-hold") == BuyAndHold()
    assert build_benchmark("buy-and-hold", str(ETH)) == BuyAndHold(ETH)
    assert build_benchmark("equal-weight") == EqualWeight()
    assert build_benchmark("external", "index.csv") == External(Path("index.csv"))


@pytest.mark.unit
def test_unknown_benchmarks_list_the_known_ones() -> None:
    with pytest.raises(
        UnknownBenchmarkError,
        match="no benchmark cash; known: buy-and-hold, equal-weight, external, none",
    ):
        build_benchmark("cash")


@pytest.mark.unit
def test_an_external_benchmark_needs_a_file() -> None:
    with pytest.raises(BenchmarkArgumentError, match="external needs a file"):
        build_benchmark("external")


@pytest.mark.unit
@pytest.mark.parametrize("name", ["equal-weight", "none"])
def test_benchmarks_without_an_argument_refuse_one(name: str) -> None:
    with pytest.raises(BenchmarkArgumentError, match=f"{name} takes no argument"):
        build_benchmark(name, "BTCUSDT-LINEAR.BYBIT")
