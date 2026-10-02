from pathlib import Path

import pytest
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import OmsType

from sbt2.core.spec import load

REPO = Path(__file__).parents[4]
SPEC = """
strategy = "spec_strategies:MinuteLookback"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
period = [2024-01-01, 2024-03-01]
split = { validation_start = 2024-02-01, test_start = 2024-02-15 }
part = "train"
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

    [resolved] = load(spec)
    [venue] = resolved.run_config("/catalog").venues

    assert venue.name == "BYBIT"
    assert venue.oms_type == OmsType.NETTING
    assert venue.liquidation_enabled is False
    assert isinstance(venue.fee_model, MakerTakerFeeModel)
