from pathlib import Path

import pytest
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import OmsType

from sbt2.core.spec import MissingConfigError, load

CONFIG = Path(__file__).parents[1] / "config"
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
def test_bybit_linear_builds_a_nautilus_venue(tmp_path: Path) -> None:
    spec = tmp_path / "spec.toml"
    spec.write_text(SPEC)

    [resolved] = load(spec, CONFIG / "venues.toml")
    [venue] = resolved.run_config("/catalog").venues

    assert venue.name == "BYBIT"
    assert venue.oms_type == OmsType.NETTING
    assert venue.liquidation_enabled is False
    assert isinstance(venue.fee_model, MakerTakerFeeModel)


@pytest.mark.unit
def test_a_missing_venue_profiles_file_names_it(tmp_path: Path) -> None:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)

    with pytest.raises(MissingConfigError, match=str(venues)):
        load(spec, venues)
