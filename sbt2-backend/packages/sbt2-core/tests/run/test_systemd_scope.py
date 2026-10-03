import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from batch_kit import GiB, resolved, setup, summaries

from sbt2.core.run import (
    Memory,
    NoUserSessionError,
    OutOfMemoryError,
    SystemdScope,
    batch,
)

MiB = 2**20
HOG = """
from nautilus_trader.model import Bar

from run_strategies import BuyThenSell


class Hog(BuyThenSell):
    def on_bar(self, bar: Bar) -> None:
        # Writing the bytes makes every allocated page resident.
        self.block = b"x" * (256 * 2**20)
        super().on_bar(bar)
"""


def scope_property(run_id: str, name: str) -> str:
    show = ["systemctl", "--user", "show", f"sbt2-{run_id}.scope", f"--property={name}"]
    output = subprocess.run(show, capture_output=True, text=True, check=True).stdout
    return output.strip().removeprefix(f"{name}=")


def allocating_strategy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    (tmp_path / "resident_hog.py").write_text(HOG)
    monkeypatch.syspath_prepend(tmp_path)
    return "resident_hog:Hog"


def out_of_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OutOfMemoryError:
    strategy = allocating_strategy(tmp_path, monkeypatch)
    capped = replace(
        setup(tmp_path, SystemdScope()), memory=Memory(budget=GiB, per_run=100 * MiB)
    )
    with pytest.raises(OutOfMemoryError) as failure:
        batch([resolved(tmp_path, strategy=strategy)], capped)
    return failure.value


@pytest.mark.unit
def test_without_a_user_session_the_batch_starts_no_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    with pytest.raises(NoUserSessionError):
        batch([resolved(tmp_path)], setup(tmp_path, SystemdScope()))

    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "results").exists()


@pytest.mark.integration
@pytest.mark.systemd
def test_a_run_under_the_cap_is_stored(tmp_path: Path) -> None:
    [run_id] = batch([resolved(tmp_path)], setup(tmp_path, SystemdScope()))

    assert run_id in summaries(tmp_path)


@pytest.mark.integration
@pytest.mark.systemd
def test_a_run_over_the_cap_raises_out_of_memory_naming_its_run_and_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = out_of_memory(tmp_path, monkeypatch)

    assert error.run_id in str(error)
    assert str(error.folder) in str(error)
    assert "100M" in str(error)


@pytest.mark.integration
@pytest.mark.systemd
def test_the_scope_of_a_run_killed_over_the_cap_is_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = out_of_memory(tmp_path, monkeypatch)

    assert scope_property(error.run_id, "LoadState") == "not-found"
