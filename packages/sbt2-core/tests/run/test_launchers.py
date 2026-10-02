import pytest

from sbt2.core.run import (
    SystemdScope,
    Uncapped,
    UnsupportedPlatformError,
    launcher_for,
)


@pytest.mark.unit
def test_linux_gets_the_systemd_scope() -> None:
    assert isinstance(launcher_for("linux"), SystemdScope)


@pytest.mark.unit
def test_an_unserved_platform_names_the_known_ones() -> None:
    with pytest.raises(UnsupportedPlatformError, match="darwin; known: linux"):
        launcher_for("darwin")


@pytest.mark.unit
def test_the_uncapped_launcher_never_blames_memory() -> None:
    launcher = Uncapped()

    launcher.check()
    launcher.cap("run", 1, 2**30)

    assert not launcher.out_of_memory("run")
