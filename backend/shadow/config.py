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
    tone_weight: float = 0.5
    dtw_band: int = 4
    f0_floor: int = 60
    f0_ceiling: int = 500
    normalise_span: bool = True
    min_voiced_frames: int = 4
    gop_margin: float = 2.0
    min_duration_ratio: float = 0.4


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
