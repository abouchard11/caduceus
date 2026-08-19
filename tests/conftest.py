import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def isolated_homes(tmp_path, monkeypatch):
    """Every test gets throwaway CADUCEUS_HOME / HERMES_HOME."""
    monkeypatch.setenv("CADUCEUS_HOME", str(tmp_path / "caduceus_home"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
    (tmp_path / "hermes_home").mkdir(parents=True, exist_ok=True)
    yield tmp_path
