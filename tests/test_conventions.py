from collections.abc import Callable

import pytest
from google.protobuf.descriptor_pb2 import FileDescriptorSet

import conventions


@pytest.mark.parametrize("rule", conventions.RULES, ids=lambda rule: rule.__name__)
def test_protocol_follows(rule: Callable[[FileDescriptorSet], list[str]], fds: FileDescriptorSet):
    assert rule(fds) == []


# each rule's throwaway .proto that breaks it once, and the violation it reports
BREAKING = [
    pytest.param(
        conventions.no_floats,
        "message Quote { double price = 1; }",
        ["sbt2.protocol.v1.Quote.price is a TYPE_DOUBLE"],
        id="no_floats-double",
    ),
    pytest.param(
        conventions.no_floats,
        "message Fill { message Leg { float qty = 1; } }",
        ["sbt2.protocol.v1.Fill.Leg.qty is a TYPE_FLOAT"],
        id="no_floats-nested-float",
    ),
    pytest.param(
        conventions.timestamps,
        "message Order { int64 created_at = 1; }",
        ["sbt2.protocol.v1.Order.created_at is not a google.protobuf.Timestamp"],
        id="timestamps-at",
    ),
    pytest.param(
        conventions.timestamps,
        "message Tick { string ts_exchange = 1; uint64 timestamp = 2; string close_time = 3; }",
        [
            "sbt2.protocol.v1.Tick.ts_exchange is not a google.protobuf.Timestamp",
            "sbt2.protocol.v1.Tick.timestamp is not a google.protobuf.Timestamp",
            "sbt2.protocol.v1.Tick.close_time is not a google.protobuf.Timestamp",
        ],
        id="timestamps-time-ts-timestamp",
    ),
    pytest.param(
        conventions.envelopes,
        "message ClientMessage { uint64 request_id = 2; oneof body { string ping = 3; } }",
        ["sbt2.protocol.v1.ClientMessage does not keep request_id as field 1"],
        id="envelopes-request-id",
    ),
    pytest.param(
        conventions.envelopes,
        "message ServerMessage {\n"
        "  uint64 request_id = 1;\n"
        "  uint64 subscription_id = 2;\n"
        "  optional string trace = 3;\n"
        "  oneof body { string pong = 4; }\n"
        "}",
        ["sbt2.protocol.v1.ServerMessage.trace is outside the oneof body"],
        id="envelopes-outside-body",
    ),
    pytest.param(
        conventions.envelopes,
        "message ClientMessage {\n"
        "  uint64 request_id = 1;\n"
        "  uint64 subscription_id = 2;\n"
        "  oneof body { string ping = 3; }\n"
        "}",
        ["sbt2.protocol.v1.ClientMessage.subscription_id is outside the oneof body"],
        id="envelopes-client-subscription",
    ),
    pytest.param(
        conventions.enum_zero_values,
        "enum OrderSide { ORDER_SIDE_NONE = 0; ORDER_SIDE_BUY = 1; }",
        ["OrderSide's zero value is ORDER_SIDE_NONE, not ORDER_SIDE_UNSPECIFIED"],
        id="enum_zero_values",
    ),
]


@pytest.mark.parametrize(("rule", "body", "violations"), BREAKING)
def test_rule_catches(
    rule: Callable[[FileDescriptorSet], list[str]],
    body: str,
    violations: list[str],
    compile_proto: Callable[[str], FileDescriptorSet],
):
    assert rule(compile_proto(body)) == violations


def test_timestamp_satisfies_timestamps(compile_proto: Callable[[str], FileDescriptorSet]):
    fds = compile_proto(
        'import "google/protobuf/timestamp.proto";\n\n'
        "message Order { google.protobuf.Timestamp created_at = 1; }"
    )
    assert conventions.timestamps(fds) == []


def test_envelope_imports_catches(compile_proto: Callable[..., FileDescriptorSet]):
    fds = compile_proto(
        'import "sbt2/protocol/v1/envelope.proto";\n\n'
        "message Batch { repeated ClientMessage messages = 1; }",
        {"envelope.proto": "message ClientMessage { uint64 request_id = 1; }"},
    )
    assert conventions.envelope_imports(fds) == [
        "sbt2/protocol/v1/test.proto imports sbt2/protocol/v1/envelope.proto"
    ]
