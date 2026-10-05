from pathlib import Path
from shadow.config import load_settings


def test_loads_defaults_from_toml(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text('[server]\nhost = "127.0.0.1"\nport = 9001\n[llm]\nmodel = "claude-sonnet-5-5"\n')
    s = load_settings(toml)
    assert s.server.port == 9001
    assert s.llm.model == "claude-sonnet-5-5"
    assert s.segmentation.min_chars == 6          # default
    assert s.scoring.f0_ceiling == 500             # default
    assert s.models.aligner == "auto"


def test_data_dir_defaults_next_to_config(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text("")
    s = load_settings(toml)
    assert s.data_dir == tmp_path / "data"
