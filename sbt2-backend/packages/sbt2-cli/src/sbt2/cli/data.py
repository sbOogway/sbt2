from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from sbt2.cli import tables
from sbt2.cli.options import DAY, data_option, failing
from sbt2.core import data
from sbt2.core.config import Root

STATUS_HEADER = ("instrument", "type", "first", "last", "days", "gaps", "known gaps")

app = typer.Typer(no_args_is_help=True, help="Inspect the catalog.")


@app.command()
def status(
    data_root: Annotated[
        Path, data_option("Reads PATH/catalog and PATH/known_gaps.toml.")
    ],
    start: Annotated[
        datetime | None,
        typer.Option(formats=DAY, help="Check every day from this UTC day."),
    ] = None,
    end: Annotated[
        datetime | None,
        typer.Option(formats=DAY, help="Check every day up to this UTC day, included."),
    ] = None,
) -> None:
    """Show the symbols, data types and days in the catalog, and flag gaps."""
    root = Root(data_root)
    with failing("status of %s", root.catalog):
        window = _window(start, end)
        catalog = data.Catalog(root.catalog)
        holdings = catalog.status(data.known_gaps(root.known_gaps), window)
    typer.echo(_status_table(holdings))


def _window(start: datetime | None, end: datetime | None) -> data.Window | None:
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise ValueError("give both --start and --end, or neither")
    return data.Window.of_days(start.date(), end.date())


def _status_table(holdings: tuple[data.Holding, ...]) -> str:
    if not holdings:
        return "the catalog is empty"
    return tables.table(STATUS_HEADER, [_status_row(each) for each in holdings])


def _status_row(holding: data.Holding) -> tuple[str, ...]:
    return (
        str(holding.instrument_id),
        holding.data_type.__name__,
        holding.first.isoformat(),
        holding.last.isoformat(),
        str(holding.days),
        _day_ranges(holding.gaps),
        _day_ranges(holding.known_gaps),
    )


def _day_ranges(days: tuple[date, ...]) -> str:
    """Days as comma-separated runs of consecutive days, e.g. ``a..b,c``."""
    if not days:
        return "-"
    runs: list[list[date]] = []
    for day in days:
        if runs and day - runs[-1][-1] == timedelta(days=1):
            runs[-1].append(day)
        else:
            runs.append([day])
    return ",".join(_day_run(each) for each in runs)


def _day_run(days: list[date]) -> str:
    if len(days) == 1:
        return days[0].isoformat()
    return f"{days[0].isoformat()}..{days[-1].isoformat()}"
