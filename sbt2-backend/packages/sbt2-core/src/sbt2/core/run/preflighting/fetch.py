import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import date
from functools import partial
from operator import attrgetter
from pathlib import Path

from nautilus_trader.model import Bar, IndexPriceUpdate, InstrumentId, TradeTick

from sbt2.core.assets import Calendar
from sbt2.core.run.preflighting.catalog import ReadOnceCatalog
from sbt2.core.run.preflighting.errors import MissingDataError
from sbt2.core.spec import ResolvedRunSpec
from sbt2.data import (
    INSTRUMENT,
    Catalog,
    Coverage,
    DayRange,
    DownloadOptions,
    DownloadRequest,
    Gap,
    IngestOptions,
    IngestRequest,
    NoSnapshotError,
    Outcome,
    Selection,
    Source,
    Window,
    download,
    ingest,
    source_name,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DataFolders:
    raw: Path
    catalog: Path


@dataclass(frozen=True)
class Covered:
    """The known-gap days of a covered run, and the catalog that holds it."""

    known_gaps: tuple[Gap, ...]
    catalog: Catalog


def check_coverage(
    spec: ResolvedRunSpec, source: Source, folders: DataFolders
) -> Covered:
    """Fetch the days the catalog lacks, and return the known gaps with the
    catalog as it is after the fetch."""
    wanted = _Wanted(spec.asset.calendar, partial(_coverages, spec))
    fetched = _covered(wanted, source, folders)
    _require(fetched.uncovered.missing)
    return Covered(fetched.uncovered.known_gaps, fetched.catalog)


def check_feed_coverage(
    spec: ResolvedRunSpec, sources: Callable[[str], Source], folders: DataFolders
) -> Covered:
    """The same for the feeds' candles, each fetched from the source of its
    venue. A day the source reports as missing is a known gap of the run; a day
    that is still missing for another reason fails."""
    known_gaps: list[Gap] = []
    for name, feeds in _by_source(spec.feeds).items():
        selection = Selection(feeds, (Bar,), Window(*spec.data_window))
        wanted = _Wanted(spec.asset.calendar, partial(_feed_coverages, selection))
        fetched = _covered(wanted, sources(name), folders)
        _require(
            tuple(
                each for each in fetched.uncovered.missing if each not in fetched.absent
            )
        )
        known_gaps.extend(fetched.uncovered.known_gaps)
        known_gaps.extend(fetched.absent)
    return Covered(tuple(known_gaps), ReadOnceCatalog(folders.catalog))


def _by_source(feeds: Iterable[InstrumentId]) -> dict[str, tuple[InstrumentId, ...]]:
    named: dict[str, list[InstrumentId]] = {}
    for each in feeds:
        named.setdefault(source_name(each), []).append(each)
    return {name: tuple(ids) for name, ids in named.items()}


@dataclass(frozen=True)
class _Fetched:
    """The catalog after the fetch, the days still uncovered, and those of them
    the source reported as missing."""

    catalog: Catalog
    uncovered: _Uncovered
    absent: tuple[Gap, ...]


def _covered(wanted: _Wanted, source: Source, folders: DataFolders) -> _Fetched:
    folders.catalog.mkdir(parents=True, exist_ok=True)
    catalog = ReadOnceCatalog(folders.catalog)
    uncovered = _uncovered(wanted, catalog, source.known_gaps)
    reported: set[tuple[str, date]] = set()
    # The first fetch brings the contracts, which tell what delivery data is due.
    for _ in range(2):
        if not uncovered.missing:
            break
        reported |= _fetch(source, uncovered.missing, folders)
        catalog = ReadOnceCatalog(folders.catalog)
        uncovered = _uncovered(wanted, catalog, source.known_gaps)
    absent = tuple(
        each
        for each in uncovered.missing
        if (source.symbol(each.instrument_id), each.day) in reported
    )
    return _Fetched(catalog, uncovered, absent)


def _require(missing: tuple[Gap, ...]) -> None:
    if missing:
        described = ", ".join(map(str, missing))
        raise MissingDataError(f"the catalog lacks {described}")


def _fetch(
    source: Source, missing: tuple[Gap, ...], folders: DataFolders
) -> set[tuple[str, date]]:
    """Download and ingest the span of the missing days; return the symbol and
    day of each day file the source has nothing for."""
    symbols = tuple(sorted({source.symbol(each.instrument_id) for each in missing}))
    types = tuple(sorted({each.data_type.__name__ for each in missing}))
    first, last = min(each.day for each in missing), max(each.day for each in missing)
    logger.info(
        "fetching %s %s from %s to %s",
        ", ".join(symbols),
        ", ".join(types),
        first,
        last,
    )
    days = DayRange(symbols, first, last, types)
    tally = download(source, DownloadRequest(days), DownloadOptions(folders.raw))
    for each in tally.having(Outcome.FAILED):
        logger.warning("failed to fetch %s: %s", each.item.raw.path, each.reason)
    reported = {
        (each.item.symbol, each.item.day)
        for each in tally.having(Outcome.MISSING)
        if each.item.data != INSTRUMENT
    }
    try:
        ingest(
            source,
            IngestRequest(days),
            IngestOptions(folders.raw, folders.catalog),
        )
    except NoSnapshotError as error:
        ids = ", ".join(sorted({str(each.instrument_id) for each in missing}))
        raise MissingDataError(f"no instrument for {ids}: {error}") from error
    return reported


@dataclass(frozen=True)
class _Uncovered:
    """The run's days without data, on the asset class's trading days."""

    missing: tuple[Gap, ...]
    known_gaps: tuple[Gap, ...]


type _Coverages = Callable[
    [Catalog, frozenset[Gap]], Iterator[tuple[Window, tuple[Coverage, ...]]]
]


@dataclass(frozen=True)
class _Wanted:
    """The data a fetch is to cover: what it reads, and the days it is due on."""

    calendar: Calendar
    coverages: _Coverages


def _uncovered(
    wanted: _Wanted, catalog: Catalog, known_gaps: frozenset[Gap]
) -> _Uncovered:
    trading: set[date] = set()
    coverage: list[Coverage] = []
    for window, found in wanted.coverages(catalog, known_gaps):
        trading.update(wanted.calendar.trading_days(window.start, window.end))
        coverage.extend(found)
    return _Uncovered(
        missing=tuple(_gaps(coverage, frozenset(trading), attrgetter("missing"))),
        known_gaps=tuple(_gaps(coverage, frozenset(trading), attrgetter("known_gaps"))),
    )


def _feed_coverages(
    selection: Selection, catalog: Catalog, known_gaps: frozenset[Gap]
) -> Iterator[tuple[Window, tuple[Coverage, ...]]]:
    yield selection.window, catalog.coverage(selection, known_gaps)


def _coverages(
    spec: ResolvedRunSpec, catalog: Catalog, known_gaps: frozenset[Gap]
) -> Iterator[tuple[Window, tuple[Coverage, ...]]]:
    for selection in _selections(spec, catalog):
        yield selection.window, catalog.coverage(selection, known_gaps)
    for chain in spec.chains:
        index = _chain_days(spec, catalog, chain)
        days = _with_known_gaps(chain, index, known_gaps)
        yield Window(*spec.data_window), _chain_coverage(spec, days)


def _chain_days(
    spec: ResolvedRunSpec, catalog: Catalog, chain: InstrumentId
) -> Coverage:
    [index] = catalog.coverage(spec.asset.chain.days(chain, spec.data_window))
    if spec.contracts_of(chain, catalog):
        return index
    days = spec.asset.calendar.trading_days(*spec.data_window)
    return replace(index, missing=tuple(sorted(days)))


def _with_known_gaps(
    chain: InstrumentId, index: Coverage, known_gaps: frozenset[Gap]
) -> Coverage:
    """The index coverage as the chain's: a day without trades is a known gap of
    the chain."""
    known = tuple(
        day for day in index.missing if Gap(chain, TradeTick, day) in known_gaps
    )
    missing = tuple(day for day in index.missing if day not in known)
    return Coverage(chain, IndexPriceUpdate, missing, known)


def _chain_coverage(spec: ResolvedRunSpec, days: Coverage) -> tuple[Coverage, ...]:
    """The data of a chain that the run reads, for the days ``days`` lacks:
    fetching a day of the underlying brings all of it."""
    kinds = {*spec.data_types, IndexPriceUpdate}
    return tuple(
        Coverage(days.instrument_id, kind, days.missing, days.known_gaps)
        for kind in sorted(kinds, key=attrgetter("__name__"))
    )


def _selections(spec: ResolvedRunSpec, catalog: Catalog) -> list[Selection]:
    """The data of the instruments the strategy names, the delivery prices of the
    contracts it holds, and what the chains it names read besides the contracts."""
    loaded = spec.with_contracts(catalog)
    contracts = catalog.instruments(loaded.instrument_ids).values()
    deliveries = spec.asset.settlement.delivery_selections(contracts, spec.data_window)
    return [*_named(spec), *deliveries, *_references(spec)]


def _named(spec: ResolvedRunSpec) -> list[Selection]:
    """The run's own data of the instruments that are not chains."""
    named = tuple(each for each in spec.instrument_ids if each not in spec.chains)
    if not named:
        return []
    return [Selection(named, spec.data_types, Window(*spec.data_window))]


def _references(spec: ResolvedRunSpec) -> list[Selection]:
    return [
        selection
        for chain in spec.chains
        for selection in spec.asset.chain.references(chain, spec.volatility_window)
    ]


def _gaps(
    coverage: Iterable[Coverage],
    trading: frozenset[date],
    days: Callable[[Coverage], tuple[date, ...]],
) -> Iterator[Gap]:
    for each in coverage:
        for day in days(each):
            if day in trading:
                yield Gap(each.instrument_id, each.data_type, day)
