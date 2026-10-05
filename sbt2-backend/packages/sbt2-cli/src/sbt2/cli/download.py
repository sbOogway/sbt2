from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from sbt2.cli import progress
from sbt2.cli.options import DAY, data_option, failing, logger
from sbt2.core import data
from sbt2.core.config import Root

app = typer.Typer()


@app.command()
def download(
    source: Annotated[str, typer.Option(help="The source to fetch from.")],
    symbol: Annotated[list[str], typer.Option(help="Repeat for several.")],
    start: Annotated[datetime, typer.Option(formats=DAY, help="The first UTC day.")],
    end: Annotated[
        datetime, typer.Option(formats=DAY, help="The last UTC day, included.")
    ],
    data_root: Annotated[
        Path, data_option("Reads PATH/known_gaps.toml, writes PATH/raw.")
    ],
    data_type: Annotated[
        list[str] | None,
        typer.Option(
            "--type",
            help="A nautilus data type the source serves; repeat for several. "
            "Default: all of them.",
        ),
    ] = None,
    concurrency: Annotated[int, typer.Option(min=1)] = 8,
    retries: Annotated[int, typer.Option(min=0, help="Per file.")] = 5,
) -> None:
    """Fetch a source's raw files for a range of days, and today's instruments."""
    root = Root(data_root)
    options = data.DownloadOptions(root.raw, concurrency, retries)
    with failing("download from %s", source):
        days = data.DayRange(
            tuple(symbol), start.date(), end.date(), tuple(data_type or ())
        )
        request = data.DownloadRequest(days)
        tally = _download(data.source(source, root.known_gaps), request, options)
    _log_summary(tally)
    if tally.having(data.Outcome.FAILED):
        raise typer.Exit(1)


def _download(
    adapter: data.Source, request: data.DownloadRequest, options: data.DownloadOptions
) -> data.Tally[data.FileResult]:
    with progress.download_bar() as bar:
        return data.download(adapter, request, replace(options, progress=bar))


def _log_summary(tally: data.Tally[data.FileResult]) -> None:
    for each in tally.having(data.Outcome.MISSING):
        logger.warning("missing at the source: %s", _described(each.item))
    for each in tally.having(data.Outcome.FAILED):
        logger.error("failed: %s: %s", _described(each.item), each.reason)
    counts = (f"{len(tally.having(each))} {each}" for each in data.Outcome)
    logger.info("files: %s", ", ".join(counts))


def _described(item: data.Item) -> str:
    return f"{item.symbol} {item.data} {item.day.isoformat()}"
