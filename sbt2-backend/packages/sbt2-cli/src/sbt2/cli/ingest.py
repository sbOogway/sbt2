from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from sbt2 import data
from sbt2.cli import progress
from sbt2.cli.options import DAY, data_option, failing, logger
from sbt2.core.config import Root

app = typer.Typer()


@app.command()
def ingest(
    source: Annotated[str, typer.Option(help="The source the raw files came from.")],
    symbol: Annotated[list[str], typer.Option(help="Repeat for several.")],
    start: Annotated[datetime, typer.Option(formats=DAY, help="The first UTC day.")],
    end: Annotated[
        datetime, typer.Option(formats=DAY, help="The last UTC day, included.")
    ],
    data_root: Annotated[
        Path,
        data_option("Reads PATH/raw and PATH/known_gaps.toml, writes PATH/catalog."),
    ],
    data_type: Annotated[
        list[str] | None,
        typer.Option(
            "--type",
            help="A nautilus data type the source serves; repeat for several. "
            "Default: all of them.",
        ),
    ] = None,
    reingest: Annotated[
        bool,
        typer.Option(
            help="Replace the catalog's instrument with a newer snapshot that "
            "differs, and rebuild its days."
        ),
    ] = False,
) -> None:
    """Write a source's raw files for a range of days into the catalog."""
    root = Root(data_root)
    options = data.IngestOptions(root.raw, root.catalog)
    with failing("ingest from %s", source):
        days = data.DayRange(
            tuple(symbol), start.date(), end.date(), tuple(data_type or ())
        )
        request = data.IngestRequest(days, reingest)
        tally = _ingest(data.source(source, root.known_gaps), request, options)
    _log_summary(tally)


def _ingest(
    adapter: data.Source, request: data.IngestRequest, options: data.IngestOptions
) -> data.Tally[data.DayResult]:
    with progress.bar("ingest") as bar:
        return data.ingest(adapter, request, replace(options, progress=bar))


def _log_summary(tally: data.Tally[data.DayResult]) -> None:
    for each in tally.having(data.IngestOutcome.MISSING):
        day = each.day
        logger.warning(
            "no raw file: %s %s %s", day.symbol, day.data, day.day.isoformat()
        )
    counts = (f"{len(tally.having(each))} {each}" for each in data.IngestOutcome)
    logger.info("days: %s", ", ".join(counts))
