import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from nautilus_trader.model import InstrumentId, NautilusDataType


def canonical_json(document: Any) -> str:
    """JSON with sorted keys, enums by name and decimals as strings."""
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), default=_primitive
    )


def canonical_hash(document: Any) -> str:
    """SHA-256 of the document's canonical JSON."""
    return hashlib.sha256(canonical_json(document).encode()).hexdigest()


def _primitive(value: Any) -> Any:
    if isinstance(value, Decimal | InstrumentId | NautilusDataType):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    raise TypeError(f"no canonical form for {value!r}")
