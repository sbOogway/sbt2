from collections.abc import Iterator

import pytest
from fake_source import FakeApi
from file_server import FileServer, file_server


@pytest.fixture
def files() -> Iterator[FileServer]:
    with file_server() as server:
        yield server


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()
