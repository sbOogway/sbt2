from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from sbt2.results import benchmark_statistics

START = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


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
