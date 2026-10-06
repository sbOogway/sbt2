import pandas as pd

from sbt2.core import results as core
from sbt2.core.config import Root
from sbt2.data import Catalog
from sbt2.protocol.v1 import results_pb2 as wire
from sbt2.server.results.encoding import (
    InvalidArgumentError,
    benchmark_choice,
    resolved_benchmark,
)

_FIELDS: dict[wire.PanelKind.ValueType, str] = {
    wire.PANEL_KIND_RETURNS: "returns",
    wire.PANEL_KIND_BENCHMARK_RETURNS: "benchmark_returns",
    wire.PANEL_KIND_DRAWDOWN: "drawdown",
    wire.PANEL_KIND_MONTHLY_RETURNS: "monthly_returns",
    wire.PANEL_KIND_YEARLY_RETURNS: "yearly_returns",
    wire.PANEL_KIND_ROLLING_SHARPE: "rolling_sharpe",
}


class Panels:
    """The panel series of a run's tearsheet, calculated by core on each call."""

    def __init__(self, root: Root, store: core.ResultStore) -> None:
        self._root = root
        self._store = store

    def table(self, selected: wire.GetPanel) -> pd.DataFrame:
        """The selected panel as the columns ``ts`` and ``value``."""
        if selected.kind not in _FIELDS:
            raise InvalidArgumentError
        run = self._store.stored_run(selected.run_id)
        benchmark = None
        if selected.kind == wire.PANEL_KIND_BENCHMARK_RETURNS:
            benchmark = resolved_benchmark(run, benchmark_choice(selected.benchmark))
        priced = run.priced(Catalog(self._root.catalog))
        series = getattr(
            core.tearsheet_panels(priced, benchmark), _FIELDS[selected.kind]
        )
        return pd.DataFrame({"ts": series.index, "value": series.to_numpy()})
