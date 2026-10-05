from pathlib import Path
from typing import Any

import pytest
from google.protobuf.struct_pb2 import Struct, Value
from results_kit import ask, ask_together

from sbt2.core import data, spec
from sbt2.core.config import ConfigFolder, Root
from sbt2.protocol.v1.config_pb2 import (
    AddKnownGaps,
    AssetClass,
    DeleteVenueProfile,
    InstrumentClass,
    KnownGap,
    ListKnownGaps,
    ListModelKinds,
    ListVenueProfiles,
    ModelArgument,
    ModelParameter,
    ParameterType,
    PutVenueProfile,
    RemoveKnownGaps,
    VenueModel,
    VenueProfile,
)
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server import Handler
from sbt2.server.config import routes

SPEC = """
strategy = "spec_strategies:MinuteLookback"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
period = [2024-01-01, 2024-03-01]
split = { validation_start = 2024-02-01, test_start = 2024-02-15 }
part = "train"
venue = "linear"
capital = "10000 USDT"
"""


def struct(values: dict[str, Any]) -> Struct:
    message = Struct()
    message.update(values)
    return message


def profile(name: str = "linear") -> VenueProfile:
    return VenueProfile(
        name=name,
        venue="BYBIT",
        source="bybit",
        asset_class=AssetClass.ASSET_CLASS_CRYPTOCURRENCY,
        instrument_class=InstrumentClass.INSTRUMENT_CLASS_SWAP,
        fee_model=VenueModel(
            kind="maker_taker",
            config=struct({"maker_rate": "0.0002", "taker_rate": "0.00055"}),
        ),
        fill_model=VenueModel(kind="default"),
        arguments=struct({"default_leverage": 3, "liquidation_enabled": False}),
    )


def config_routes(path: Path) -> dict[str, Handler]:
    return routes(ConfigFolder(path / "config"), Root(path / "data"))


def listed(handlers: dict[str, Handler]) -> list[VenueProfile]:
    [reply] = ask(
        handlers,
        ClientMessage(request_id=1, list_venue_profiles=ListVenueProfiles()),
    )
    return list(reply.venue_profiles.profiles)


def put(handlers: dict[str, Handler], each: VenueProfile) -> ServerMessage:
    [reply] = ask(
        handlers,
        ClientMessage(request_id=2, put_venue_profile=PutVenueProfile(profile=each)),
    )
    return reply


@pytest.mark.unit
def test_venue_profiles_of_an_empty_config_folder_are_an_empty_list(
    tmp_path: Path,
) -> None:
    [reply] = ask(
        config_routes(tmp_path),
        ClientMessage(request_id=7, list_venue_profiles=ListVenueProfiles()),
    )

    assert reply.request_id == 7
    assert reply.WhichOneof("body") == "venue_profiles"
    assert list(reply.venue_profiles.profiles) == []


@pytest.mark.integration
def test_put_venue_profile_round_trips_typed_fields_models_and_struct_arguments(
    tmp_path: Path,
) -> None:
    handlers = config_routes(tmp_path)

    reply = put(handlers, profile())

    assert reply.WhichOneof("body") == "config_written"
    assert listed(handlers) == [profile()]


@pytest.mark.integration
def test_a_put_venue_profile_is_resolved_by_the_next_run(tmp_path: Path) -> None:
    put(config_routes(tmp_path), profile())
    spec_file = tmp_path / "spec.toml"
    spec_file.write_text(SPEC)

    [run] = spec.load(spec_file, ConfigFolder(tmp_path / "config").venues)

    assert run.source == "bybit"
    assert run.venue["default_leverage"] == 3


@pytest.mark.unit
def test_an_invalid_venue_profile_answers_invalid_argument_with_core_message(
    tmp_path: Path,
) -> None:
    invalid = profile()
    invalid.fee_model.kind = "tiered"

    reply = put(config_routes(tmp_path), invalid)

    assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_ARGUMENT
    assert reply.error.message == "no fee_model kind tiered; known: fixed, maker_taker"


@pytest.mark.unit
def test_deleting_an_unknown_venue_profile_answers_not_found(tmp_path: Path) -> None:
    [reply] = ask(
        config_routes(tmp_path),
        ClientMessage(
            request_id=3, delete_venue_profile=DeleteVenueProfile(name="missing")
        ),
    )

    assert reply.error.code == ErrorCode.ERROR_CODE_NOT_FOUND
    assert "no venue profile missing" in reply.error.message


@pytest.mark.unit
def test_deleting_a_venue_profile_leaves_the_others(tmp_path: Path) -> None:
    handlers = config_routes(tmp_path)
    put(handlers, profile("kept"))
    put(handlers, profile("dropped"))

    [reply] = ask(
        handlers,
        ClientMessage(
            request_id=3, delete_venue_profile=DeleteVenueProfile(name="dropped")
        ),
    )

    assert reply.WhichOneof("body") == "config_written"
    assert [each.name for each in listed(handlers)] == ["kept"]


@pytest.mark.unit
def test_arguments_repeating_a_typed_field_answer_invalid_argument(
    tmp_path: Path,
) -> None:
    invalid = profile()
    invalid.arguments.update({"source": "other"})

    reply = put(config_routes(tmp_path), invalid)

    assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_ARGUMENT
    assert "source" in reply.error.message
    assert listed(config_routes(tmp_path)) == []


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
    assert set(fees) == {"fixed", "maker_taker"}
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


@pytest.mark.integration
def test_concurrent_profile_writes_lose_no_update(tmp_path: Path) -> None:
    handlers = config_routes(tmp_path)
    names = [f"profile-{each}" for each in range(8)]

    replies = ask_together(
        handlers,
        [
            ClientMessage(
                request_id=index + 1,
                put_venue_profile=PutVenueProfile(profile=profile(name)),
            )
            for index, name in enumerate(names)
        ],
    )

    assert all(reply.WhichOneof("body") == "config_written" for [reply] in replies)
    assert sorted(each.name for each in listed(handlers)) == names
