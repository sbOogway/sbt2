"""What every area that runs an uploaded module in a process of its own shares."""

import importlib.util
import keyword
import sys
from collections.abc import Mapping

SERVER_VARIABLES = "SBT2_SERVER_"


def clean_environment(server: Mapping[str, str]) -> dict[str, str]:
    """The environment of ``server`` without its ``SBT2_SERVER_*`` variables,
    the API token among them."""
    return {
        key: value
        for key, value in server.items()
        if not key.startswith(SERVER_VARIABLES)
    }


def module_name_problem(name: str) -> str | None:
    """Why ``name`` cannot name an uploaded module, or ``None`` when it can."""
    if not name.isidentifier() or keyword.iskeyword(name):
        return f"the module name {name!r} is not an identifier"
    if _importable(name):
        return f"the server has a module called {name}; give yours another name"
    return None


def _importable(name: str) -> bool:
    """Whether the server's image has a module of this name; ``find_spec`` runs
    no module's code."""
    if name in sys.modules:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except ImportError, ValueError:
        return True
