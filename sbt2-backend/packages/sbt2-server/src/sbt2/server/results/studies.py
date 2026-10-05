from collections.abc import Iterator

from sbt2.core import results as core
from sbt2.protocol.v1 import results_pb2 as wire


def study_summaries(store: core.ResultStore) -> Iterator[wire.StudySummary]:
    for row in core.study_list(store).to_dict("records"):
        yield wire.StudySummary(
            name=row["study"], strategy=row["strategy"], run_count=row["runs"]
        )
