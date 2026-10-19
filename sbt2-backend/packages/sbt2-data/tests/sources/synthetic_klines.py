"""A UTC day of synthetic 1-minute klines (2025-01-01) in the shape each exchange
sends them, so the paging tests need no recorded day.

Minute ``n`` opens at ``90000 + n``, highs 5 above, lows 5 below, closes 1 above,
and trades ``1 + n % 5`` units.
"""

import hashlib
import io
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

DAY_START_MS = 1_735_689_600_000
MINUTE_MS = 60_000
MINUTES = 1440
OKX_PAGE = 100
COINBASE_PAGE = 288


def opened_ms(n: int) -> int:
    return DAY_START_MS + n * MINUTE_MS


def _prices(n: int, decimals: int) -> tuple[str, str, str, str]:
    base = 90000 + n
    o, h, low, c = (
        f"{each:.{decimals}f}" for each in (base, base + 5, base - 5, base + 1)
    )
    return o, h, low, c


def _units(n: int) -> int:
    return 1 + n % 5


def binance_zip() -> tuple[bytes, bytes]:
    """The dump of the day, and its checksum file."""
    header = "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    header += "taker_buy_volume,taker_buy_quote_volume,ignore"
    rows = [header]
    for n in range(MINUTES):
        o, h, low, c = _prices(n, 2)
        rows.append(
            f"{opened_ms(n)},{o},{h},{low},{c},{_units(n)}.000,"
            f"{opened_ms(n) + MINUTE_MS - 1},0,1,0,0,0"
        )
    name = "BTCUSDT-1m-2025-01-01.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name.replace(".zip", ".csv"), "\n".join(rows) + "\n")
    dump = buffer.getvalue()
    return dump, f"{hashlib.sha256(dump).hexdigest()}  {name}\n".encode()


def okx_pages(symbol: str) -> list[dict[str, Any]]:
    """The recorded-response entries for the pages OKX answers, newest first."""
    entries = []
    after = opened_ms(MINUTES)
    for page in range(-(-MINUTES // OKX_PAGE)):
        top = MINUTES - 1 - page * OKX_PAGE
        rows = []
        for n in range(top, max(top - OKX_PAGE, -1), -1):
            o, h, low, c = _prices(n, 1)
            rows.append(
                [str(opened_ms(n)), o, h, low, c, str(_units(n)), "0", "0", "1"]
            )
        query = {
            "instId": symbol,
            "bar": "1m",
            "before": DAY_START_MS - 1,
            "after": after,
            "limit": OKX_PAGE,
        }
        target = f"/api/v5/market/history-candles?{urlencode(query)}"
        entries.append(
            {"request": target, "response": {"code": "0", "msg": "", "data": rows}}
        )
        after = int(rows[-1][0])
    return entries


def coinbase_pages(symbol: str) -> list[dict[str, Any]]:
    """The recorded-response entries for the five pages Coinbase answers."""
    first = datetime(2025, 1, 1, tzinfo=UTC)
    entries = []
    for page in range(MINUTES // COINBASE_PAGE):
        low = page * COINBASE_PAGE
        start = first + timedelta(minutes=low)
        end = start + timedelta(minutes=COINBASE_PAGE - 1)
        query = {
            "granularity": "ONE_MINUTE",
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        rows = []
        for n in range(low + COINBASE_PAGE - 1, low - 1, -1):
            o, h, lo, c = _prices(n, 1)
            opened = first + timedelta(minutes=n)
            rows.append(
                {
                    "start": opened.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "open": o,
                    "high": h,
                    "low": lo,
                    "close": c,
                    "volume": f"{_units(n)}.5",
                }
            )
        target = f"/api/v1/instruments/{symbol}/candles?{urlencode(query)}"
        entries.append({"request": target, "response": {"aggregations": rows}})
    return entries


def deribit_chart(symbol: str) -> dict[str, Any]:
    """The recorded-response entry for the day's chart data."""
    columns = [_prices(n, 1) for n in range(MINUTES)]
    result = {
        "ticks": [opened_ms(n) for n in range(MINUTES)],
        "open": [float(each[0]) for each in columns],
        "high": [float(each[1]) for each in columns],
        "low": [float(each[2]) for each in columns],
        "close": [float(each[3]) for each in columns],
        "volume": [_units(n) * 0.5 for n in range(MINUTES)],
        "cost": [0.0] * MINUTES,
        "status": "ok",
    }
    query = {
        "instrument_name": symbol,
        "start_timestamp": DAY_START_MS,
        "end_timestamp": DAY_START_MS + 86_400_000 - 1,
        "resolution": 1,
    }
    target = f"/api/v2/public/get_tradingview_chart_data?{urlencode(query)}"
    return {"request": target, "response": {"result": result}}
