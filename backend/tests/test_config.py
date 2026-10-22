from pathlib import Path
from shadow.config import load_settings


def test_loads_defaults_from_toml(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text('[server]\nhost = "127.0.0.1"\nport = 9001\n')
    s = load_settings(toml)
    assert s.server.port == 9001
    assert s.segmentation.pad_ms == 120           # default
    assert s.scoring.f0_ceiling == 500             # default
    assert s.models.aligner == "auto"


def test_data_dir_defaults_next_to_config(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text("")
    s = load_settings(toml)
    assert s.data_dir == tmp_path / "data"


def test_auto_aligner_is_mms_fa_on_every_device():
    from shadow.config import ModelsCfg, Settings
    for device in ("cuda", "cpu"):
        assert Settings(models=ModelsCfg(device=device)).resolved_aligner() == "mms_fa"
    assert Settings(models=ModelsCfg(device="cuda", aligner="qwen3_fa")).resolved_aligner() == "qwen3_fa"


def test_youtube_defaults():
    from shadow.config import Settings
    y = Settings().youtube
    assert (y.enabled, y.max_minutes, y.cookies_file) == (True, 90, "")


def test_phase2_scoring_defaults():
    from shadow.config import Settings
    s = Settings().scoring
    assert (s.green_at, s.wrong_margin, s.ref_confidence) == (0.7, 0.25, 0.6)
    assert (s.min_rms_dbfs, s.min_align_conf, s.max_clipped, s.profile_seconds) == (-55.0, 0.05, 0.01, 60.0)
    assert (s.min_text_similarity, s.words_ok_at) == (0.25, 0.55)
    assert s.tone_model == "tone_v1"


def test_repo_config_toml_has_phase2_scoring_keys():
    from pathlib import Path
    from shadow.config import load_settings
    s = load_settings(Path(__file__).resolve().parents[2] / "config.toml")
    assert s.scoring.tone_model == "tone_v1" and s.scoring.green_at == 0.7
    from shadow.config import ScoringCfg
    assert s.scoring.min_text_similarity == ScoringCfg().min_text_similarity     # the words check's thresholds are set
    assert s.scoring.words_ok_at == ScoringCfg().words_ok_at


def test_drill_defaults_and_config_toml():
    from pathlib import Path
    from shadow.config import Settings, load_settings
    d = Settings().drill
    assert (d.window_days, d.min_rows, d.queue_size, d.max_tries, d.max_per_lesson) == (30, 8, 10, 3, 4)
    assert (d.min_syllables, d.max_syllables, d.rotate_within) == (4, 15, 0.05)
    assert load_settings(Path(__file__).resolve().parents[2] / "config.toml").drill == d


def test_sounds_defaults_and_config_toml():
    from pathlib import Path
    from shadow.config import Settings, load_settings
    d = Settings().sounds
    assert d.enabled is True
    assert (d.model, d.revision) == ("wbbbbb/wav2vec2-large-chinese-zh-cn", "b654b5f3df69725df32808de454a1b865c829e4c")
    assert (d.z_a_mean, d.z_a_sd, d.z_b_mean, d.z_b_sd) == (-4.006537, 2.974512, 1.239741, 3.072057)
    assert (d.fused_threshold, d.b_only_threshold) == (5.3036, 11.6518)
    s = load_settings(Path(__file__).resolve().parents[2] / "config.toml")
    assert s.sounds == d
