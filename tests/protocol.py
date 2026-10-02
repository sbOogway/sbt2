"""Compiles .proto files with buf and loads them for the tests."""

import subprocess
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import Message

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "sbt2.protocol.v1"


def build(module: Path, out: Path) -> descriptor_pb2.FileDescriptorSet:
    """Compiles every .proto under module, with its imports, into one FileDescriptorSet."""
    image = out / "image.binpb"
    subprocess.run(["buf", "build", str(module), "-o", str(image)], check=True)
    return descriptor_pb2.FileDescriptorSet.FromString(image.read_bytes())


def message_classes(fds: descriptor_pb2.FileDescriptorSet) -> dict[str, type[Message]]:
    """The message classes of every type in fds, by full name, standing in for generated code."""
    pool = descriptor_pool.DescriptorPool()
    for file in fds.file:
        pool.Add(file)
    names = [
        f"{file.package}.{message.name}" for file in fds.file for message in file.message_type
    ]
    return {name: message_factory.GetMessageClass(pool.FindMessageTypeByName(name)) for name in names}
