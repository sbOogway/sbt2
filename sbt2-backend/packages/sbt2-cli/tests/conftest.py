import pytest
from cli_launchers import uncapped
from launchers import PlainLauncher


@pytest.fixture(autouse=True)
def launcher(monkeypatch: pytest.MonkeyPatch) -> PlainLauncher:
    return uncapped(monkeypatch)
