from datetime import UTC, datetime
from typing import Any

import pytest
from runs_kit import spec_message

from sbt2.protocol.v1.runs_pb2 import SpecFile
from sbt2.server.runs.encoding import InvalidArgumentError, spec_table
from sbt2.server.runs.wire import (
    Conflict,
    ConflictKind,
    Rejected,
    Rejection,
    decode,
    encode,
)

TABLE: dict[str, Any] = {
    "strategy": "trend:Trend",
    "instruments": ["BTCUSDT-LINEAR.BYBIT", "ETHUSDT-LINEAR.BYBIT"],
    "period": [
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 3, 1, 12, 30, tzinfo=UTC),
    ],
    "venue": "linear",
    "capital": "10000 USDT",
    "part": ["train", "validation"],
    "split": {"validation_start": "2024-02-01", "test_start": "2024-02-15"},
    "seed": 7,
    "equity_interval": "30m",
    "liquidation": False,
    "bars": "candles",
    "params": {
        "lookback": [30, 60],
        "bar": "1-HOUR-LAST",
        "quantity": "0.100",
        "scale": 0.5,
        "nested": {"depth": 2},
    },
    "risk": {"drawdown_limit": "0.2", "max_order_submit_rate": "100/00:00:01"},
    "study": "trend-btc",
}
REQUIRED = ("strategy", "instruments", "period", "venue", "capital")


@pytest.mark.unit
def test_spec_file_message_round_trips_to_the_spec_table() -> None:
    assert spec_table(spec_message(TABLE)) == TABLE


@pytest.mark.unit
def test_spec_file_message_keeps_integral_numbers_as_integers() -> None:
    table = spec_table(spec_message(TABLE))

    assert isinstance(table["seed"], int)
    assert isinstance(table["params"]["lookback"][0], int)
    assert isinstance(table["params"]["nested"]["depth"], int)
    assert isinstance(table["params"]["scale"], float)


@pytest.mark.unit
def test_spec_file_message_round_trips_a_fraction_split() -> None:
    table = {**TABLE, "split": {"validation": 0.2, "test": 0.1}}

    assert spec_table(spec_message(table))["split"] == {"validation": 0.2, "test": 0.1}


@pytest.mark.unit
def test_spec_file_message_leaves_out_what_it_does_not_set() -> None:
    table = {key: TABLE[key] for key in REQUIRED}

    assert spec_table(spec_message(table)) == table


@pytest.mark.unit
@pytest.mark.parametrize("key", REQUIRED)
def test_spec_file_message_with_bad_values_is_invalid_argument(key: str) -> None:
    table = {each: value for each, value in TABLE.items() if each != key}

    with pytest.raises(InvalidArgumentError, match=key):
        spec_table(spec_message(table))


@pytest.mark.unit
def test_spec_file_message_with_a_half_set_period_is_invalid_argument() -> None:
    message = SpecFile()
    message.CopyFrom(spec_message(TABLE))
    message.period.ClearField("end_at")

    with pytest.raises(InvalidArgumentError, match="period"):
        spec_table(message)


@pytest.mark.unit
def test_a_rejection_keeps_its_study_conflict() -> None:
    conflicts = [
        Conflict(ConflictKind.CONTEXT, context_keys=("capital", "period")),
        Conflict(ConflictKind.CODE),
        Conflict(ConflictKind.DUPLICATE_RUN, run_id="run-1"),
    ]
    for conflict in conflicts:
        rejected = Rejected(Rejection.INVALID, "no", conflict)

        assert decode(encode(rejected)) == rejected

    plain = Rejected(Rejection.INVALID, "no")
    assert decode(encode(plain)) == plain
    assert decode('{"type": "rejected", "kind": "invalid", "message": "no"}') == plain
