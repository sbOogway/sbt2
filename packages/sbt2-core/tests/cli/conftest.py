import pytest
from launchers import PlainLauncher, uncapped


@pytest.fixture(autouse=True)
def launcher(monkeypatch: pytest.MonkeyPatch) -> PlainLauncher:
    return uncapped(monkeypatch)
