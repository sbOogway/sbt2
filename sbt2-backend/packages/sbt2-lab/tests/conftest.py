from pathlib import Path

import pytest
from lab_kit import CROSS


@pytest.fixture
def strategies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder on ``sys.path`` holding the module ``my_strats``."""
    (tmp_path / "my_strats.py").write_text(CROSS)
    monkeypatch.syspath_prepend(tmp_path)
    return tmp_path
