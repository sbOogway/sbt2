import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from nautilus_trader.model import InstrumentId, NautilusDataType


def canonical_hash(document: Any) -> str:
    """SHA-256 of canonical JSON: sorted keys, enums by name, decimals as strings."""
    text = json.dumps(
        document, sort_keys=True, separators=(",", ":"), default=_primitive
    )
    return hashlib.sha256(text.encode()).hexdigest()


def _primitive(value: Any) -> Any:
    if isinstance(value, Decimal | InstrumentId | NautilusDataType):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    raise TypeError(f"no canonical form for {value!r}")
