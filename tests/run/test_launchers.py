import pytest

from sbt2.run import SystemdScope, UnsupportedPlatformError, launcher_for


@pytest.mark.unit
def test_linux_gets_the_systemd_scope() -> None:
    assert isinstance(launcher_for("linux"), SystemdScope)


@pytest.mark.unit
def test_an_unserved_platform_names_the_known_ones() -> None:
    with pytest.raises(UnsupportedPlatformError, match="darwin; known: linux"):
        launcher_for("darwin")
