from __future__ import annotations
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


class LlmCfg(BaseModel):
    model: str = "claude-sonnet-5-5"
    effort: str = "low"
    rectify: bool = True
    translate: bool = True


class SegmentationCfg(BaseModel):
    min_chars: int = 6
    max_chars: int = 25
    pad_ms: int = 120


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
    min_text_similarity: float = 0.55  # words check (spec §1, R14): toneless similarity of what was heard to the sentence
    max_clipped: float = 0.01
    profile_seconds: float = 60.0     # voiced seconds before the voice profile alone sets the learner's baseline
    tone_model: str = "tone_v1"       # backend/shadow/scoring/models/<name>.{joblib,json}


class PracticeCfg(BaseModel):
    hide_text_while_recording: bool = True
    chorus_passes: int = 5
    flow_gap_factor: float = 1.1
    move_on_after: int = 4


class YoutubeCfg(BaseModel):
    enabled: bool = True
    max_minutes: int = 90
    cookies_file: str = ""


class AnkiCfg(BaseModel):
    default_url: str = "http://127.0.0.1:8765"


class Settings(BaseModel):
    server: ServerCfg = Field(default_factory=ServerCfg)
    models: ModelsCfg = Field(default_factory=ModelsCfg)
    llm: LlmCfg = Field(default_factory=LlmCfg)
    segmentation: SegmentationCfg = Field(default_factory=SegmentationCfg)
    scoring: ScoringCfg = Field(default_factory=ScoringCfg)
    practice: PracticeCfg = Field(default_factory=PracticeCfg)
    youtube: YoutubeCfg = Field(default_factory=YoutubeCfg)
    anki: AnkiCfg = Field(default_factory=AnkiCfg)
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
    path = path or Path(__file__).resolve().parents[2] / "config.toml"
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    s = Settings.model_validate(raw)
    if "data_dir" not in raw:
        s.data_dir = path.parent / "data"
    return s
