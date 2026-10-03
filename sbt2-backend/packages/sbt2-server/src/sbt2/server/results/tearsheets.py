import asyncio
import hashlib
import os
import tempfile
from importlib.metadata import version
from pathlib import Path
from weakref import WeakValueDictionary

from sbt2.core import results as core
from sbt2.core.config import Root
from sbt2.core.data import Catalog
from sbt2.server import offloaded
from sbt2.server.results.encoding import Choice, InvalidArgumentError


class Tearsheets:
    """Renders each run's tearsheets once per benchmark choice and server
    version, cached in the run's folder; completed runs never change."""

    def __init__(self, root: Root, store: core.ResultStore) -> None:
        self._root = root
        self._store = store
        self._version = version("sbt2-server")
        self._locks: WeakValueDictionary[Path, asyncio.Lock] = WeakValueDictionary()

    async def cached(self, run_id: str, choice: Choice) -> Path:
        """The HTML file of the run's tearsheet, rendered when not yet cached."""
        path = await offloaded(self._path)(run_id, choice)
        lock = self._locks.setdefault(path, asyncio.Lock())
        async with lock:
            if not await offloaded(path.exists)():
                await offloaded(self._render)(run_id, choice, path)
        return path

    def _path(self, run_id: str, choice: Choice) -> Path:
        self._store.load(run_id, "summary")
        key = "\n".join([self._version, *map(str, choice)])
        name = hashlib.sha256(key.encode()).hexdigest()[:32]
        return self._store.folder(run_id) / "tearsheets" / f"{name}.html"

    def _render(self, run_id: str, choice: Choice, path: Path) -> None:
        run = self._store.stored_run(run_id)
        benchmark = _benchmark(run, choice)
        priced = run.priced(Catalog(self._root.catalog))
        path.parent.mkdir(exist_ok=True)
        # the tearsheet's format follows the extension, so the staging file keeps it
        fd, name = tempfile.mkstemp(suffix=".html", dir=path.parent)
        os.close(fd)
        staging = Path(name)
        try:
            core.tearsheet(priced, staging, benchmark)
            staging.replace(path)
        finally:
            staging.unlink(missing_ok=True)


def _benchmark(run: core.StoredRun, choice: Choice) -> core.Benchmark | None:
    name, argument = choice
    if name is None:
        return run.benchmark()
    try:
        return run.benchmark(name, argument)
    except ValueError as invalid:
        raise InvalidArgumentError from invalid
