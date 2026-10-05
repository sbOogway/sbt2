import os
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomli_w


def read_toml(path: Path) -> dict[str, Any]:
    """The document in ``path``; an empty one when the file is missing."""
    if not path.exists():
        return {}
    with path.open("rb") as file:
        return tomllib.load(file)


def write_toml(path: Path, document: Mapping[str, Any]) -> None:
    """Replace ``path`` with ``document`` at once, so a reader sees either the old
    file or the new one, and a failed write leaves the old file.

    Raises ``TypeError`` before writing when TOML cannot hold a value.
    """
    text = tomli_w.dumps(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        staged.replace(path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
