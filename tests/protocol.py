"""Compiles .proto files with buf and loads them for the tests."""

import subprocess
from pathlib import Path

from google.protobuf import descriptor_pb2

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "sbt2.protocol.v1"


def build(module: Path, out: Path) -> descriptor_pb2.FileDescriptorSet:
    """Compiles every .proto under module, with its imports, into one FileDescriptorSet."""
    image = out / "image.binpb"
    subprocess.run(["buf", "build", str(module), "-o", str(image)], check=True)
    return descriptor_pb2.FileDescriptorSet.FromString(image.read_bytes())
