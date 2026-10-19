from datetime import timedelta

from nautilus_trader.model import QuoteTick

from sbt2.core.run.preflighting.errors import (
    InstrumentAssetClassError,
    LiquidationWithoutQuotesError,
    MissingDataError,
    SnapshotBufferError,
)
from sbt2.core.run.preflighting.fetch import DataFolders, check_coverage
from sbt2.core.spec import ResolvedRunSpec
from sbt2.data import Catalog, Gap, Source

# Nautilus keeps at most this many portfolio snapshots per account, in a ring buffer.
SNAPSHOT_BUFFER = 1_000_000


def preflight(
    spec: ResolvedRunSpec, source: Source, folders: DataFolders
) -> tuple[Gap, ...]:
    """Check that ``spec`` can run, fetching the data it lacks from ``source``.

    Returns the known-gap days the run will skip.
    """
    _check_snapshots(spec)
    _check_liquidation(spec)
    covered = check_coverage(spec, source, folders)
    _check_instruments(spec, covered.catalog)
    return covered.known_gaps


def _check_snapshots(spec: ResolvedRunSpec) -> None:
    interval = timedelta(milliseconds=spec.equity_interval_ms)
    snapshots = -((spec.start - spec.end) // interval)
    if snapshots > SNAPSHOT_BUFFER:
        raise SnapshotBufferError(
            f"the run from {spec.start} to {spec.end} takes {snapshots:,} snapshots "
            f"at {interval}; nautilus keeps at most {SNAPSHOT_BUFFER:,}"
        )


def _check_liquidation(spec: ResolvedRunSpec) -> None:
    if spec.liquidation_enabled and QuoteTick not in spec.data_types:
        raise LiquidationWithoutQuotesError(
            "the run has liquidation on but streams no quotes; nautilus liquidates "
            "only on quotes, so it never would. Set liquidation = false"
        )


def _check_instruments(spec: ResolvedRunSpec, catalog: Catalog) -> None:
    _check_chains(spec, catalog)
    ids = spec.with_contracts(catalog).instrument_ids
    instruments = catalog.instruments(ids)
    absent = [str(each) for each in ids if each not in instruments]
    if absent:
        raise MissingDataError(f"the catalog has no instrument {', '.join(absent)}")
    profile = spec.asset
    for each in instruments.values():
        if not profile.covers(each):
            raise InstrumentAssetClassError(
                f"{each.id} is {each.asset_class.name}/{each.instrument_class.name}, "
                f"not the run's {profile.asset_class.name}/"
                f"{profile.instrument_class.name}"
            )


def _check_chains(spec: ResolvedRunSpec, catalog: Catalog) -> None:
    for chain in spec.chains:
        if not spec.contracts_of(chain, catalog):
            raise MissingDataError(
                f"the catalog has no contract of {chain} inside its bands "
                f"from {spec.data_window[0]} to {spec.data_window[1]}"
            )
