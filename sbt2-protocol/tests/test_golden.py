"""Every golden fixture decodes to its textproto and re-encodes to the same bytes.

The .binpb files come from buf convert (Go), so this checks Python's protobuf against it;
checks/rust does the same for prost.
"""

from pathlib import Path

import pytest
from google.protobuf import text_format
from google.protobuf.descriptor_pb2 import FileDescriptorSet
from google.protobuf.message import Message

from protocol import PACKAGE, ROOT, message_classes

GOLDEN = ROOT / "golden"
HEADER = "# proto-message: "
FIXTURES = sorted(GOLDEN.rglob("*.textproto"))


def _load(text: Path, classes: dict[str, type[Message]]) -> tuple[Message, Message]:
    """The fixture's message parsed from its textproto, and decoded from its .binpb."""
    source = text.read_text()
    header = source.splitlines()[0]
    assert header.startswith(HEADER), f"{text} does not start with {HEADER!r}"
    cls = classes[header.removeprefix(HEADER)]
    return text_format.Parse(source, cls()), cls.FromString(text.with_suffix(".binpb").read_bytes())


@pytest.fixture(scope="session")
def classes(fds: FileDescriptorSet) -> dict[str, type[Message]]:
    return message_classes(fds)


@pytest.mark.unit
@pytest.mark.golden
@pytest.mark.parametrize("text", FIXTURES, ids=lambda text: str(text.relative_to(GOLDEN)))
def test_fixture_round_trips(text: Path, classes: dict[str, type[Message]]):
    parsed, decoded = _load(text, classes)
    assert decoded == parsed
    # deterministic, as buf convert is: map entries sorted by key
    encoded = decoded.SerializeToString(deterministic=True)
    assert encoded == text.with_suffix(".binpb").read_bytes()
    known = type(decoded).FromString(encoded)
    known.DiscardUnknownFields()
    assert known.SerializeToString(deterministic=True) == encoded, "the .binpb has unknown fields"


@pytest.mark.unit
@pytest.mark.golden
@pytest.mark.parametrize("envelope", ["ClientMessage", "ServerMessage"])
def test_every_body_has_a_fixture(envelope: str, classes: dict[str, type[Message]]):
    name = f"{PACKAGE}.{envelope}"
    bodies = {field.name for field in classes[name].DESCRIPTOR.oneofs_by_name["body"].fields}
    covered = set()
    for text in FIXTURES:
        parsed, _ = _load(text, classes)
        if parsed.DESCRIPTOR.full_name == name:
            covered.add(parsed.WhichOneof("body"))
    assert bodies - covered == set(), f"{envelope} bodies without a golden fixture"
