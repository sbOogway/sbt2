from pathlib import Path

import pytest
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import OmsType

from sbt2.spec import load

REPO = Path(__file__).parents[2]
SPEC = """
strategy = "spec_strategies:MinuteLookback"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
start = 2024-01-01
end = 2024-02-01
venue = "bybit_linear"
capital = "10000 USDT"
"""


@pytest.mark.unit
def test_bybit_linear_builds_a_nautilus_venue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = tmp_path / "spec.toml"
    spec.write_text(SPEC)
    monkeypatch.chdir(REPO)

    [venue] = load(spec).run_config("/catalog").venues

    assert venue.name == "BYBIT"
    assert venue.oms_type == OmsType.NETTING
    assert venue.liquidation_enabled is False
    assert isinstance(venue.fee_model, MakerTakerFeeModel)
