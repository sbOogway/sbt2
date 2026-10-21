from pathlib import Path

import pytest
from google.protobuf.struct_pb2 import Value
from results_kit import ask

from sbt2 import data
from sbt2.core.config import Root
from sbt2.protocol.v1.config_pb2 import (
    AddKnownGaps,
    KnownGap,
    ListKnownGaps,
    ListModelKinds,
    ModelArgument,
    ModelParameter,
    ParameterType,
    RemoveKnownGaps,
)
from sbt2.protocol.v1.envelope_pb2 import ClientMessage
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server import Handler
from sbt2.server.config import routes


def config_routes(path: Path) -> dict[str, Handler]:
    return routes(Root(path / "data"))


TRADES = KnownGap(
    source="bybit", symbol="BTCUSDT", data_type="trades", day="2020-03-25"
)
CANDLES = KnownGap(
    source="bybit", symbol="ETHUSDT", data_type="candles", day="2020-03-26"
)


def gaps_listed(handlers: dict[str, Handler]) -> list[KnownGap]:
    [reply] = ask(
        handlers, ClientMessage(request_id=1, list_known_gaps=ListKnownGaps())
    )
    return list(reply.known_gaps.gaps)


@pytest.mark.integration
def test_known_gaps_add_list_and_remove_round_trip(tmp_path: Path) -> None:
    handlers = config_routes(tmp_path)
    assert gaps_listed(handlers) == []

    [added] = ask(
        handlers,
        ClientMessage(
            request_id=2, add_known_gaps=AddKnownGaps(gaps=[TRADES, CANDLES])
        ),
    )
    assert added.WhichOneof("body") == "config_written"
    assert gaps_listed(handlers) == [TRADES, CANDLES]
    assert len(data.known_gaps(Root(tmp_path / "data").known_gaps)) == 2

    [removed] = ask(
        handlers,
        ClientMessage(request_id=3, remove_known_gaps=RemoveKnownGaps(gaps=[TRADES])),
    )
    assert removed.WhichOneof("body") == "config_written"
    assert gaps_listed(handlers) == [CANDLES]


@pytest.mark.unit
@pytest.mark.parametrize(
    "gap",
    [
        KnownGap(source="nope", symbol="BTCUSDT", data_type="trades", day="2020-03-25"),
        KnownGap(
            source="bybit", symbol="BTCUSDT", data_type="quotes", day="2020-03-25"
        ),
        KnownGap(
            source="bybit", symbol="BTCUSDT", data_type="trades", day="25/03/2020"
        ),
    ],
    ids=["unknown-source", "unknown-data-type", "bad-day"],
)
def test_an_invalid_known_gap_answers_invalid_argument(
    tmp_path: Path, gap: KnownGap
) -> None:
    handlers = config_routes(tmp_path)

    [reply] = ask(
        handlers,
        ClientMessage(request_id=2, add_known_gaps=AddKnownGaps(gaps=[TRADES, gap])),
    )

    assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_ARGUMENT
    assert reply.error.message
    assert gaps_listed(handlers) == []


@pytest.mark.unit
def test_list_model_kinds_answers_each_kind_with_its_parameters(
    tmp_path: Path,
) -> None:
    [reply] = ask(
        config_routes(tmp_path),
        ClientMessage(request_id=4, list_model_kinds=ListModelKinds()),
    )

    arguments = {each.argument: each for each in reply.model_kinds.arguments}
    assert set(arguments) == {
        ModelArgument.MODEL_ARGUMENT_FEE_MODEL,
        ModelArgument.MODEL_ARGUMENT_FILL_MODEL,
        ModelArgument.MODEL_ARGUMENT_LATENCY_MODEL,
        ModelArgument.MODEL_ARGUMENT_MARGIN_MODEL,
        ModelArgument.MODEL_ARGUMENT_MODULES,
    }
    fees = {
        kind.name: kind
        for kind in arguments[ModelArgument.MODEL_ARGUMENT_FEE_MODEL].kinds
    }
    assert set(fees) == {"capped_option", "fixed", "maker_taker"}
    assert list(fees["fixed"].parameters) == [
        ModelParameter(
            name="commission", type=ParameterType.PARAMETER_TYPE_STRING, required=True
        ),
        ModelParameter(
            name="charge_commission_once", type=ParameterType.PARAMETER_TYPE_BOOLEAN
        ),
    ]
    [fill] = arguments[ModelArgument.MODEL_ARGUMENT_FILL_MODEL].kinds
    assert fill.parameters[0] == ModelParameter(
        name="prob_fill_on_limit",
        type=ParameterType.PARAMETER_TYPE_NUMBER,
        default=Value(number_value=1.0),
    )
    assert list(arguments[ModelArgument.MODEL_ARGUMENT_LATENCY_MODEL].kinds) == []
