"""The traces and panel titles of a plotly figure, read back from its HTML."""

import base64
import json
from dataclasses import dataclass
from typing import Any

import numpy as np

_NEW_PLOT = "Plotly.newPlot("


@dataclass(frozen=True)
class Plotted:
    traces: list[dict[str, Any]]
    titles: list[str]

    def named(self, name: str) -> list[dict[str, Any]]:
        return [each for each in self.traces if each.get("name") == name]

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [each for each in self.traces if each.get("type") == kind]

    def trace(self, name: str) -> dict[str, Any]:
        [trace] = self.named(name)
        return trace


def plotted(html: str) -> Plotted:
    """Arrays plotly packs as base64 come back as numpy arrays."""
    decoder = json.JSONDecoder()
    rest = html[html.index(_NEW_PLOT) + len(_NEW_PLOT) :]
    _, rest = _next_argument(decoder, rest)
    traces, rest = _next_argument(decoder, rest)
    layout, _ = _next_argument(decoder, rest)
    titles = [each["text"] for each in layout.get("annotations", [])]
    return Plotted([_unpacked(each) for each in traces], titles)


def _next_argument(decoder: json.JSONDecoder, text: str) -> tuple[Any, str]:
    value, end = decoder.raw_decode(text.lstrip())
    return value, text.lstrip()[end:].lstrip().removeprefix(",")


def _unpacked(value: Any) -> Any:
    if isinstance(value, dict) and "bdata" in value:
        flat = np.frombuffer(base64.b64decode(value["bdata"]), dtype=value["dtype"])
        shape = str(value.get("shape", len(flat)))
        return flat.reshape([int(each) for each in shape.split(",")])
    if isinstance(value, dict):
        return {key: _unpacked(each) for key, each in value.items()}
    if isinstance(value, list):
        return [_unpacked(each) for each in value]
    return value
