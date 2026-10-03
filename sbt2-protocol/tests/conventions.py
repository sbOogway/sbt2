"""sbt2's protocol conventions that buf lint does not check, as rules over a FileDescriptorSet.

Each rule returns its violations, one line each, so that a test can show them all at once.
"""

import re
from collections.abc import Callable, Iterator

from google.protobuf.descriptor_pb2 import (
    DescriptorProto,
    EnumDescriptorProto,
    FieldDescriptorProto,
    FileDescriptorSet,
    FileDescriptorProto,
)

from protocol import PACKAGE

ENVELOPES = ("ClientMessage", "ServerMessage")
# fields of an envelope that live outside its oneof body, besides request_id
ENVELOPE_HEADERS = {"ServerMessage": {"subscription_id"}}
TIME_NAME = re.compile(r"(_at|_time)$|^timestamp$|^ts_")
TIMESTAMP = ".google.protobuf.Timestamp"


def _own_files(fds: FileDescriptorSet) -> Iterator[FileDescriptorProto]:
    """The files of this repo, without the well-known types buf includes as imports."""
    return (file for file in fds.file if not file.name.startswith("google/"))


def _messages(fds: FileDescriptorSet) -> Iterator[tuple[str, DescriptorProto]]:
    """Every message, nested ones included, with its full name."""

    def walk(prefix: str, messages: list[DescriptorProto]) -> Iterator[tuple[str, DescriptorProto]]:
        for message in messages:
            name = f"{prefix}.{message.name}"
            if not message.options.map_entry:
                yield name, message
            yield from walk(name, list(message.nested_type))

    for file in _own_files(fds):
        yield from walk(file.package, list(file.message_type))


def _enums(fds: FileDescriptorSet) -> Iterator[EnumDescriptorProto]:
    for file in _own_files(fds):
        yield from file.enum_type
    for _, message in _messages(fds):
        yield from message.enum_type


def no_floats(fds: FileDescriptorSet) -> list[str]:
    """Prices, quantities and money are decimal strings: no field is a double or float."""
    floats = {FieldDescriptorProto.TYPE_DOUBLE, FieldDescriptorProto.TYPE_FLOAT}
    return [
        f"{name}.{field.name} is a {FieldDescriptorProto.Type.Name(field.type)}"
        for name, message in _messages(fds)
        for field in message.field
        if field.type in floats
    ]


def timestamps(fds: FileDescriptorSet) -> list[str]:
    """A field named for a point in time is a google.protobuf.Timestamp."""
    return [
        f"{name}.{field.name} is not a google.protobuf.Timestamp"
        for name, message in _messages(fds)
        for field in message.field
        if TIME_NAME.search(field.name) and field.type_name != TIMESTAMP
    ]


def envelopes(fds: FileDescriptorSet) -> list[str]:
    """Each envelope keeps request_id as field 1, and its other fields in its oneof body."""
    violations = []
    for name, message in _messages(fds):
        package, _, short = name.rpartition(".")
        if package != PACKAGE or short not in ENVELOPES:
            continue
        fields = {field.number: field for field in message.field}
        first = fields.get(1)
        if first is None or first.name != "request_id":
            violations.append(f"{name} does not keep request_id as field 1")
        headers = {"request_id"} | ENVELOPE_HEADERS.get(short, set())
        oneofs = [oneof.name for oneof in message.oneof_decl]
        for field in message.field:
            in_body = field.HasField("oneof_index") and oneofs[field.oneof_index] == "body"
            if field.name not in headers and not in_body:
                violations.append(f"{name}.{field.name} is outside the oneof body")
    return violations


def enum_zero_values(fds: FileDescriptorSet) -> list[str]:
    """Every enum's zero value is <ENUM>_UNSPECIFIED."""
    violations = []
    for enum in _enums(fds):
        expected = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", enum.name).upper() + "_UNSPECIFIED"
        zero = next((value.name for value in enum.value if value.number == 0), None)
        if zero != expected:
            violations.append(f"{enum.name}'s zero value is {zero}, not {expected}")
    return violations


def envelope_imports(fds: FileDescriptorSet) -> list[str]:
    """No file imports envelope.proto, so area files can embed shared types without a cycle."""
    return [
        f"{file.name} imports {dependency}"
        for file in _own_files(fds)
        for dependency in file.dependency
        if dependency.endswith("/envelope.proto")
    ]


RULES: list[Callable[[FileDescriptorSet], list[str]]] = [
    no_floats,
    timestamps,
    envelopes,
    enum_zero_values,
    envelope_imports,
]
