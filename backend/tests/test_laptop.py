import json
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


def test_manifest_path_is_in_the_models_folder_of_the_home(tmp_path, monkeypatch):
    from shadow.laptop import manifest_path
    for k, v in model_env(tmp_path).items():
        monkeypatch.setenv(k, v)
    assert manifest_path() == tmp_path / "models" / "prepared.json"
    monkeypatch.delenv("SHADOW_MODELS_DIR")
    assert manifest_path().parent.parts[-2:] == ("shadow-speech", "models")


def _prepared_home(tmp_path, monkeypatch):
    """A laptop home whose model files exist as prepare leaves them: an int8 copy, the punctuation model, the
    recogniser and VAD snapshots and the HF snapshots of the tone and sound models."""
    import shadow.ingest.asr as asr
    import shadow.laptop as laptop
    import shadow.quant as q
    models = tmp_path / "models"

    def touch(p: Path) -> Path:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p
    int8 = touch(models / "shadow" / "int8" / "mms_fa-q2.pt")
    punct = touch(models / "shadow" / "punct-model" / "inner" / "model.int8.onnx")
    snaps = {n: models / "modelscope" / "models" / n for n in ("paraformer", "vad")}
    for d in snaps.values():
        for f in asr._MS_FILES:
            touch(d / f)
    hf = {n: models / "hf" / "hub" / f"models--{n}" / "snapshots" / "abc" for n in ("tone", "sounds")}
    touch(hf["tone"] / "config.json"), touch(hf["tone"] / "model.safetensors")
    touch(hf["sounds"] / "config.json"), touch(hf["sounds"] / "pytorch_model.bin"), touch(hf["sounds"] / "vocab.json")
    monkeypatch.setattr(q, "_stored", {int8, tmp_path / "elsewhere" / "other.pt"})   # outside the home: not listed
    monkeypatch.setattr(asr, "_local_snapshot", lambda n: str(snaps["paraformer" if n == "pm" else "vad"]))
    monkeypatch.setattr(laptop, "_hf_snapshot", lambda name, revision: hf[name])
    deps = fake_deps([])
    deps.asr.model_id = "pm"
    deps.asr.punctuator.model_file = punct
    deps.embedder.name, deps.embedder.revision = "tone", "r1"
    deps.sounds.chars.name, deps.sounds.chars.revision = "sounds", "r2"
    return deps, models


def test_run_prepare_writes_a_manifest_of_the_files_the_app_needs(tmp_path, monkeypatch, capsys):
    from shadow.quant import QUANT_FORMAT
    deps, models = _prepared_home(tmp_path, monkeypatch)
    assert run_prepare(deps, models / "prepared.json") == 0
    m = json.loads((models / "prepared.json").read_text(encoding="utf-8"))
    assert m["quant_format"] == QUANT_FORMAT
    assert set(m["files"]) == {
        "shadow/int8/mms_fa-q2.pt", "shadow/punct-model/inner/model.int8.onnx",
        *(f"modelscope/models/{n}/{f}" for n in ("paraformer", "vad") for f in ("configuration.json", "config.yaml",
                                                                                  "model.pt")),
        "hf/hub/models--tone/snapshots/abc/config.json", "hf/hub/models--tone/snapshots/abc/model.safetensors",
        "hf/hub/models--sounds/snapshots/abc/config.json", "hf/hub/models--sounds/snapshots/abc/pytorch_model.bin"}
    assert all((models / f).is_file() for f in m["files"])
    assert [p.name for p in models.iterdir() if p.is_file()] == ["prepared.json"]   # no temporary file left


def test_a_failed_prepare_writes_no_manifest(tmp_path, monkeypatch, capsys):
    deps, models = _prepared_home(tmp_path, monkeypatch)
    deps.aligner.inner.fail = True
    assert run_prepare(deps, models / "prepared.json") != 0
    assert not (models / "prepared.json").exists()


def test_manifest_lists_only_files_that_exist(tmp_path, monkeypatch, capsys):
    # a snapshot that cannot be found (or a model the config turned off) is left out, never listed as missing:
    # a listed file that prepare cannot bring back would rerun setup on every start
    import shadow.laptop as laptop
    deps, models = _prepared_home(tmp_path, monkeypatch)
    monkeypatch.setattr(laptop, "_hf_snapshot", lambda name, revision: None)
    deps.asr.punctuator.model_file = models / "gone.onnx"
    assert run_prepare(deps, models / "prepared.json") == 0
    files = json.loads((models / "prepared.json").read_text(encoding="utf-8"))["files"]
    assert "shadow/int8/mms_fa-q2.pt" in files
    assert not any(f.startswith("hf/") or f == "gone.onnx" for f in files)


def test_run_prepare_fails_when_an_int8_copy_could_not_be_stored(tmp_path, monkeypatch, capsys):
    # a copy that failed to save (e.g. a full disk) would otherwise be built during a take, with every model loaded
    import shadow.quant as quant
    monkeypatch.setattr(quant, "_unsaved", {"some-model-key"})
    manifest = tmp_path / "prepared.json"
    assert run_prepare(fake_deps([]), manifest) != 0
    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "error" in last and "disk" in last["error"]
    assert not manifest.exists()


def test_cached_int8_records_a_copy_it_could_not_store(tmp_path, monkeypatch):
    import torch
    import shadow.quant as quant
    monkeypatch.setattr(quant, "_unsaved", set())
    monkeypatch.setattr(quant, "int8_cache_path", lambda key: tmp_path / "int8" / f"{key}.pt")
    monkeypatch.setattr(torch, "save", lambda *a, **k: (_ for _ in ()).throw(OSError("No space left on device")))
    m = quant.cached_int8("k", lambda: torch.nn.Linear(2, 2))
    assert isinstance(m, torch.nn.Linear) and quant.unsaved_int8() == ["k"]
