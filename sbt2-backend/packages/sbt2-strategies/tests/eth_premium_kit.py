from pathlib import Path

import option_catalog
import pytest
from option_catalog import (
    DENSE_LISTING,
    ETH_DVOL_ID,
    build_two_chain_catalog,
    write_dvol,
)
from option_runs import Scenario, run_two_chains
from premium_kit import LOW_RANK

PARAMS = """
[params]
core_dte = 45
supplemental_dte = 45
close_dte = 0
profit_target = 1000
interval_hours = 1
ladder = 1
"""
LOOSE = """
[risk.short_premium]
undefined_cap = 1
defined_cap = 1
defined_share = 1
"""


def build_portfolio_catalog(path: Path) -> None:
    expiry = DENSE_LISTING["15FEB24"][0]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(option_catalog, "LADDER_LISTING", DENSE_LISTING)
        patch.setattr(
            option_catalog,
            "ETH_LISTING",
            {"15FEB24": (expiry, tuple(range(1000, 4001, 125)))},
        )
        build_two_chain_catalog(path)
    write_dvol(path, LOW_RANK)
    write_dvol(path, LOW_RANK, ETH_DVOL_ID)


def run_portfolio(tmp_path: Path, catalog: Path, extra: str = "") -> None:
    run_two_chains(
        tmp_path,
        catalog,
        Scenario("premium_probe:ProbePortfolio", PARAMS + extra + LOOSE),
    )
