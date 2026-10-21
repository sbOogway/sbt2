from pathlib import Path

import pytest
from deribit_perpetual_catalog import build_catalog, price_in_hour
from deribit_perpetual_runs import run
from nautilus_trader.model import Money
from plotted import Plotted, plotted

from sbt2.core.results import PricedRun, costs_and_exposure, tearsheet
from sbt2.data import Catalog

CONTRACTS = 100_000
OPEN_HOUR = 3
CLOSE_HOUR = 23
TAKER_RATE = 0.00035
TOLERANCE = 2e-8


@pytest.fixture(scope="module")
def priced(tmp_path_factory: pytest.TempPathFactory) -> PricedRun:
    catalog = tmp_path_factory.mktemp("catalog")
    build_catalog(catalog)
    store, run_id = run(tmp_path_factory.mktemp("run"), catalog)
    return store.stored_run(run_id).priced(Catalog(catalog))


def coin(amount: object) -> float:
    return Money.from_str(str(amount)).as_double()


def fee(hour: int) -> float:
    """The fee of an order that fills at the open of the hour's first bar."""
    return CONTRACTS / price_in_hour(hour) * TAKER_RATE


@pytest.mark.integration
def test_the_costs_of_an_inverse_perpetual_run_are_in_the_coin(
    priced: PricedRun,
) -> None:
    tables = priced.tables

    activity = costs_and_exposure(priced).total
    costs = activity.costs

    open_price, close_price = price_in_hour(OPEN_HOUR), price_in_hour(CLOSE_HOUR)
    gross = CONTRACTS * (1 / open_price - 1 / close_price)
    funding = sum(coin(each) for each in tables.carry["pnl_change"])
    assert costs.fees == pytest.approx(
        -(fee(OPEN_HOUR) + fee(CLOSE_HOUR)), abs=TOLERANCE
    )
    assert costs.carry == pytest.approx(funding, abs=TOLERANCE)
    assert costs.gross == pytest.approx(gross, abs=TOLERANCE)
    assert costs.net == pytest.approx(priced.equity.iloc[-1] - priced.equity.iloc[0])
    leverage = activity.exposure.gross_leverage
    mark_at_open = price_in_hour(OPEN_HOUR - 1)
    assert leverage.max() == pytest.approx(CONTRACTS / mark_at_open / 1.0, rel=1e-6)
    [by_instrument] = costs_and_exposure(priced).by_instrument.values()
    assert by_instrument.costs.net == pytest.approx(costs.net, abs=TOLERANCE)


def drawn(run_: PricedRun, path: Path) -> Plotted:
    target = path / "tearsheet.html"
    tearsheet(run_, target)
    return plotted(target.read_text())


@pytest.mark.integration
def test_the_tearsheet_of_an_inverse_perpetual_run_renders(
    priced: PricedRun, tmp_path: Path
) -> None:
    figure = drawn(priced, tmp_path)

    [waterfall] = figure.of_type("waterfall")
    gross, fees, carry, net = waterfall["y"]
    assert gross + fees + carry == pytest.approx(net)
    assert fees < 0
