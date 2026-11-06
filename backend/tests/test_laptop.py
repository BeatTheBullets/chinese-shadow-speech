import sys
from pathlib import Path
from types import SimpleNamespace
from shadow.config import load_settings
from shadow.laptop import ensure_laptop_config, laptop_config_text, model_env, prepare_steps, run_prepare


def test_laptop_config_is_cpu_int8_sherpa(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(laptop_config_text(tmp_path))
    s = load_settings(p)
    assert s.models.device == "cpu" and s.models.int8 is True
    assert s.models.punctuation == "sherpa"
    assert s.data_dir == tmp_path / "data"


def test_ensure_laptop_config_never_overwrites(tmp_path: Path):
    p = ensure_laptop_config(tmp_path)
    assert p.exists()
    p.write_text("# mine\n")
    assert ensure_laptop_config(tmp_path) == p
    assert p.read_text() == "# mine\n"


def test_laptop_config_round_trips_awkward_home(tmp_path: Path):
    name = "Jöhn Doe 张"
    if sys.platform != "win32":  # Windows forbids these in file names; keep them where the TOML escaping is testable
        name = 'Jöhn "Doe" \\ 张'
    home = tmp_path / name
    p = ensure_laptop_config(home)
    assert load_settings(p).data_dir == home / "data"


def test_model_env_points_under_home(tmp_path: Path):
    env = model_env(tmp_path)
    assert set(env) == {"HF_HOME", "MODELSCOPE_CACHE", "TORCH_HOME", "SHADOW_MODELS_DIR"}
    for v in env.values():
        assert Path(v).is_relative_to(tmp_path / "models")


class Loader:
    def __init__(self, log, name, fail=False):
        self.log, self.name, self.fail = log, name, fail

    def _load(self):
        self.log.append(self.name)
        if self.fail:
            raise RuntimeError("boom")


def fake_deps(log, fail=None):
    def mk(n):
        return Loader(log, n, fail == n)
    asr = mk("asr")
    asr.punctuator = mk("punct")
    return SimpleNamespace(asr=asr, aligner=SimpleNamespace(inner=mk("aligner")), embedder=mk("embedder"),
                           sounds=SimpleNamespace(chars=mk("sounds")))


def test_prepare_steps_load_each_model_in_order():
    log = []
    steps = prepare_steps(fake_deps(log))
    assert len(steps) == 5
    for _, fn in steps:
        fn()
    assert log == ["asr", "punct", "aligner", "embedder", "sounds"]


def test_run_prepare_prints_progress_and_reports_failure(capsys):
    assert run_prepare(fake_deps([])) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 5 and '"done": 5' in lines[-1] and '"total": 5' in lines[-1]
    assert run_prepare(fake_deps([], fail="aligner")) != 0
    assert '"error"' in capsys.readouterr().out.strip().splitlines()[-1]


class Holder:
    """A loader that keeps its model in `_model` (or `_punct`), like the real ones, and records what else is loaded."""
    live: list = []

    def __init__(self, name, attr="_model"):
        self.name, self.attr = name, attr
        setattr(self, attr, None)

    def _load(self):
        Holder.seen[self.name] = sorted(h.name for h in Holder.live if getattr(h, h.attr) is not None)
        setattr(self, self.attr, object())
        return getattr(self, self.attr)


def test_run_prepare_drops_each_model_before_loading_the_next(capsys):
    # prepare only fills the caches; holding every model at once made its peak the sum of all loads
    Holder.seen = {}
    asr, punct, al, emb, snd = Holder("asr"), Holder("punct", "_punct"), Holder("aligner"), Holder("embedder"), Holder("sounds")
    Holder.live = [asr, punct, al, emb, snd]
    asr.punctuator = punct
    deps = SimpleNamespace(asr=asr, aligner=SimpleNamespace(inner=al), embedder=emb, sounds=SimpleNamespace(chars=snd))
    assert run_prepare(deps) == 0
    assert all(v == [] for v in Holder.seen.values()), Holder.seen
    assert all(getattr(h, h.attr) is None for h in Holder.live)
