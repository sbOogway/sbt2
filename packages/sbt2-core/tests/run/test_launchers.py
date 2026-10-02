import pytest

from sbt2.core.run import (
    Launcher,
    SystemdScope,
    Uncapped,
    UnknownLauncherError,
    launcher_named,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "kind"), [("uncapped", Uncapped), ("systemd", SystemdScope)]
)
def test_each_launcher_is_found_by_its_name(name: str, kind: type[Launcher]) -> None:
    assert isinstance(launcher_named(name), kind)


@pytest.mark.unit
def test_an_unknown_launcher_names_the_known_ones() -> None:
    with pytest.raises(UnknownLauncherError, match="cgroup; known: systemd, uncapped"):
        launcher_named("cgroup")


@pytest.mark.unit
def test_the_uncapped_launcher_never_blames_memory() -> None:
    launcher = Uncapped()

    launcher.check()
    launcher.cap("run", 1, 2**30)

    assert not launcher.out_of_memory("run")
