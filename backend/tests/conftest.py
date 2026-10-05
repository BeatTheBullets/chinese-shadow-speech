import pytest
from pathlib import Path


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    (d / "lessons").mkdir(parents=True)
    (d / "attempts").mkdir()
    (d / "cache").mkdir()
    return d
