from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from sbt2.core.results import trade_statistics

START = datetime(2024, 1, 1, tzinfo=UTC)
NO_MARGIN = pd.DataFrame()


def trades(pls: list[float], days: list[float] | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {"pl": pls, "days_held": days or [1.0] * len(pls), "pl_percent": pls}
    )


def margin(*used: float, currency: str = "BTC") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_event": [START + timedelta(hours=k) for k in range(len(used))],
            "currency": currency,
            "margin_used": list(used),
            "maintenance_margin": list(used),
        }
    )


def statistics(
    run_trades: pd.DataFrame, run_margin: pd.DataFrame = NO_MARGIN
) -> dict[str, float | None]:
    return trade_statistics(run_trades, run_margin, "BTC")


@pytest.mark.unit
def test_pop_is_the_share_of_trades_with_a_profit() -> None:
    found = statistics(trades([0.1, -0.05, 0.0, 0.2]))

    assert found["Occurrences"] == 4
    assert found["POP"] == pytest.approx(0.5)


@pytest.mark.unit
def test_cvar_is_the_mean_of_the_worst_five_percent_of_trades() -> None:
    found = statistics(trades([float(k) for k in range(-20, 20)]))

    assert found["CVaR 5%"] == pytest.approx((-20 - 19) / 2)


@pytest.mark.unit
def test_cvar_of_few_trades_is_the_worst_trade() -> None:
    found = statistics(trades([0.3, -0.2, 0.1]))

    assert found["CVaR 5%"] == pytest.approx(-0.2)


@pytest.mark.unit
def test_pl_per_day_is_total_pl_over_days_held() -> None:
    found = statistics(trades([0.3, -0.1], days=[2.0, 3.0]))

    assert found["P/L per Day"] == pytest.approx(0.2 / 5.0)


@pytest.mark.unit
def test_average_deviation_and_largest_loss() -> None:
    found = statistics(trades([0.1, -0.3, 0.2]))

    assert found["Average P/L"] == pytest.approx(0.0)
    assert found["P/L Standard Deviation"] == pytest.approx(0.07**0.5)
    assert found["Largest Loss"] == pytest.approx(-0.3)


@pytest.mark.unit
def test_bpr_average_and_peak_come_from_the_margin_table() -> None:
    found = statistics(trades([0.1]), margin(0.2, 0.4, 0.0))

    assert found["BPR Average"] == pytest.approx(0.2)
    assert found["BPR Peak"] == pytest.approx(0.4)


@pytest.mark.unit
def test_a_run_without_trades_or_margin_has_only_its_count() -> None:
    assert statistics(trades([])) == {"Occurrences": 0}


@pytest.mark.unit
def test_a_single_trade_has_no_standard_deviation() -> None:
    assert statistics(trades([0.1]))["P/L Standard Deviation"] is None
