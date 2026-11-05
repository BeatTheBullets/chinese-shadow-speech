from __future__ import annotations
import os
import tomllib
from pathlib import Path
from pydantic import BaseModel, Field


class ServerCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class ModelsCfg(BaseModel):
    device: str = "auto"
    asr: str = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    aligner: str = "auto"
    gop_model: str = "wbbbbb/wav2vec2-large-chinese-zh-cn"
    tone_embedder: str = "TencentGameMate/chinese-wav2vec2-base"      # Phase 2 spec §10 (MIT)
    tone_embedder_revision: str = "3991242c806928916fff4a8c0e4f76acf661b743"
    tone_layer: int = 6
    punctuation: str = "sherpa"       # "sherpa": the small sherpa-onnx punctuation model; "pauses": none, sentences are cut at pauses ([segmentation])
    punctuation_model: str = "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
    punctuation_url: str = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models/"
                            "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8.tar.bz2")
    punctuation_sha256: str = "c0d5aa5f8eeb686032345e180bedf39319dc2e0556781c6264bcadba8328a6e1"
    int8: bool = False                # CPU only: 8-bit recogniser, aligner and sounds model (about half the RAM)
    asr_int8_below_ram_gb: float = 12.0   # with int8 on, the recogniser is 8-bit only on a machine with less RAM than this
    int8_skip: list[str] = []         # models kept fp32 even with int8 on: "asr", "aligner", "sounds"
    threads: int = 0                  # CPU threads for the models; 0 = physical cores minus one


class SegmentationCfg(BaseModel):
    pad_ms: int = 120
    pause_cut_s: float = 0.5          # unpunctuated text: a pause this long always ends a sentence
    pause_split_s: float = 0.25       # ... a too-long sentence is split preferably at a pause this long
    min_chars: int = 4                # ... a shorter sentence is merged into a neighbour
    max_chars: int = 25               # ... a longer one is split


class ScoringCfg(BaseModel):
    tone_weight: float = 0.5          # share of the classifier's P(target) in tone_score; the rest is contour similarity
    dtw_band: int = 4
    f0_floor: int = 60
    f0_ceiling: int = 500
    normalise_span: bool = True
    min_voiced_frames: int = 4
    gop_margin: float = 2.0
    min_duration_ratio: float = 0.4
    green_at: float = 0.7             # Phase 2 spec §3: ok needs the target tone heard and tone_score ≥ this
    wrong_margin: float = 0.25        # wrong: another tone beats P(target) by at least this
    ref_confidence: float = 0.6       # the reference's own classification becomes the target from this probability
    min_rms_dbfs: float = -55.0       # gate (spec §1); re-set from the user's takes in the plan's Task 15
    min_align_conf: float = 0.05
    min_text_similarity: float = 0.25  # words check (spec §1): below this toneless similarity of what was heard → not scored
    words_ok_at: float = 0.55         # from here no notice; in between the take is scored with notice `words_differ`
    max_clipped: float = 0.01
    profile_seconds: float = 60.0     # voiced seconds before the voice profile alone sets the learner's baseline
    tone_model: str = "tone_v1"       # backend/shadow/scoring/models/<name>.{joblib,json}


class PracticeCfg(BaseModel):
    hide_text_while_recording: bool = True
    flow_gap_factor: float = 1.1
    move_on_after: int = 4


class YoutubeCfg(BaseModel):
    enabled: bool = True
    max_minutes: int = 90
    cookies_file: str = ""


class AnkiCfg(BaseModel):
    default_url: str = "http://127.0.0.1:8765"


class DrillCfg(BaseModel):
    window_days: int = 30             # weakness = mean tone_score over attempts this recent
    min_rows: int = 8                 # a focus needs this many scored syllable rows to be ranked
    queue_size: int = 10
    max_tries: int = 3                # scored tries per queue item before it moves on
    max_per_lesson: int = 4
    min_syllables: int = 4
    max_syllables: int = 15
    rotate_within: float = 0.05       # foci this close to the weakest rotate instead of repeating


class SoundsCfg(BaseModel):
    # Phase 3a wrong-sound detector (spec §3). z-normalisers put model A (GOP on the planned syllable) and
    # model B (bad-pronunciation score) on a common scale before they are summed; constants are the spike's.
    enabled: bool = True
    model: str = "wbbbbb/wav2vec2-large-chinese-zh-cn"
    revision: str = "b654b5f3df69725df32808de454a1b865c829e4c"
    z_a_mean: float = -4.006537
    z_a_sd: float = 2.974512
    z_b_mean: float = 1.239741
    z_b_sd: float = 3.072057
    fused_threshold: float = 5.3036   # slip when the summed z-scores exceed this (both models ran)
    b_only_threshold: float = 11.6518  # raw model-B score alone; used when model A has no reading for the syllable


class Settings(BaseModel):
    server: ServerCfg = Field(default_factory=ServerCfg)
    models: ModelsCfg = Field(default_factory=ModelsCfg)
    segmentation: SegmentationCfg = Field(default_factory=SegmentationCfg)
    scoring: ScoringCfg = Field(default_factory=ScoringCfg)
    practice: PracticeCfg = Field(default_factory=PracticeCfg)
    youtube: YoutubeCfg = Field(default_factory=YoutubeCfg)
    anki: AnkiCfg = Field(default_factory=AnkiCfg)
    drill: DrillCfg = Field(default_factory=DrillCfg)
    sounds: SoundsCfg = Field(default_factory=SoundsCfg)
    data_dir: Path = Path("data")

    def resolved_device(self) -> str:
        if self.models.device != "auto":
            return self.models.device
        try:
            import torch  # noqa: WPS433
            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def resolved_aligner(self) -> str:
        """`auto` is MMS_FA on every device: repaired MMS_FA beat repaired Qwen3 on lesson 1 (plan 2026-10-07, ledger)."""
        if self.models.aligner != "auto":
            return self.models.aligner
        return "mms_fa"


def load_settings(path: Path | None = None) -> Settings:
    if path is None:
        env = os.environ.get("SHADOW_CONFIG")
        path = Path(env) if env else Path(__file__).resolve().parents[2] / "config.toml"
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    s = Settings.model_validate(raw)
    if "data_dir" not in raw:
        s.data_dir = path.parent / "data"
    return s
