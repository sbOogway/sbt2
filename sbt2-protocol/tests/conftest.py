from pathlib import Path

import pytest
from google.protobuf.descriptor_pb2 import FileDescriptorSet

from protocol import ROOT, build


@pytest.fixture(scope="session")
def fds(tmp_path_factory: pytest.TempPathFactory) -> FileDescriptorSet:
    """This repo's .proto files, compiled by buf."""
    return build(ROOT, tmp_path_factory.mktemp("image"))


@pytest.fixture
def compile_proto(tmp_path: Path):
    """Compiles a throwaway sbt2/protocol/v1/test.proto holding body, next to the others files."""

    def compile_(body: str, others: dict[str, str] | None = None) -> FileDescriptorSet:
        package = tmp_path / "module/sbt2/protocol/v1"
        package.mkdir(parents=True)
        for name, content in {"test.proto": body, **(others or {})}.items():
            (package / name).write_text(
                f'syntax = "proto3";\n\npackage sbt2.protocol.v1;\n\n{content}\n'
            )
        return build(package.parent.parent.parent, tmp_path)

    return compile_
