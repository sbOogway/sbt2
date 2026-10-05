import math
from collections.abc import Hashable, Mapping
from dataclasses import fields
from datetime import datetime

import pandas as pd

from sbt2.core import results, spec

HEADLINE = tuple(each.name for each in fields(results.HeadlineMetrics))


def table(header: tuple[str, ...], body: list[tuple[str, ...]]) -> str:
    """Rows of left-aligned columns, as wide as their widest cell."""
    rows = [header, *body]
    widths = [max(len(row[column]) for row in rows) for column in range(len(header))]
    return "\n".join(
        "  ".join(
            cell.ljust(width) for cell, width in zip(row, widths, strict=True)
        ).rstrip()
        for row in rows
    )


def frame_table(frame: pd.DataFrame, columns: tuple[str, ...]) -> str:
    """The frame's ``columns``, one row per record, cells as ``runs list``
    prints them."""
    records = frame.to_dict("records")
    return table(columns, [_row(each, columns) for each in records])


def part_tables(frame: pd.DataFrame, columns: tuple[str, ...]) -> str:
    """One table of the frame's ``columns`` per part, in split order, each under
    its part's name."""
    return "\n\n".join(
        f"{part}\n{frame_table(frame.loc[frame['part'] == part], columns)}"
        for part in spec.PARTS
        if (frame["part"] == part).any()
    )


def text(value: object) -> str:
    """A stored value as ``runs list`` and ``runs show`` print it."""
    if _missing(value):
        return "-"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _row(
    record: Mapping[Hashable, object], columns: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(_cell(record[column]) for column in columns)


def _cell(value: object) -> str:
    if isinstance(value, float) and not math.isnan(value):
        return f"{value:.4f}"
    return text(value)


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))
