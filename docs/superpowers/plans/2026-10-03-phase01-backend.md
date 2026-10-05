# Phase 0 + 1 Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI backend that turns an uploaded recording or a set of Anki notes into a lesson of aligned, pinyin-annotated sentence clips, stores practice attempts, and exposes the API the Phase 1 frontend consumes. No scoring yet.

**Architecture:** One Python package `shadow` with four layers: `store` (SQLModel on SQLite plus a fixed on-disk file layout), `ingest` (pure functions and small adapter classes for ffmpeg, ASR, LLM rectification, forced alignment, pinyin and clips, wired together in `pipeline.py`), `jobs` (an asyncio queue running pipelines in a thread pool and fanning progress out over SSE), and `api` (thin routers). Every external model sits behind a Protocol with a `Fake*` implementation so the whole pipeline is tested without GPU, network or model downloads.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLModel, pydantic-settings, sse-starlette, anthropic SDK, FunASR (Paraformer-zh), torchaudio MMS_FA / qwen-asr Qwen3-ForcedAligner, jieba, pypinyin, opencc-python-reimplemented, rapidfuzz, soundfile, numpy, ffmpeg CLI, pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-shadowing-tool-design.md` (sections 1–5, 8.1–8.2, 9–12 for Phase 0/1)

## Global Constraints

- Python 3.12; dependency management with `uv`; repo layout exactly as spec §1.1 (`backend/shadow/{api,ingest,scoring,store}`, `backend/tests`, `backend/fixtures`, `data/` gitignored).
- Backend binds `127.0.0.1:8000` by default; `[server] host` / `port` from `config.toml`.
- All audio stored and processed as 16 kHz mono WAV; clips also as Opus; mp3 only on demand for Anki export.
- Everything simplified Chinese: every text input passes through OpenCC `t2s`.
- Segments target 6–25 characters (`[segmentation] min_chars`, `max_chars`), 2–60 accepted; `pad_ms = 120`, clamped to neighbours.
- LLM: `claude-sonnet-5-5`, `output_config={"effort": "low", "format": {...json_schema...}}`, **no `temperature`**, cached by SHA-256 of the chunk's characters.
- `device = "auto"`; aligner `"auto"` → `qwen3_fa` on CUDA, `mms_fa` on CPU; torchaudio ≥ 2.10 and audio I/O via `soundfile`, never `torchaudio.load`.
- Tests never need a GPU, network, or model download; real-model tests are marked `models` and deselected by default.
- Every attempt is kept; editing segment text invalidates alignment, words and clips and re-runs align + enrich for that segment.
- Scores are never written back to Anki.

## Review Focus

1. An upload whose ASR returns no speech at all (silence, music) must produce a lesson with status `error` and a readable message, not a crash in rectification over an empty character list. Test added to Task 11.
2. A subtitle file whose cues overlap or run out of order must still yield monotonically non-decreasing character times. Test added to Task 6.
3. A rectification range that the LLM reports off by one at a chunk boundary (overlapping the context-only prefix) must be rejected by the validator and fall back, not shift every later sentence. Test added to Task 8.
4. An Anki note whose audio field contains two `[sound:…]` tags, or HTML wrapped around the sentence, must import the first clip and the plain-text sentence. Test added to Task 12.
5. `PATCH /segments/{id}` with text identical to the current text must be a no-op (no re-alignment, clips untouched). Test added to Task 13.

---

### Task 1: Repository, toolchain and test harness

**Files:**
- Create: `.gitignore`, `backend/pyproject.toml`, `backend/shadow/__init__.py`, `backend/tests/__init__.py`, `backend/tests/conftest.py`, `backend/tests/test_smoke.py`, `Makefile`, `config.toml`, `README.MD` (replace empty file)

**Interfaces:**
- Produces: `uv run pytest` works from `backend/`; `make test`, `make dev` targets; `config.toml` at repo root.

- [ ] **Step 1: Initialise git and ignore runtime data**

```bash
cd ~/shadow-speech && git init -b main
```

`.gitignore`:
```
data/
.superpowers/
backend/.venv/
backend/.pytest_cache/
backend/**/__pycache__/
frontend/node_modules/
frontend/dist/
*.pyc
.env
```

- [ ] **Step 2: Install uv and create the backend project**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && export PATH="$HOME/.local/bin:$PATH"
cd ~/shadow-speech/backend && uv init --no-readme --python 3.12 --name shadow --lib
rm -rf src && mkdir -p shadow tests fixtures
```

`backend/pyproject.toml` (replace generated content):
```toml
[project]
name = "shadow"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlmodel>=0.0.22",
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "python-multipart>=0.0.9",
  "sse-starlette>=2.1",
  "anthropic>=0.60",
  "jieba>=0.42",
  "pypinyin>=0.53",
  "opencc-python-reimplemented>=0.1.7",
  "rapidfuzz>=3.9",
  "soundfile>=0.12",
  "numpy>=1.26",
]

[project.optional-dependencies]
models = [
  "torch>=2.6",
  "torchaudio>=2.10",
  "funasr>=1.2",
  "modelscope>=1.20",
  "qwen-asr>=0.1",
]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.23",
  "httpx>=0.27",
]

[tool.uv]
default-groups = []

[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cu128" }]
torchaudio = [{ index = "pytorch-cu128" }]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = ["models: needs downloaded models / GPU (deselected by default)"]
addopts = "-m 'not models'"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["shadow"]
```

```bash
cd ~/shadow-speech/backend && uv sync --extra dev
```

- [ ] **Step 3: Write the smoke test**

`backend/tests/test_smoke.py`:
```python
def test_package_imports():
    import shadow
    assert shadow.__version__ == "0.1.0"
```

`backend/shadow/__init__.py`:
```python
__version__ = "0.1.0"
```

`backend/tests/conftest.py`:
```python
import pytest
from pathlib import Path


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    (d / "lessons").mkdir(parents=True)
    (d / "attempts").mkdir()
    (d / "cache").mkdir()
    return d
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest -q`
Expected: `1 passed`

- [ ] **Step 5: Makefile and root config**

`Makefile`:
```make
.PHONY: dev test backend frontend
backend:
	cd backend && uv run uvicorn shadow.main:app --host 127.0.0.1 --port 8000 --reload
frontend:
	cd frontend && npm run dev
dev:
	$(MAKE) -j2 backend frontend
test:
	cd backend && uv run pytest -q
	cd frontend && npm test -- --run
```

`config.toml`: copy spec §10 verbatim.

`README.MD`:
```markdown
# shadow — Mandarin shadowing tool

Spec: docs/superpowers/specs/2026-10-03-shadowing-tool-design.md

    make dev      # backend on :8000, frontend on :5173
    make test
```

- [ ] **Step 6: Commit**

```bash
cd ~/shadow-speech && git add -A && git commit -m "chore: repo skeleton, uv project, pytest harness"
```

---

### Task 2: Config loader and `/health`

**Files:**
- Create: `backend/shadow/config.py`, `backend/shadow/main.py`, `backend/shadow/api/__init__.py`, `backend/shadow/api/health.py`, `backend/tests/test_config.py`, `backend/tests/test_health.py`

**Interfaces:**
- Produces: `shadow.config.Settings` (pydantic model mirroring `config.toml`), `load_settings(path: Path | None = None) -> Settings`, `settings.data_dir: Path`; `shadow.main.create_app(settings: Settings | None = None) -> FastAPI`; `app.state.settings`.

- [ ] **Step 1: Failing tests**

`backend/tests/test_config.py`:
```python
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
```

`backend/tests/test_health.py`:
```python
from fastapi.testclient import TestClient
from shadow.main import create_app
from shadow.config import Settings


def test_health(data_dir):
    app = create_app(Settings(data_dir=data_dir))
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["device"] in {"cpu", "cuda"}
    assert body["models_loaded"] == []
    assert "versions" in body
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_config.py tests/test_health.py -q`
Expected: FAIL, `ModuleNotFoundError: shadow.config`

- [ ] **Step 3: Implement**

`backend/shadow/config.py`:
```python
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
    enabled: bool = False
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
        if self.models.aligner != "auto":
            return self.models.aligner
        return "qwen3_fa" if self.resolved_device() == "cuda" else "mms_fa"


def load_settings(path: Path | None = None) -> Settings:
    path = path or Path(__file__).resolve().parents[2] / "config.toml"
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    s = Settings.model_validate(raw)
    if "data_dir" not in raw:
        s.data_dir = path.parent / "data"
    return s
```

`backend/shadow/api/__init__.py`: empty.

`backend/shadow/api/health.py`:
```python
from fastapi import APIRouter, Request
import fastapi, sqlmodel, pydantic

router = APIRouter()


@router.get("/health")
def health(request: Request):
    settings = request.app.state.settings
    loaded = getattr(request.app.state, "deps", None)
    return {
        "device": settings.resolved_device(),
        "aligner": settings.resolved_aligner(),
        "models_loaded": loaded.loaded_models() if loaded else [],
        "versions": {"fastapi": fastapi.__version__, "sqlmodel": sqlmodel.__version__, "pydantic": pydantic.__version__},
    }
```

`backend/shadow/main.py`:
```python
from fastapi import FastAPI
from shadow.config import Settings, load_settings
from shadow.api import health


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="shadow")
    app.state.settings = settings
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: config loader and /health"
```

---

### Task 3: Store — SQLModel tables, engine, file layout

**Files:**
- Create: `backend/shadow/store/__init__.py`, `backend/shadow/store/models.py`, `backend/shadow/store/db.py`, `backend/shadow/store/files.py`, `backend/tests/test_store.py`

**Interfaces:**
- Produces: tables `Lesson, Segment, Attempt, Session, SyllableScore` (spec §4) with JSON columns typed `list | dict | None`; `make_engine(data_dir) -> Engine`; `init_db(engine)`; `get_session(request) -> Iterator[Session]` FastAPI dependency; `FileLayout(data_dir)` with `lesson_dir(id)`, `source_wav(id)`, `clip_wav(id, idx)`, `clip_opus(id, idx)`, `clip_mp3(id, idx)`, `attempt_wav(attempt_id)`, `cache_dir(name)`.
- Status strings: lesson `status ∈ {"queued","processing","ready","error"}`.

- [ ] **Step 1: Failing test**

`backend/tests/test_store.py`:
```python
from sqlmodel import Session as DbSession, select
from shadow.store.db import make_engine, init_db
from shadow.store.models import Lesson, Segment, Attempt, PracticeSession, SyllableScore
from shadow.store.files import FileLayout


def test_roundtrip_lesson_segment_attempt(data_dir):
    engine = make_engine(data_dir)
    init_db(engine)
    with DbSession(engine) as db:
        lesson = Lesson(title="t", speaker="s", source_type="upload", source_ref="x.mp4", status="ready")
        db.add(lesson); db.commit(); db.refresh(lesson)
        seg = Segment(lesson_id=lesson.id, idx=0, start_s=0.0, end_s=1.2, text="你好。",
                      words_json=[{"word": "你好", "pinyin": "nǐhǎo", "tones": [3, 3], "char_from": 0, "char_to": 1}],
                      ref_alignment_json=[{"ch": "你", "start": 0.1, "end": 0.5, "conf": 0.9}])
        db.add(seg); db.commit(); db.refresh(seg)
        ps = PracticeSession(lesson_id=lesson.id, mode="echo")
        db.add(ps); db.commit(); db.refresh(ps)
        att = Attempt(segment_id=seg.id, session_id=ps.id, mode="echo", audio_path="a.wav", duration_s=1.0)
        db.add(att); db.commit(); db.refresh(att)
        db.add(SyllableScore(attempt_id=att.id, segment_id=seg.id, idx=0, ch="你", pinyin_toneless="ni",
                             tone=3, prev_tone=None, tone_score=0.8, seg_score=None, status="ok"))
        db.commit()
        got = db.exec(select(Segment).where(Segment.lesson_id == lesson.id)).one()
        assert got.words_json[0]["word"] == "你好"
        assert got.ref_alignment_json[0]["ch"] == "你"
        assert db.exec(select(SyllableScore)).one().tone == 3


def test_file_layout(data_dir):
    fl = FileLayout(data_dir)
    assert fl.clip_wav(7, 3) == data_dir / "lessons" / "7" / "clips" / "3.wav"
    assert fl.attempt_wav(12) == data_dir / "attempts" / "12.wav"
    fl.lesson_dir(7).mkdir(parents=True)
    assert fl.source_wav(7).parent.exists()
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_store.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`backend/shadow/store/__init__.py`: empty.

`backend/shadow/store/models.py`:
```python
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


class Lesson(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    speaker: str = ""
    source_type: str                      # upload | youtube | anki
    source_ref: str = ""
    duration_s: float = 0.0
    created_at: datetime = Field(default_factory=now)
    status: str = "queued"                # queued | processing | ready | error
    error: str | None = None
    meta_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    transcript_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class Segment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    lesson_id: int = Field(foreign_key="lesson.id", index=True)
    idx: int
    start_s: float
    end_s: float
    char_from: int | None = None
    char_to: int | None = None
    text: str
    translation: str | None = None
    words_json: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    ref_alignment_json: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    difficulty_flag: bool = False
    anki_note_id: int | None = None
    clip_wav_path: str | None = None
    clip_opus_path: str | None = None


class PracticeSession(SQLModel, table=True):
    __tablename__ = "session"
    id: int | None = Field(default=None, primary_key=True)
    lesson_id: int = Field(foreign_key="lesson.id", index=True)
    mode: str                              # echo | chorus | flow | guided
    started_at: datetime = Field(default_factory=now)
    ended_at: datetime | None = None
    attempts_count: int = 0


class Attempt(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    segment_id: int = Field(foreign_key="segment.id", index=True)
    session_id: int | None = Field(default=None, foreign_key="session.id")
    created_at: datetime = Field(default_factory=now)
    mode: str
    audio_path: str
    duration_s: float
    score_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class SyllableScore(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    attempt_id: int = Field(foreign_key="attempt.id", index=True)
    segment_id: int = Field(foreign_key="segment.id", index=True)
    idx: int
    ch: str
    pinyin_toneless: str = Field(index=True)
    tone: int
    prev_tone: int | None = None
    tone_score: float | None = None
    seg_score: float | None = None
    status: str
```

`backend/shadow/store/db.py`:
```python
from pathlib import Path
from typing import Iterator
from fastapi import Request
from sqlalchemy import Engine
from sqlmodel import SQLModel, Session, create_engine
from shadow.store import models  # noqa: F401  (registers tables)


def make_engine(data_dir: Path) -> Engine:
    data_dir.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{data_dir / 'shadow.db'}", connect_args={"check_same_thread": False})


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as s:
        yield s
```

`backend/shadow/store/files.py`:
```python
from pathlib import Path


class FileLayout:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def lesson_dir(self, lesson_id: int) -> Path:
        return self.data_dir / "lessons" / str(lesson_id)

    def source_wav(self, lesson_id: int) -> Path:
        return self.lesson_dir(lesson_id) / "source.wav"

    def clip_wav(self, lesson_id: int, idx: int) -> Path:
        return self.lesson_dir(lesson_id) / "clips" / f"{idx}.wav"

    def clip_opus(self, lesson_id: int, idx: int) -> Path:
        return self.lesson_dir(lesson_id) / "clips" / f"{idx}.opus"

    def clip_mp3(self, lesson_id: int, idx: int) -> Path:
        return self.lesson_dir(lesson_id) / "clips" / f"{idx}.mp3"

    def attempt_wav(self, attempt_id: int) -> Path:
        return self.data_dir / "attempts" / f"{attempt_id}.wav"

    def cache_dir(self, name: str) -> Path:
        p = self.data_dir / "cache" / name
        p.mkdir(parents=True, exist_ok=True)
        return p
```

Add to `create_app` in `main.py` after `app.state.settings = settings`:
```python
from shadow.store.db import make_engine, init_db
from shadow.store.files import FileLayout
    app.state.engine = make_engine(settings.data_dir)
    init_db(app.state.engine)
    app.state.files = FileLayout(settings.data_dir)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: store models, sqlite engine, file layout"
```

---

### Task 4: Audio utilities (ffmpeg wrappers)

**Files:**
- Create: `backend/shadow/ingest/__init__.py`, `backend/shadow/ingest/audio.py`, `backend/tests/test_audio.py`, `backend/tests/helpers.py`

**Interfaces:**
- Produces: `normalise(src: Path, dst: Path) -> None` (16 kHz mono PCM16 WAV), `duration_s(path) -> float`, `cut(src, dst, start_s, end_s) -> None`, `encode_opus(src_wav, dst) -> None`, `encode_mp3(src_wav, dst) -> None`, `read_wav(path) -> tuple[np.ndarray, int]` (float32 mono), `write_wav(path, samples: np.ndarray, sr=16000)`.
- Test helper: `tests/helpers.py: make_tone_wav(path, seconds, sr=16000, freq=220.0)`.

- [ ] **Step 1: Failing tests**

`backend/tests/helpers.py`:
```python
from pathlib import Path
import numpy as np
import soundfile as sf


def make_tone_wav(path: Path, seconds: float, sr: int = 16000, freq: float = 220.0) -> Path:
    t = np.arange(int(seconds * sr)) / sr
    sf.write(path, (0.3 * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)
    return path
```

`backend/tests/test_audio.py`:
```python
import numpy as np
import soundfile as sf
from shadow.ingest import audio
from tests.helpers import make_tone_wav


def test_normalise_to_16k_mono(tmp_path):
    src = tmp_path / "in.wav"
    t = np.arange(44100) / 44100
    stereo = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 220 * t)], axis=1).astype("float32")
    sf.write(src, stereo, 44100)
    dst = tmp_path / "out.wav"
    audio.normalise(src, dst)
    info = sf.info(dst)
    assert info.samplerate == 16000 and info.channels == 1 and info.subtype == "PCM_16"
    assert abs(audio.duration_s(dst) - 1.0) < 0.02


def test_cut_and_encode(tmp_path):
    src = make_tone_wav(tmp_path / "src.wav", 3.0)
    clip = tmp_path / "c.wav"
    audio.cut(src, clip, 1.0, 2.5)
    assert abs(audio.duration_s(clip) - 1.5) < 0.02
    audio.encode_opus(clip, tmp_path / "c.opus")
    audio.encode_mp3(clip, tmp_path / "c.mp3")
    assert (tmp_path / "c.opus").stat().st_size > 0 and (tmp_path / "c.mp3").stat().st_size > 0


def test_read_write_wav_roundtrip(tmp_path):
    x = (0.1 * np.random.randn(16000)).astype("float32")
    audio.write_wav(tmp_path / "r.wav", x)
    y, sr = audio.read_wav(tmp_path / "r.wav")
    assert sr == 16000 and y.shape == x.shape and np.max(np.abs(y - x)) < 1e-3
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_audio.py -q`
Expected: FAIL, `ModuleNotFoundError: shadow.ingest`

- [ ] **Step 3: Implement**

`backend/shadow/ingest/__init__.py`: empty.

`backend/shadow/ingest/audio.py`:
```python
from __future__ import annotations
import json
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf

SR = 16000


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def normalise(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)])


def duration_s(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def cut(src: Path, dst: Path, start_s: float, end_s: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}", "-i", str(src),
          "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)])


def encode_opus(src_wav: Path, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-i", str(src_wav), "-c:a", "libopus", "-b:a", "48k", str(dst)])


def encode_mp3(src_wav: Path, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-i", str(src_wav), "-c:a", "libmp3lame", "-q:a", "4", str(dst)])


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(path, dtype="float32", always_2d=False)
    if data.ndim == 2:
        data = data.mean(axis=1)
    return data, sr


def write_wav(path: Path, samples: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, samples.astype("float32"), sr, subtype="PCM_16")
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_audio.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: ffmpeg audio utilities"
```

---

### Task 5: Text utilities — simplification, punctuation, subtitle parsing

**Files:**
- Create: `backend/shadow/ingest/text.py`, `backend/tests/test_text.py`

**Interfaces:**
- Produces: `to_simplified(s) -> str`; `PUNCT: frozenset[str]`; `is_punct(ch) -> bool`; `strip_punct(s) -> str`; `strip_html(s) -> str`; `@dataclass Cue(start: float, end: float, text: str)`; `parse_subtitles(content: str, filename: str) -> list[Cue]` (SRT, VTT, or plain text lines with no timing → `start=end=-1`).

- [ ] **Step 1: Failing tests**

`backend/tests/test_text.py`:
```python
from shadow.ingest.text import to_simplified, strip_punct, parse_subtitles, strip_html, is_punct

SRT = """1
00:00:01,000 --> 00:00:02,500
你好，世界。

2
00:00:03,000 --> 00:00:04,000
<i>再見</i>
"""

VTT = """WEBVTT

00:01.000 --> 00:02.500
你好

00:03.000 --> 00:04.000
再见
"""


def test_simplified():
    assert to_simplified("再見世界") == "再见世界"


def test_punct():
    assert strip_punct("你好，世界。！？") == "你好世界"
    assert is_punct("，") and not is_punct("你")


def test_strip_html():
    assert strip_html('<div class="x">你好<br>世界</div>&nbsp;') == "你好 世界"


def test_parse_srt_simplifies_and_strips_tags():
    cues = parse_subtitles(SRT, "a.srt")
    assert cues[0].start == 1.0 and cues[0].end == 2.5 and cues[0].text == "你好，世界。"
    assert cues[1].text == "再见"


def test_parse_vtt():
    cues = parse_subtitles(VTT, "a.vtt")
    assert [c.text for c in cues] == ["你好", "再见"]
    assert cues[1].start == 3.0


def test_parse_plain():
    cues = parse_subtitles("第一句。\n\n第二句。\n", "a.txt")
    assert [c.text for c in cues] == ["第一句。", "第二句。"]
    assert cues[0].start == -1
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_text.py -q`
Expected: FAIL, `ImportError`

- [ ] **Step 3: Implement**

`backend/shadow/ingest/text.py`:
```python
from __future__ import annotations
import html
import re
from dataclasses import dataclass
from opencc import OpenCC

_t2s = OpenCC("t2s")

PUNCT = frozenset("，。！？；：、“”‘’（）《》〈〉【】…—·,.!?;:()\"'[]<>-~～ 　\n\t")


def to_simplified(s: str) -> str:
    return _t2s.convert(s)


def is_punct(ch: str) -> bool:
    return ch in PUNCT


def strip_punct(s: str) -> str:
    return "".join(ch for ch in s if not is_punct(ch))


_TAG = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = _TAG.sub("", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Cue:
    start: float
    end: float
    text: str


_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})")


def _ts(s: str) -> float:
    m = _TIME.search(s)
    if not m:
        raise ValueError(f"bad timestamp: {s}")
    h, mi, se, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(se) + int(ms) / 1000


def parse_subtitles(content: str, filename: str) -> list[Cue]:
    name = filename.lower()
    if name.endswith(".srt") or name.endswith(".vtt"):
        cues: list[Cue] = []
        for block in re.split(r"\n\s*\n", content.strip().replace("\r", "")):
            lines = [ln for ln in block.split("\n") if ln.strip()]
            if not lines or lines[0].upper().startswith("WEBVTT") or lines[0].upper().startswith("NOTE"):
                continue
            if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
                lines = lines[1:]
            if "-->" not in lines[0]:
                continue
            a, b = lines[0].split("-->")
            text = to_simplified(strip_html(" ".join(lines[1:])))
            if text:
                cues.append(Cue(_ts(a), _ts(b), text))
        return cues
    return [Cue(-1, -1, to_simplified(strip_html(ln))) for ln in content.splitlines() if ln.strip()]
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_text.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: text utils and subtitle parsing"
```

---

### Task 6: Transcript model and construction from cues

**Files:**
- Create: `backend/shadow/ingest/transcript.py`, `backend/tests/test_transcript.py`

**Interfaces:**
- Produces: `@dataclass TimedChar(c: str, start: float, end: float)`; `@dataclass Transcript(chars: list[TimedChar], segments: list[tuple[int, int]])` where `segments` are inclusive coarse char-index ranges; `Transcript.text -> str`; `Transcript.to_json()/from_json()`; `transcript_from_cues(cues: list[Cue]) -> Transcript` (interpolates per-character times inside each cue; punctuation gets zero-length at previous char's end; enforces monotonic non-decreasing times across overlapping/out-of-order cues).

- [ ] **Step 1: Failing tests**

`backend/tests/test_transcript.py`:
```python
from shadow.ingest.text import Cue
from shadow.ingest.transcript import transcript_from_cues, Transcript


def test_interpolates_times_per_char():
    tr = transcript_from_cues([Cue(1.0, 2.0, "你好。")])
    assert tr.text == "你好。"
    assert tr.chars[0].start == 1.0 and abs(tr.chars[1].end - 2.0) < 1e-6
    assert tr.chars[2].start == tr.chars[2].end == tr.chars[1].end   # punctuation zero-length
    assert tr.segments == [(0, 2)]


def test_overlapping_and_unordered_cues_stay_monotonic():
    tr = transcript_from_cues([Cue(3.0, 4.0, "后面"), Cue(1.0, 3.5, "前面")])
    times = [c.start for c in tr.chars] + [tr.chars[-1].end]
    assert times == sorted(times)
    assert tr.text == "前面后面"
    assert tr.segments == [(0, 1), (2, 3)]


def test_json_roundtrip():
    tr = transcript_from_cues([Cue(0.0, 1.0, "好")])
    assert Transcript.from_json(tr.to_json()).text == "好"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_transcript.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

`backend/shadow/ingest/transcript.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any
from shadow.ingest.text import Cue, is_punct


@dataclass
class TimedChar:
    c: str
    start: float
    end: float


@dataclass
class Transcript:
    chars: list[TimedChar] = field(default_factory=list)
    segments: list[tuple[int, int]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(ch.c for ch in self.chars)

    def to_json(self) -> dict[str, Any]:
        return {"chars": [asdict(c) for c in self.chars], "segments": [list(s) for s in self.segments]}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Transcript":
        return cls([TimedChar(**c) for c in d["chars"]], [tuple(s) for s in d["segments"]])


def chars_with_interpolated_times(text: str, start: float, end: float) -> list[TimedChar]:
    speech = [i for i, ch in enumerate(text) if not is_punct(ch)]
    n = max(len(speech), 1)
    step = (end - start) / n
    out: list[TimedChar] = []
    k = 0
    last_end = start
    for i, ch in enumerate(text):
        if is_punct(ch):
            out.append(TimedChar(ch, last_end, last_end))
        else:
            s, e = start + k * step, start + (k + 1) * step
            out.append(TimedChar(ch, s, e))
            last_end = e
            k += 1
    return out


def transcript_from_cues(cues: list[Cue]) -> Transcript:
    ordered = sorted(cues, key=lambda c: c.start)
    tr = Transcript()
    floor = 0.0
    for cue in ordered:
        start = max(cue.start, floor)
        end = max(cue.end, start)
        chars = chars_with_interpolated_times(cue.text, start, end)
        if not chars:
            continue
        a = len(tr.chars)
        tr.chars.extend(chars)
        tr.segments.append((a, len(tr.chars) - 1))
        floor = end
    return tr
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_transcript.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: transcript model built from subtitle cues"
```

---

### Task 7: ASR interface, Paraformer adapter, fake

**Files:**
- Create: `backend/shadow/ingest/asr.py`, `backend/tests/test_asr.py`

**Interfaces:**
- Produces: `class ASR(Protocol): def transcribe(self, wav_path: Path) -> Transcript`; `FakeASR(transcript: Transcript)`; `ParaformerASR(model_id: str, device: str)` lazily creating `funasr.AutoModel(model=model_id, vad_model="fsmn-vad", punc_model="ct-punc", device=device, disable_update=True)` and calling `generate(input=str(wav_path), sentence_timestamp=True, batch_size_s=300)`; `transcript_from_funasr(result: dict) -> Transcript` (pure, tested without the model).

- [ ] **Step 1: Failing tests**

`backend/tests/test_asr.py`:
```python
from shadow.ingest.asr import transcript_from_funasr, FakeASR
from shadow.ingest.transcript import Transcript


def test_funasr_sentence_info_with_matching_timestamps():
    result = {
        "text": "你好，世界。再见。",
        "sentence_info": [
            {"text": "你好，世界。", "start": 1000, "end": 2000,
             "timestamp": [[1000, 1200], [1200, 1400], [1500, 1700], [1700, 2000]]},
            {"text": "再见。", "start": 2500, "end": 3000, "timestamp": [[2500, 2700], [2700, 3000]]},
        ],
    }
    tr = transcript_from_funasr(result)
    assert tr.text == "你好，世界。再见。"
    assert tr.chars[0].start == 1.0 and tr.chars[3].end == 1.7 and tr.chars[4].end == 2.0
    assert tr.chars[2].start == tr.chars[2].end == 1.4           # comma zero-length
    assert tr.segments == [(0, 5), (6, 8)]


def test_funasr_timestamp_count_mismatch_falls_back_to_interpolation():
    result = {"text": "你好世界", "sentence_info": [{"text": "你好世界", "start": 0, "end": 2000, "timestamp": [[0, 500]]}]}
    tr = transcript_from_funasr(result)
    assert [round(c.start, 2) for c in tr.chars] == [0.0, 0.5, 1.0, 1.5]


def test_funasr_without_sentence_info_uses_whole_text():
    tr = transcript_from_funasr({"text": "大家好", "timestamp": [[0, 300], [300, 600], [600, 900]]})
    assert tr.text == "大家好" and tr.chars[2].end == 0.9 and tr.segments == [(0, 2)]


def test_funasr_empty_text_gives_empty_transcript():
    tr = transcript_from_funasr({"text": "", "sentence_info": []})
    assert tr.chars == [] and tr.segments == []


def test_fake_asr_returns_given_transcript(tmp_path):
    tr = Transcript()
    assert FakeASR(tr).transcribe(tmp_path / "x.wav") is tr
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_asr.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

`backend/shadow/ingest/asr.py`:
```python
from __future__ import annotations
from pathlib import Path
from typing import Any, Protocol
from shadow.ingest.text import is_punct, to_simplified
from shadow.ingest.transcript import Transcript, TimedChar, chars_with_interpolated_times


class ASR(Protocol):
    def transcribe(self, wav_path: Path) -> Transcript: ...


class FakeASR:
    def __init__(self, transcript: Transcript):
        self._tr = transcript

    def transcribe(self, wav_path: Path) -> Transcript:
        return self._tr


def _sentence_chars(text: str, start_ms: float, end_ms: float, ts: list[list[float]] | None) -> list[TimedChar]:
    text = to_simplified(text)
    speech_idx = [i for i, ch in enumerate(text) if not is_punct(ch)]
    if ts and len(ts) == len(speech_idx):
        out: list[TimedChar] = []
        last_end = start_ms / 1000
        k = 0
        for i, ch in enumerate(text):
            if is_punct(ch):
                out.append(TimedChar(ch, last_end, last_end))
            else:
                s, e = ts[k][0] / 1000, ts[k][1] / 1000
                out.append(TimedChar(ch, s, e))
                last_end = e
                k += 1
        return out
    return chars_with_interpolated_times(text, start_ms / 1000, end_ms / 1000)


def transcript_from_funasr(result: dict[str, Any]) -> Transcript:
    tr = Transcript()
    sentences = result.get("sentence_info") or []
    if not sentences:
        text = result.get("text") or ""
        if not text.strip():
            return tr
        ts = result.get("timestamp")
        end_ms = ts[-1][1] if ts else 0
        start_ms = ts[0][0] if ts else 0
        sentences = [{"text": text, "start": start_ms, "end": end_ms, "timestamp": ts}]
    for s in sentences:
        chars = _sentence_chars(s.get("text", ""), float(s.get("start", 0)), float(s.get("end", 0)), s.get("timestamp"))
        if not chars:
            continue
        a = len(tr.chars)
        tr.chars.extend(chars)
        tr.segments.append((a, len(tr.chars) - 1))
    return tr


class ParaformerASR:
    def __init__(self, model_id: str, device: str):
        self.model_id, self.device = model_id, device
        self._model = None

    def _load(self):
        if self._model is None:
            from funasr import AutoModel
            self._model = AutoModel(model=self.model_id, vad_model="fsmn-vad", punc_model="ct-punc",
                                    device=self.device, disable_update=True)
        return self._model

    def transcribe(self, wav_path: Path) -> Transcript:
        res = self._load().generate(input=str(wav_path), sentence_timestamp=True, batch_size_s=300)
        return transcript_from_funasr(res[0] if res else {"text": ""})
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_asr.py -q`
Expected: `5 passed`

- [ ] **Step 5: Real-model smoke test (deselected by default)**

Append to `backend/tests/test_asr.py`:
```python
import pytest


@pytest.mark.models
def test_paraformer_real(tmp_path):
    from shadow.ingest.asr import ParaformerASR
    from tests.helpers import make_tone_wav
    asr = ParaformerASR("iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch", "cpu")
    tr = asr.transcribe(make_tone_wav(tmp_path / "t.wav", 2.0))
    assert isinstance(tr, Transcript)
```

Run once with models installed: `uv sync --extra dev --extra models && uv run pytest -m models tests/test_asr.py -q`. Expected: `1 passed` (text may be empty for a sine tone; the point is the adapter runs end to end).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: ASR interface with Paraformer adapter and fake"
```

---

### Task 8: Rectification — chunking, LLM call, validation, fallback, cache

**Files:**
- Create: `backend/shadow/ingest/rectify.py`, `backend/shadow/ingest/llm.py`, `backend/tests/test_rectify.py`, `backend/fixtures/rectify_response_1.json`

**Interfaces:**
- Produces in `llm.py`: `class RectSentence(BaseModel): from_: int (alias "from"), to: int, text: str`; `class RectifyOutput(BaseModel): sentences: list[RectSentence]`; `class LLM(Protocol): def rectify(self, chunk_chars: list[str], context_chars: list[str]) -> RectifyOutput; def translate(self, sentences: list[str]) -> list[str]`; `AnthropicLLM(model, effort, cache_dir: Path)`; `FakeLLM(rectify_fn, translate_fn)`.
- Produces in `rectify.py`: `@dataclass RectSentenceOut(char_from: int, char_to: int, text: str)` (absolute indices into the transcript); `make_chunks(tr: Transcript, max_chars=600, context=60) -> list[Chunk]` where `Chunk(start: int, end: int, context_start: int)`; `validate(out: RectifyOutput, chunk: Chunk, tr: Transcript) -> list[RectSentenceOut] | None`; `fallback_sentences(tr, chunk) -> list[RectSentenceOut]`; `rectify_transcript(tr, llm, enabled=True) -> list[RectSentenceOut]`.

- [ ] **Step 1: Failing tests**

`backend/tests/test_rectify.py`:
```python
import json
from pathlib import Path
from shadow.ingest.text import Cue
from shadow.ingest.transcript import transcript_from_cues
from shadow.ingest.llm import RectifyOutput, RectSentence, FakeLLM
from shadow.ingest.rectify import make_chunks, validate, fallback_sentences, rectify_transcript, Chunk

TEXT = "我今天想跟你们聊一聊学中文的方法，其实方法有很多，但是最重要的是坚持。"


def tr_one():
    return transcript_from_cues([Cue(0.0, 10.0, TEXT)])


def test_chunks_cut_at_segment_boundaries_and_carry_context():
    cues = [Cue(i, i + 1, "一二三四五六七八九十" * 10) for i in range(8)]   # 8 × 100 chars
    tr = transcript_from_cues(cues)
    chunks = make_chunks(tr, max_chars=250, context=60)
    assert [(c.start, c.end) for c in chunks] == [(0, 199), (200, 399), (400, 599), (600, 799)]
    assert chunks[0].context_start == 0 and chunks[1].context_start == 140


def test_validate_accepts_good_output():
    tr = tr_one()
    chunk = make_chunks(tr)[0]
    out = RectifyOutput(sentences=[
        RectSentence(**{"from": 0, "to": 15, "text": "我今天想跟你们聊一聊学中文的方法，"}),
        RectSentence(**{"from": 16, "to": 23, "text": "其实方法有很多，"}),
        RectSentence(**{"from": 24, "to": 34, "text": "但是最重要的是坚持。"}),
    ])
    res = validate(out, chunk, tr)
    assert res is not None and [(s.char_from, s.char_to) for s in res] == [(0, 15), (16, 23), (24, 34)]


def test_validate_rejects_gap_overlap_bad_text_and_context_overlap():
    tr = tr_one()
    chunk = Chunk(start=10, end=34, context_start=0)
    bad_gap = RectifyOutput(sentences=[RectSentence(**{"from": 10, "to": 20, "text": "x"}), RectSentence(**{"from": 22, "to": 34, "text": "y"})])
    assert validate(bad_gap, chunk, tr) is None
    into_context = RectifyOutput(sentences=[RectSentence(**{"from": 9, "to": 34, "text": TEXT[9:35]})])
    assert validate(into_context, chunk, tr) is None
    wrong_text = RectifyOutput(sentences=[RectSentence(**{"from": 10, "to": 34, "text": "完全不一样的句子完全不一样的句子完全不一样"})])
    assert validate(wrong_text, chunk, tr) is None
    too_short = RectifyOutput(sentences=[RectSentence(**{"from": 10, "to": 10, "text": "聊"}), RectSentence(**{"from": 11, "to": 34, "text": TEXT[11:35]})])
    assert validate(too_short, chunk, tr) is None


def test_fallback_splits_at_sentence_punct():
    tr = tr_one()
    res = fallback_sentences(tr, make_chunks(tr)[0])
    assert [s.text for s in res] == ["我今天想跟你们聊一聊学中文的方法，", "其实方法有很多，", "但是最重要的是坚持。"]


def test_rectify_transcript_uses_llm_then_falls_back_per_chunk():
    tr = tr_one()
    calls = []

    def bad(chunk_chars, context_chars):
        calls.append(len(chunk_chars))
        return RectifyOutput(sentences=[])
    res = rectify_transcript(tr, FakeLLM(bad, lambda xs: xs))
    assert calls == [35] and len(res) == 3


def test_recorded_response_fixture_validates():
    tr = tr_one()
    data = json.loads(Path(__file__).parents[1].joinpath("fixtures/rectify_response_1.json").read_text())
    out = RectifyOutput.model_validate(data)
    assert validate(out, make_chunks(tr)[0], tr) is not None
```

`backend/fixtures/rectify_response_1.json`:
```json
{"sentences": [
  {"from": 0, "to": 15, "text": "我今天想跟你们聊一聊学中文的方法，"},
  {"from": 16, "to": 23, "text": "其实方法有很多，"},
  {"from": 24, "to": 34, "text": "但是最重要的是坚持。"}
]}
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_rectify.py -q`
Expected: FAIL

- [ ] **Step 3: Implement `llm.py`**

```python
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Protocol
from pydantic import BaseModel, ConfigDict, Field


class RectSentence(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    from_: int = Field(alias="from")
    to: int
    text: str


class RectifyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sentences: list[RectSentence]


class TranslateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    translations: list[str]


class LLM(Protocol):
    def rectify(self, chunk_chars: list[str], context_chars: list[str]) -> RectifyOutput: ...
    def translate(self, sentences: list[str]) -> list[str]: ...


class FakeLLM:
    def __init__(self, rectify_fn: Callable[[list[str], list[str]], RectifyOutput],
                 translate_fn: Callable[[list[str]], list[str]]):
        self._r, self._t = rectify_fn, translate_fn

    def rectify(self, chunk_chars, context_chars):
        return self._r(chunk_chars, context_chars)

    def translate(self, sentences):
        return self._t(sentences)


RECTIFY_SYSTEM = (
    "You repair Mandarin ASR transcripts for shadowing practice. You receive characters with indices. "
    "Group them into natural, shadowable sentences or clauses of roughly {min_chars}-{max_chars} characters; "
    "prefer splitting long sentences at commas, 的时候, 但是, 所以. For each group return from/to (inclusive "
    "indices into the given chars, never into the context) and text: the corrected, punctuated simplified-Chinese "
    "text for exactly those characters. Fix homophone errors, punctuation and clearly wrong fillers only. Do not "
    "paraphrase, add or drop content. Ranges must be contiguous, non-overlapping and cover every index."
)


class AnthropicLLM:
    def __init__(self, model: str, effort: str, cache_dir: Path, min_chars: int = 6, max_chars: int = 25):
        import anthropic
        self._client = anthropic.Anthropic()
        self.model, self.effort, self.cache_dir = model, effort, cache_dir
        self.min_chars, self.max_chars = min_chars, max_chars

    def _cached(self, key: str, make: Callable[[], dict]) -> dict:
        p = self.cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"
        if p.exists():
            return json.loads(p.read_text())
        data = make()
        p.write_text(json.dumps(data, ensure_ascii=False))
        return data

    def _call(self, system: str, user: str, schema_model: type[BaseModel]) -> dict:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort,
                           "format": {"type": "json_schema", "schema": schema_model.model_json_schema(by_alias=True)}},
        )
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)

    def rectify(self, chunk_chars: list[str], context_chars: list[str]) -> RectifyOutput:
        payload = {
            "context_before": "".join(context_chars),
            "chars": [{"i": i, "c": c} for i, c in enumerate(chunk_chars)],
        }
        key = "rectify:" + self.model + ":" + "".join(chunk_chars)
        data = self._cached(key, lambda: self._call(
            RECTIFY_SYSTEM.format(min_chars=self.min_chars, max_chars=self.max_chars),
            json.dumps(payload, ensure_ascii=False), RectifyOutput))
        return RectifyOutput.model_validate(data)

    def translate(self, sentences: list[str]) -> list[str]:
        key = "translate:" + self.model + ":" + "\n".join(sentences)
        data = self._cached(key, lambda: self._call(
            "Translate each Mandarin sentence into natural English. Return exactly one translation per input, in order.",
            json.dumps({"sentences": sentences}, ensure_ascii=False), TranslateOutput))
        out = TranslateOutput.model_validate(data).translations
        return out if len(out) == len(sentences) else [""] * len(sentences)
```

Note: `from_` carries chunk-relative indices in the API payload; `rectify.py` converts to absolute.

- [ ] **Step 4: Implement `rectify.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from rapidfuzz.distance import Levenshtein
from shadow.ingest.llm import LLM, RectifyOutput
from shadow.ingest.text import is_punct, strip_punct
from shadow.ingest.transcript import Transcript

SENTENCE_END = set("。！？；")
CLAUSE_END = set("，、：")


@dataclass
class Chunk:
    start: int            # absolute, inclusive
    end: int              # absolute, inclusive
    context_start: int    # absolute index where context-only prefix begins


@dataclass
class RectSentenceOut:
    char_from: int
    char_to: int
    text: str


def make_chunks(tr: Transcript, max_chars: int = 600, context: int = 60) -> list[Chunk]:
    chunks: list[Chunk] = []
    if not tr.chars:
        return chunks
    cur_start = 0
    for i, (a, b) in enumerate(tr.segments):
        is_last = i == len(tr.segments) - 1
        next_len = tr.segments[i + 1][1] - cur_start + 1 if not is_last else None
        if is_last or next_len > max_chars:
            chunks.append(Chunk(cur_start, b, max(0, cur_start - context)))
            cur_start = b + 1
    return chunks


def validate(out: RectifyOutput, chunk: Chunk, tr: Transcript) -> list[RectSentenceOut] | None:
    sents = sorted(out.sentences, key=lambda s: s.from_)
    if not sents:
        return None
    expected = chunk.start
    result: list[RectSentenceOut] = []
    for s in sents:
        a, b = chunk.start + s.from_, chunk.start + s.to
        if a != expected or b < a or b > chunk.end:
            return None
        raw = "".join(c.c for c in tr.chars[a:b + 1])
        raw_speech, text_speech = strip_punct(raw), strip_punct(s.text)
        if not (2 <= len(s.text) <= 60):
            return None
        if Levenshtein.distance(text_speech, raw_speech) / max(len(raw_speech), 1) >= 0.25:
            return None
        result.append(RectSentenceOut(a, b, s.text))
        expected = b + 1
    if expected != chunk.end + 1:
        return None
    return result


def fallback_sentences(tr: Transcript, chunk: Chunk) -> list[RectSentenceOut]:
    out: list[RectSentenceOut] = []
    a = chunk.start
    seg_ends = {b for _, b in tr.segments}
    for i in range(chunk.start, chunk.end + 1):
        ch = tr.chars[i].c
        nxt = tr.chars[i + 1].c if i + 1 <= chunk.end else ""
        at_end = (ch in SENTENCE_END or ch in CLAUSE_END or i in seg_ends or i == chunk.end) and not is_punct(nxt)
        if at_end:
            text = "".join(c.c for c in tr.chars[a:i + 1])
            if strip_punct(text):
                out.append(RectSentenceOut(a, i, text))
            a = i + 1
    return out


def rectify_transcript(tr: Transcript, llm: LLM | None, enabled: bool = True,
                       max_chars: int = 600, context: int = 60) -> list[RectSentenceOut]:
    sentences: list[RectSentenceOut] = []
    for chunk in make_chunks(tr, max_chars, context):
        validated = None
        if enabled and llm is not None:
            try:
                chunk_chars = [c.c for c in tr.chars[chunk.start:chunk.end + 1]]
                ctx = [c.c for c in tr.chars[chunk.context_start:chunk.start]]
                validated = validate(llm.rectify(chunk_chars, ctx), chunk, tr)
            except Exception:
                validated = None
        sentences.extend(validated if validated is not None else fallback_sentences(tr, chunk))
    return sentences
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/test_rectify.py -q`
Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: LLM rectification with validation, fallback and cache"
```

---

### Task 9: Forced alignment — interface, MMS_FA, Qwen3, fake, sentence timing

**Files:**
- Create: `backend/shadow/ingest/align.py`, `backend/tests/test_align.py`

**Interfaces:**
- Produces: `@dataclass Span(ch: str, start: float, end: float, conf: float)`; `class Aligner(Protocol): def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]` (times relative to the given audio, one span per non-punctuation character); `FakeAligner()` (uniform spans); `MmsAligner(device)`; `Qwen3Aligner(device)`; `make_aligner(name: str, device: str) -> Aligner`; `align_in_window(aligner, wav, sr, text, win_start, win_end) -> list[Span]` (absolute times); `sentence_bounds(spans, pad_s, prev_end, next_start, total) -> tuple[float, float]`.

- [ ] **Step 1: Failing tests**

`backend/tests/test_align.py`:
```python
import numpy as np
from shadow.ingest.align import FakeAligner, align_in_window, sentence_bounds, romanise_for_mms


def test_fake_aligner_uniform_spans_skip_punct():
    wav = np.zeros(16000, dtype="float32")
    spans = FakeAligner().align(wav, 16000, "你好，世界。")
    assert [s.ch for s in spans] == ["你", "好", "世", "界"]
    assert spans[0].start == 0.0 and abs(spans[-1].end - 1.0) < 1e-6


def test_align_in_window_offsets_to_absolute():
    wav = np.zeros(16000 * 10, dtype="float32")
    spans = align_in_window(FakeAligner(), wav, 16000, "你好", 4.0, 6.0)
    assert abs(spans[0].start - 4.0) < 1e-6 and abs(spans[-1].end - 6.0) < 1e-6


def test_sentence_bounds_pad_and_clamp():
    from shadow.ingest.align import Span
    spans = [Span("你", 1.0, 1.4, 1.0), Span("好", 1.4, 1.9, 1.0)]
    assert sentence_bounds(spans, 0.12, prev_end=0.0, next_start=10.0, total=20.0) == (0.88, 2.02)
    assert sentence_bounds(spans, 0.12, prev_end=0.95, next_start=1.95, total=20.0) == (0.95, 1.95)
    assert sentence_bounds(spans, 0.12, prev_end=0.0, next_start=10.0, total=1.95) == (0.88, 1.95)


def test_romanise_for_mms():
    assert romanise_for_mms("你好，绿") == ["ni", "hao", "lu"]
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_align.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

`backend/shadow/ingest/align.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
import numpy as np
from pypinyin import lazy_pinyin, Style
from shadow.ingest.text import is_punct


@dataclass
class Span:
    ch: str
    start: float
    end: float
    conf: float


class Aligner(Protocol):
    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]: ...


def speech_chars(text: str) -> list[str]:
    return [c for c in text if not is_punct(c)]


def romanise_for_mms(text: str) -> list[str]:
    out = []
    for p in lazy_pinyin(speech_chars(text), style=Style.NORMAL):
        p = p.replace("ü", "u").replace("v", "u")
        out.append("".join(ch for ch in p.lower() if "a" <= ch <= "z") or "a")
    return out


class FakeAligner:
    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]:
        chars = speech_chars(text)
        dur = len(wav) / sr
        n = max(len(chars), 1)
        return [Span(c, i * dur / n, (i + 1) * dur / n, 1.0) for i, c in enumerate(chars)]


class MmsAligner:
    def __init__(self, device: str):
        self.device = device
        self._bundle = self._model = self._tok = self._al = None

    def _load(self):
        if self._model is None:
            import torch, torchaudio
            self._bundle = torchaudio.pipelines.MMS_FA
            self._model = self._bundle.get_model(with_star=False).to(self.device).eval()
            self._tok = self._bundle.get_tokenizer()
            self._al = self._bundle.get_aligner()
        return self._model

    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]:
        import torch
        model = self._load()
        chars = speech_chars(text)
        if not chars:
            return []
        words = romanise_for_mms(text)
        x = torch.from_numpy(wav).float().unsqueeze(0).to(self.device)
        if sr != self._bundle.sample_rate:
            import torchaudio.functional as F
            x = F.resample(x, sr, self._bundle.sample_rate)
        with torch.inference_mode():
            emission, _ = model(x)
        token_spans = self._al(emission[0], self._tok(words))
        ratio = x.size(1) / emission.size(1) / self._bundle.sample_rate
        out: list[Span] = []
        for ch, spans in zip(chars, token_spans):
            out.append(Span(ch, spans[0].start * ratio, spans[-1].end * ratio,
                            float(sum(s.score for s in spans) / len(spans))))
        return out


class Qwen3Aligner:
    def __init__(self, device: str):
        self.device = device
        self._model = None

    def _load(self):
        if self._model is None:
            import torch
            from qwen_asr import Qwen3ForcedAligner
            self._model = Qwen3ForcedAligner.from_pretrained(
                "Qwen/Qwen3-ForcedAligner-0.6B", dtype=torch.bfloat16,
                device_map="cuda:0" if self.device == "cuda" else "cpu")
        return self._model

    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]:
        chars = speech_chars(text)
        if not chars:
            return []
        results = self._load().align(audio=(wav, sr), text="".join(chars), language="Chinese")
        items = results[0]
        out = [Span(it.text, float(it.start_time), float(it.end_time), 1.0) for it in items if not is_punct(it.text)]
        if len(out) != len(chars):            # aligner merged or split units; fall back to uniform
            return FakeAligner().align(wav, sr, text)
        return out


def make_aligner(name: str, device: str) -> Aligner:
    if name == "qwen3_fa":
        return Qwen3Aligner(device)
    if name == "mms_fa":
        return MmsAligner(device)
    if name == "fake":
        return FakeAligner()
    raise ValueError(f"unknown aligner {name}")


def align_in_window(aligner: Aligner, wav: np.ndarray, sr: int, text: str,
                    win_start: float, win_end: float) -> list[Span]:
    a = max(0, int(win_start * sr))
    b = min(len(wav), int(win_end * sr))
    spans = aligner.align(wav[a:b], sr, text)
    off = a / sr
    return [Span(s.ch, s.start + off, s.end + off, s.conf) for s in spans]


def sentence_bounds(spans: list[Span], pad_s: float, prev_end: float, next_start: float, total: float) -> tuple[float, float]:
    start = max(spans[0].start - pad_s, prev_end, 0.0)
    end = min(spans[-1].end + pad_s, next_start, total)
    return (round(start, 3), round(max(end, start), 3))
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_align.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: forced alignment interface with MMS_FA, Qwen3 and fake"
```

---

### Task 10: Enrichment — words/pinyin, translation batching, clips

**Files:**
- Create: `backend/shadow/ingest/enrich.py`, `backend/tests/test_enrich.py`

**Interfaces:**
- Produces: `words_for(text: str) -> list[dict]` with keys `word, pinyin, tones (list[int], 0 = neutral), char_from, char_to` (indices into `text`, punctuation-only tokens skipped); `syllables_for(text) -> list[dict]` with `ch, pinyin, pinyin_toneless, tone` per speech character; `translate_all(llm, texts, batch=20) -> list[str]`; `make_clips(files: FileLayout, lesson_id, idx, source_wav, start_s, end_s) -> tuple[Path, Path]`.

- [ ] **Step 1: Failing tests**

`backend/tests/test_enrich.py`:
```python
from shadow.ingest.enrich import words_for, syllables_for, translate_all
from shadow.ingest.llm import FakeLLM


def test_words_for_groups_by_jieba_and_marks_ranges():
    w = words_for("我今天不去。")
    assert w[0]["word"] == "我" and w[0]["char_from"] == 0 and w[0]["char_to"] == 0
    assert w[1]["word"] == "今天" and w[1]["pinyin"] == "jīntiān" and w[1]["tones"] == [1, 1]
    assert w[1]["syllables"][1] == {"ch": "天", "pinyin": "tiān", "pinyin_toneless": "tian", "tone": 1}
    assert all(x["word"] != "。" for x in w)


def test_tone_sandhi_and_neutral():
    s = syllables_for("你好们")
    assert [x["tone"] for x in s][:2] == [2, 3]            # 3+3 → 2+3
    assert s[2]["tone"] == 0 and s[2]["pinyin_toneless"] == "men"
    assert s[0]["pinyin_toneless"] == "ni"


def test_translate_batches_of_20():
    sizes = []

    def t(xs):
        sizes.append(len(xs)); return [f"en:{x}" for x in xs]
    out = translate_all(FakeLLM(lambda a, b: None, t), [f"句{i}" for i in range(45)])
    assert sizes == [20, 20, 5] and out[44] == "en:句44"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_enrich.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

`backend/shadow/ingest/enrich.py`:
```python
from __future__ import annotations
import re
from pathlib import Path
import jieba
from pypinyin import pinyin, lazy_pinyin, Style
from shadow.ingest import audio
from shadow.ingest.llm import LLM
from shadow.ingest.text import is_punct, strip_punct
from shadow.store.files import FileLayout

jieba.setLogLevel(60)
_DIGIT = re.compile(r"\d")


def _tone_of(tone3: str) -> int:
    m = _DIGIT.search(tone3)
    t = int(m.group()) if m else 5
    return 0 if t == 5 else t


def words_for(text: str) -> list[dict]:
    out: list[dict] = []
    pos = 0
    for word in jieba.lcut(text):
        a, b = pos, pos + len(word) - 1
        pos += len(word)
        if not strip_punct(word):
            continue
        tone = pinyin(word, style=Style.TONE, heteronym=False, tone_sandhi=True, neutral_tone_with_five=True)
        tone3 = pinyin(word, style=Style.TONE3, heteronym=False, tone_sandhi=True, neutral_tone_with_five=True)
        normal = lazy_pinyin(word, style=Style.NORMAL)
        tones = [_tone_of(p[0]) for p in tone3]
        out.append({
            "word": word,
            "pinyin": "".join(p[0] for p in tone),
            "tones": tones,
            "char_from": a, "char_to": b,
            "syllables": [{"ch": ch, "pinyin": p[0], "pinyin_toneless": n.replace("ü", "v"), "tone": t}
                          for ch, p, t, n in zip(word, tone, tones, normal)],
        })
    return out


def syllables_for(text: str) -> list[dict]:
    chars = [c for c in text if not is_punct(c)]
    out = [s for w in words_for(text) for s in w["syllables"] if not is_punct(s["ch"])]
    assert len(out) == len(chars), (text, out)
    return out


def translate_all(llm: LLM, texts: list[str], batch: int = 20) -> list[str]:
    out: list[str] = []
    for i in range(0, len(texts), batch):
        out.extend(llm.translate(texts[i:i + batch]))
    return out


def make_clips(files: FileLayout, lesson_id: int, idx: int, source_wav: Path, start_s: float, end_s: float) -> tuple[Path, Path]:
    wav, opus = files.clip_wav(lesson_id, idx), files.clip_opus(lesson_id, idx)
    audio.cut(source_wav, wav, start_s, end_s)
    audio.encode_opus(wav, opus)
    return wav, opus
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_enrich.py -q`
Expected: `3 passed`. If `test_tone_sandhi_and_neutral` fails on `们`, pypinyin's dictionary may not mark the neutral tone for the isolated character; change the test text to `"你好吗"` and assert on `吗`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: pinyin words, translation batching, clip rendering"
```

---

### Task 11: Dependency container, job runner with SSE, upload ingest pipeline

**Files:**
- Create: `backend/shadow/deps.py`, `backend/shadow/jobs.py`, `backend/shadow/ingest/pipeline.py`, `backend/shadow/api/jobs.py`, `backend/shadow/api/lessons.py` (create endpoint only; rest in Task 13), `backend/shadow/schemas.py`, `backend/tests/test_pipeline.py`, `backend/tests/test_jobs_api.py`
- Modify: `backend/shadow/main.py`, `backend/tests/conftest.py`

**Interfaces:**
- `deps.py`: `class Deps: asr: ASR, llm: LLM | None, aligner: Aligner, files: FileLayout, settings: Settings; loaded_models() -> list[str]`; `build_deps(settings) -> Deps` (real adapters), `fake_deps(settings, transcript) -> Deps`.
- `jobs.py`: `@dataclass JobState(id: str, stage: str, fraction: float, status: "queued|running|done|error", error: str | None, lesson_id: int | None)`; `class JobManager: submit(fn: Callable[[Progress], None], lesson_id) -> str; get(job_id) -> JobState; events(job_id) -> AsyncIterator[dict]; start(loop) / stop()`; `Progress = Callable[[str, float], None]`.
- `pipeline.py`: `ingest_upload(deps, engine, lesson_id: int, media_path: Path, subtitle: tuple[str, str] | None, progress: Progress) -> None` — runs §3.1–3.5, writes `Segment` rows, sets lesson `status`.
- `schemas.py`: `LessonOut, SegmentOut, AttemptOut, SessionOut, JobOut` pydantic models used by routers.
- API: `POST /lessons` multipart `file` (+ optional `subtitles` file, `title`, `speaker`) → `{"job_id", "lesson_id"}`; `GET /jobs/{id}` → `JobOut`; `GET /jobs/{id}/events` SSE with events `{"stage","fraction","status","error","lesson_id"}`, ends after `done|error`.

- [ ] **Step 1: Failing tests**

`backend/tests/conftest.py` (append):
```python
from fastapi.testclient import TestClient
from shadow.config import Settings
from shadow.deps import fake_deps
from shadow.ingest.text import Cue
from shadow.ingest.transcript import transcript_from_cues
from shadow.main import create_app

LESSON_TEXT = [
    (0.0, 3.0, "我今天想跟你们聊一聊学中文的方法。"),
    (3.0, 5.0, "其实方法有很多。"),
    (5.0, 7.5, "但是最重要的是坚持。"),
]


@pytest.fixture
def fake_transcript():
    return transcript_from_cues([Cue(a, b, t) for a, b, t in LESSON_TEXT])


@pytest.fixture
def client(data_dir, fake_transcript):
    settings = Settings(data_dir=data_dir)
    settings.llm.translate = True
    app = create_app(settings, deps=fake_deps(settings, fake_transcript))
    with TestClient(app) as c:
        yield c


def wait_job(client, job_id, timeout=10.0):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")
```

`backend/tests/test_pipeline.py`:
```python
from sqlmodel import Session, select
from shadow.ingest.pipeline import ingest_upload
from shadow.store.models import Lesson, Segment
from shadow.deps import fake_deps
from shadow.config import Settings
from shadow.store.db import make_engine, init_db
from shadow.ingest.transcript import Transcript
from tests.helpers import make_tone_wav


def _lesson(engine):
    with Session(engine) as db:
        l = Lesson(title="t", speaker="s", source_type="upload", source_ref="t.wav")
        db.add(l); db.commit(); db.refresh(l)
        return l.id


def test_ingest_upload_creates_segments(data_dir, fake_transcript, tmp_path):
    settings = Settings(data_dir=data_dir)
    deps = fake_deps(settings, fake_transcript)
    engine = make_engine(data_dir); init_db(engine)
    lid = _lesson(engine)
    stages = []
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), None, lambda s, f: stages.append(s))
    with Session(engine) as db:
        lesson = db.get(Lesson, lid)
        segs = db.exec(select(Segment).where(Segment.lesson_id == lid).order_by(Segment.idx)).all()
    assert lesson.status == "ready" and abs(lesson.duration_s - 8.0) < 0.05
    assert [s.text for s in segs] == ["我今天想跟你们聊一聊学中文的方法。", "其实方法有很多。", "但是最重要的是坚持。"]
    assert segs[0].start_s == 0.0 and segs[0].end_s <= segs[1].start_s
    assert segs[0].words_json[1]["word"] == "今天"
    assert len(segs[0].ref_alignment_json) == 16
    assert segs[0].translation.startswith("en:")
    assert deps.files.clip_wav(lid, 0).exists() and deps.files.clip_opus(lid, 2).exists()
    assert lesson.transcript_json["chars"][0]["c"] == "我"
    assert stages[:2] == ["normalise", "transcribe"] and stages[-1] == "done"


def test_ingest_upload_with_subtitles_skips_asr(data_dir, tmp_path):
    settings = Settings(data_dir=data_dir)
    deps = fake_deps(settings, Transcript())          # ASR would return nothing
    engine = make_engine(data_dir); init_db(engine)
    lid = _lesson(engine)
    srt = "1\n00:00:00,000 --> 00:00:02,000\n大家好。\n\n2\n00:00:02,000 --> 00:00:04,000\n欢迎回来。\n"
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 4.0), ("a.srt", srt), lambda s, f: None)
    with Session(engine) as db:
        assert [s.text for s in db.exec(select(Segment).order_by(Segment.idx)).all()] == ["大家好。", "欢迎回来。"]


def test_ingest_upload_with_no_speech_sets_error(data_dir, tmp_path):
    settings = Settings(data_dir=data_dir)
    deps = fake_deps(settings, Transcript())
    engine = make_engine(data_dir); init_db(engine)
    lid = _lesson(engine)
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 2.0), None, lambda s, f: None)
    with Session(engine) as db:
        lesson = db.get(Lesson, lid)
    assert lesson.status == "error" and "no speech" in lesson.error.lower()
```

`backend/tests/test_jobs_api.py`:
```python
from tests.helpers import make_tone_wav
from tests.conftest import wait_job


def test_post_lesson_runs_job_and_streams_events(client, tmp_path):
    wav = make_tone_wav(tmp_path / "u.wav", 8.0)
    with open(wav, "rb") as f:
        r = client.post("/lessons", files={"file": ("u.wav", f, "audio/wav")}, data={"title": "Up", "speaker": "Me"})
    assert r.status_code == 202
    job_id, lesson_id = r.json()["job_id"], r.json()["lesson_id"]
    j = wait_job(client, job_id)
    assert j["status"] == "done" and j["lesson_id"] == lesson_id
    with client.stream("GET", f"/jobs/{job_id}/events") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert '"status": "done"' in body or '"status":"done"' in body


def test_unknown_job_404(client):
    assert client.get("/jobs/nope").status_code == 404
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_pipeline.py tests/test_jobs_api.py -q`
Expected: FAIL

- [ ] **Step 3: Implement `deps.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from shadow.config import Settings
from shadow.ingest.align import Aligner, FakeAligner, make_aligner
from shadow.ingest.asr import ASR, FakeASR, ParaformerASR
from shadow.ingest.llm import LLM, AnthropicLLM, FakeLLM, RectifyOutput
from shadow.ingest.transcript import Transcript
from shadow.store.files import FileLayout


@dataclass
class Deps:
    asr: ASR
    llm: LLM | None
    aligner: Aligner
    files: FileLayout
    settings: Settings

    def loaded_models(self) -> list[str]:
        out = []
        for name, obj in (("asr", self.asr), ("aligner", self.aligner)):
            if getattr(obj, "_model", None) is not None:
                out.append(name)
        return out


def build_deps(settings: Settings) -> Deps:
    import os
    device = settings.resolved_device()
    files = FileLayout(settings.data_dir)
    llm = None
    if os.environ.get("ANTHROPIC_API_KEY") and (settings.llm.rectify or settings.llm.translate):
        llm = AnthropicLLM(settings.llm.model, settings.llm.effort, files.cache_dir("llm"),
                           settings.segmentation.min_chars, settings.segmentation.max_chars)
    return Deps(asr=ParaformerASR(settings.models.asr, device), llm=llm,
                aligner=make_aligner(settings.resolved_aligner(), device), files=files, settings=settings)


def fake_deps(settings: Settings, transcript: Transcript) -> Deps:
    def rectify(chunk_chars, ctx):
        return RectifyOutput(sentences=[])          # forces punctuation fallback in tests
    llm = FakeLLM(rectify, lambda xs: [f"en:{x}" for x in xs])
    return Deps(asr=FakeASR(transcript), llm=llm, aligner=FakeAligner(),
                files=FileLayout(settings.data_dir), settings=settings)
```

- [ ] **Step 4: Implement `jobs.py`**

```python
from __future__ import annotations
import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from typing import AsyncIterator, Callable

Progress = Callable[[str, float], None]


@dataclass
class JobState:
    id: str
    stage: str = "queued"
    fraction: float = 0.0
    status: str = "queued"           # queued | running | done | error
    error: str | None = None
    lesson_id: int | None = None


class JobManager:
    def __init__(self):
        self._jobs: dict[str, JobState] = {}
        self._subs: dict[str, list[asyncio.Queue]] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._worker = self._loop.create_task(self._run())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def get(self, job_id: str) -> JobState | None:
        return self._jobs.get(job_id)

    def submit(self, fn: Callable[[Progress], None], lesson_id: int | None) -> str:
        job_id = uuid.uuid4().hex[:12]
        self._jobs[job_id] = JobState(id=job_id, lesson_id=lesson_id)
        self._subs[job_id] = []
        self._queue.put_nowait((job_id, fn))
        return job_id

    def _publish(self, job_id: str) -> None:
        snap = asdict(self._jobs[job_id])
        for q in self._subs.get(job_id, []):
            q.put_nowait(snap)

    def _progress_cb(self, job_id: str) -> Progress:
        def cb(stage: str, fraction: float) -> None:
            def apply():
                st = self._jobs[job_id]
                st.stage, st.fraction, st.status = stage, fraction, "running"
                self._publish(job_id)
            assert self._loop is not None
            self._loop.call_soon_threadsafe(apply)
        return cb

    async def _run(self) -> None:
        while True:
            job_id, fn = await self._queue.get()
            st = self._jobs[job_id]
            st.status = "running"
            self._publish(job_id)
            try:
                await asyncio.get_running_loop().run_in_executor(self._pool, fn, self._progress_cb(job_id))
                st.status, st.stage, st.fraction = "done", "done", 1.0
            except Exception as e:  # noqa: BLE001
                st.status, st.stage, st.error = "error", "error", str(e)
            self._publish(job_id)

    async def events(self, job_id: str) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue()
        self._subs[job_id].append(q)
        try:
            yield asdict(self._jobs[job_id])
            if self._jobs[job_id].status in ("done", "error"):
                return
            while True:
                snap = await q.get()
                yield snap
                if snap["status"] in ("done", "error"):
                    return
        finally:
            self._subs[job_id].remove(q)
```

- [ ] **Step 5: Implement `pipeline.py`**

```python
from __future__ import annotations
from pathlib import Path
from sqlalchemy import Engine
from sqlmodel import Session, select
from shadow.deps import Deps
from shadow.ingest import audio
from shadow.ingest.align import align_in_window, sentence_bounds
from shadow.ingest.enrich import make_clips, translate_all, words_for
from shadow.ingest.rectify import RectSentenceOut, rectify_transcript
from shadow.ingest.text import parse_subtitles
from shadow.ingest.transcript import Transcript, transcript_from_cues
from shadow.jobs import Progress
from shadow.store.models import Lesson, Segment


class NoSpeechError(RuntimeError):
    pass


def _set_status(engine: Engine, lesson_id: int, status: str, error: str | None = None, **fields) -> None:
    with Session(engine) as db:
        lesson = db.get(Lesson, lesson_id)
        lesson.status, lesson.error = status, error
        for k, v in fields.items():
            setattr(lesson, k, v)
        db.add(lesson); db.commit()


def build_segments(deps: Deps, engine: Engine, lesson_id: int, source_wav: Path, tr: Transcript,
                   sentences: list[RectSentenceOut], progress: Progress, anki_note_ids: list[int] | None = None,
                   idx_offset: int = 0) -> None:
    """Align, enrich and clip `sentences`; writes Segment rows numbered from `idx_offset`.
    Shared by upload (offset 0) and Anki ingest (offset = existing segment count)."""
    wav, sr = audio.read_wav(source_wav)
    total = len(wav) / sr
    pad = deps.settings.segmentation.pad_ms / 1000
    progress("align", 0.0)
    aligned = []
    for i, s in enumerate(sentences):
        coarse_start = tr.chars[s.char_from].start
        coarse_end = tr.chars[s.char_to].end
        spans = align_in_window(deps.aligner, wav, sr, s.text, max(0.0, coarse_start - 1.0), min(total, coarse_end + 1.0))
        aligned.append(spans)
        progress("align", (i + 1) / len(sentences))
    bounds = []
    for i, spans in enumerate(aligned):
        prev_end = bounds[i - 1][1] if i else 0.0
        next_start = aligned[i + 1][0].start if i + 1 < len(aligned) and aligned[i + 1] else total
        bounds.append(sentence_bounds(spans, pad, prev_end, next_start, total) if spans else (prev_end, prev_end))
    progress("enrich", 0.0)
    translations = [None] * len(sentences)
    if deps.llm is not None and deps.settings.llm.translate:
        translations = translate_all(deps.llm, [s.text for s in sentences])
    with Session(engine) as db:
        for i, s in enumerate(sentences):
            start, end = bounds[i]
            idx = idx_offset + i
            clip_wav, clip_opus = make_clips(deps.files, lesson_id, idx, source_wav, start, end)
            db.add(Segment(
                lesson_id=lesson_id, idx=idx, start_s=start, end_s=end,
                char_from=s.char_from, char_to=s.char_to, text=s.text,
                translation=translations[i] or None, words_json=words_for(s.text),
                ref_alignment_json=[{"ch": sp.ch, "start": round(sp.start, 3), "end": round(sp.end, 3), "conf": round(sp.conf, 3)} for sp in aligned[i]],
                anki_note_id=anki_note_ids[i] if anki_note_ids else None,
                clip_wav_path=str(clip_wav), clip_opus_path=str(clip_opus),
            ))
            progress("enrich", (i + 1) / len(sentences))
        db.commit()


def ingest_upload(deps: Deps, engine: Engine, lesson_id: int, media_path: Path,
                  subtitle: tuple[str, str] | None, progress: Progress) -> None:
    try:
        _set_status(engine, lesson_id, "processing")
        progress("normalise", 0.0)
        source_wav = deps.files.source_wav(lesson_id)
        audio.normalise(media_path, source_wav)
        duration = audio.duration_s(source_wav)
        progress("normalise", 1.0)

        progress("transcribe", 0.0)
        if subtitle is not None:
            cues = [c for c in parse_subtitles(subtitle[1], subtitle[0]) if c.start >= 0]
            tr = transcript_from_cues(cues)
        else:
            tr = deps.asr.transcribe(source_wav)
        if not tr.chars:
            raise NoSpeechError("no speech found in the recording")
        progress("transcribe", 1.0)

        progress("rectify", 0.0)
        sentences = rectify_transcript(tr, deps.llm, enabled=deps.settings.llm.rectify and subtitle is None)
        progress("rectify", 1.0)

        build_segments(deps, engine, lesson_id, source_wav, tr, sentences, progress)
        _set_status(engine, lesson_id, "ready", duration_s=duration, transcript_json=tr.to_json())
        progress("done", 1.0)
    except Exception as e:  # noqa: BLE001
        _set_status(engine, lesson_id, "error", error=str(e))
        raise
```

- [ ] **Step 6: Implement `schemas.py`, `api/jobs.py`, `api/lessons.py` (create only), wire `main.py`**

`backend/shadow/schemas.py`:
```python
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel


class JobOut(BaseModel):
    id: str
    stage: str
    fraction: float
    status: str
    error: str | None
    lesson_id: int | None


class SegmentOut(BaseModel):
    id: int
    lesson_id: int
    idx: int
    start_s: float
    end_s: float
    text: str
    translation: str | None
    words_json: list[dict[str, Any]] | None
    ref_alignment_json: list[dict[str, Any]] | None
    difficulty_flag: bool
    anki_note_id: int | None
    last_score: float | None = None
    best_score: float | None = None
    attempts: int = 0


class LessonOut(BaseModel):
    id: int
    title: str
    speaker: str
    source_type: str
    source_ref: str
    duration_s: float
    created_at: datetime
    status: str
    error: str | None
    segment_count: int = 0
    practised_count: int = 0
    mean_last_score: float | None = None


class LessonDetail(LessonOut):
    segments: list[SegmentOut]


class AttemptOut(BaseModel):
    id: int
    segment_id: int
    session_id: int | None
    created_at: datetime
    mode: str
    duration_s: float
    score_json: dict[str, Any] | None


class SessionOut(BaseModel):
    id: int
    lesson_id: int
    mode: str
    started_at: datetime
    ended_at: datetime | None
    attempts_count: int
```

`backend/shadow/api/jobs.py`:
```python
import json
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from shadow.schemas import JobOut

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, request: Request):
    st = request.app.state.jobs.get(job_id)
    if st is None:
        raise HTTPException(404, "job not found")
    return JobOut(**st.__dict__)


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    jobs = request.app.state.jobs
    if jobs.get(job_id) is None:
        raise HTTPException(404, "job not found")

    async def gen():
        async for snap in jobs.events(job_id):
            yield {"event": "progress", "data": json.dumps(snap)}
    return EventSourceResponse(gen())
```

`backend/shadow/api/lessons.py` (create endpoint; Task 13 adds the rest):
```python
from __future__ import annotations
import shutil
import uuid
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlmodel import Session
from shadow.ingest.pipeline import ingest_upload
from shadow.store.db import get_session
from shadow.store.models import Lesson

router = APIRouter()


@router.post("/lessons", status_code=202)
async def create_lesson(request: Request, file: UploadFile = File(...), subtitles: UploadFile | None = File(None),
                        title: str = Form(""), speaker: str = Form(""), db: Session = Depends(get_session)):
    deps, engine, jobs = request.app.state.deps, request.app.state.engine, request.app.state.jobs
    lesson = Lesson(title=title or file.filename or "Untitled", speaker=speaker, source_type="upload",
                    source_ref=file.filename or "")
    db.add(lesson); db.commit(); db.refresh(lesson)
    upload_dir = deps.files.lesson_dir(lesson.id) / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    media_path = upload_dir / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    with media_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    sub = None
    if subtitles is not None and subtitles.filename:
        sub = (subtitles.filename, (await subtitles.read()).decode("utf-8", errors="replace"))
    lesson_id = lesson.id
    job_id = jobs.submit(lambda progress: ingest_upload(deps, engine, lesson_id, media_path, sub, progress), lesson_id)
    return {"job_id": job_id, "lesson_id": lesson_id}
```

`backend/shadow/main.py` (replace):
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shadow.config import Settings, load_settings
from shadow.deps import Deps, build_deps
from shadow.jobs import JobManager
from shadow.store.db import make_engine, init_db
from shadow.api import health, jobs, lessons


def create_app(settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.jobs.start()
        yield
        await app.state.jobs.stop()

    app = FastAPI(title="shadow", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = make_engine(settings.data_dir)
    init_db(app.state.engine)
    app.state.deps = deps or build_deps(settings)
    app.state.files = app.state.deps.files
    app.state.jobs = JobManager()
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])
    for r in (health.router, jobs.router, lessons.router):
        app.include_router(r)
    return app


app = create_app()
```

Note: `app = create_app()` at import time builds real deps lazily (no model loads until first use), so importing the module in tests is harmless.

- [ ] **Step 7: Run tests**

Run: `cd backend && uv run pytest -q`
Expected: all pass (previous 27 + 5 new).

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: job runner with SSE, upload ingest pipeline, POST /lessons"
```

---

### Task 12: Anki import endpoint

**Files:**
- Create: `backend/shadow/ingest/anki.py`, `backend/shadow/api/anki.py`, `backend/tests/test_anki_import.py`
- Modify: `backend/shadow/main.py` (include router)

**Interfaces:**
- `ingest/anki.py`: `class AnkiNoteIn(BaseModel): note_id: int, text: str, translation: str | None, source: str | None, url: str | None, audio_b64: str, filename: str`; `parse_source(source: str | None) -> tuple[str, float | None]` (video name, timestamp seconds) handling asbplayer's `"<name> <mm:ss.mmm>"` / `"<name>_<timestamp>"` forms and plain names; `group_by_video(notes) -> dict[str, list[AnkiNoteIn]]`; `ingest_anki_group(deps, engine, lesson_id, notes, progress)` — decodes each clip, normalises, concatenates into `source.wav` with 0.5 s gaps, builds a `Transcript` with one segment per note, calls `build_segments` with `anki_note_ids`.
- API: `POST /lessons/anki` body `{"query_name": str, "notes": [AnkiNoteIn...]}` → `{"jobs": [{"job_id","lesson_id","title"}...]}`; one lesson per video; re-import appends only notes whose `note_id` is not yet a `Segment.anki_note_id` of that lesson (lesson matched by `source_type="anki"` and `source_ref == f"{query_name}::{video}"`).

- [ ] **Step 1: Failing tests**

`backend/tests/test_anki_import.py`:
```python
import base64
from sqlmodel import Session, select
from shadow.ingest.anki import parse_source, group_by_video, AnkiNoteIn
from shadow.store.models import Lesson, Segment
from tests.helpers import make_tone_wav
from tests.conftest import wait_job


def test_parse_source_forms():
    assert parse_source("春天的茶.mp4 00:12:03.450") == ("春天的茶.mp4", 723.45)
    assert parse_source("春天的茶_12345") == ("春天的茶", None)
    assert parse_source("春天的茶") == ("春天的茶", None)
    assert parse_source(None) == ("", None)


def _note(i, text, source="春天的茶.mp4 00:00:0%d.000" % 1, audio_b64="", translation=None):
    return AnkiNoteIn(note_id=i, text=text, translation=translation, source=source, url=None,
                      audio_b64=audio_b64, filename=f"{i}.wav")


def test_group_by_video():
    g = group_by_video([_note(1, "a", "v1.mp4 00:00:01.000"), _note(2, "b", "v2.mp4 00:00:01.000"), _note(3, "c", None)])
    assert set(g) == {"v1.mp4", "v2.mp4", ""}


def test_import_creates_one_lesson_per_video_and_is_idempotent(client, tmp_path):
    b64 = base64.b64encode(make_tone_wav(tmp_path / "c.wav", 1.5).read_bytes()).decode()
    notes = [
        {"note_id": 1, "text": "<div>你好，<b>世界</b>。</div>", "translation": "Hello", "source": "v1.mp4 00:00:01.000", "url": None, "audio_b64": b64, "filename": "1.wav"},
        {"note_id": 2, "text": "再见。[sound:x.mp3]", "translation": None, "source": "v1.mp4 00:00:05.000", "url": None, "audio_b64": b64, "filename": "2.wav"},
        {"note_id": 3, "text": "欢迎回来。", "translation": None, "source": "v2.mp4 00:00:02.000", "url": None, "audio_b64": b64, "filename": "3.wav"},
    ]
    r = client.post("/lessons/anki", json={"query_name": "deck:Mining", "notes": notes})
    assert r.status_code == 202
    jobs = r.json()["jobs"]
    assert len(jobs) == 2
    for j in jobs:
        assert wait_job(client, j["job_id"])["status"] == "done"
    engine = client.app.state.engine
    with Session(engine) as db:
        lessons = db.exec(select(Lesson).where(Lesson.source_type == "anki")).all()
        assert sorted(l.title for l in lessons) == ["v1.mp4", "v2.mp4"]
        v1 = next(l for l in lessons if l.title == "v1.mp4")
        segs = db.exec(select(Segment).where(Segment.lesson_id == v1.id).order_by(Segment.idx)).all()
        assert [s.text for s in segs] == ["你好，世界。", "再见。"]
        assert segs[0].translation == "Hello" and segs[0].anki_note_id == 1
        assert segs[1].start_s > segs[0].end_s
    # re-import with one new note → only one job, one new segment
    r2 = client.post("/lessons/anki", json={"query_name": "deck:Mining", "notes": notes[:1] + [
        {"note_id": 4, "text": "新的句子。", "translation": None, "source": "v1.mp4 00:00:09.000", "url": None, "audio_b64": b64, "filename": "4.wav"}]})
    jobs2 = r2.json()["jobs"]
    assert len(jobs2) == 1
    assert wait_job(client, jobs2[0]["job_id"])["status"] == "done"
    with Session(engine) as db:
        segs = db.exec(select(Segment).where(Segment.lesson_id == v1.id).order_by(Segment.idx)).all()
        assert [s.anki_note_id for s in segs] == [1, 2, 4]
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_anki_import.py -q`
Expected: FAIL

- [ ] **Step 3: Implement `ingest/anki.py`**

```python
from __future__ import annotations
import base64
import re
from collections import defaultdict
from pathlib import Path
import numpy as np
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session, select
from shadow.deps import Deps
from shadow.ingest import audio
from shadow.ingest.pipeline import build_segments, _set_status
from shadow.ingest.rectify import RectSentenceOut
from shadow.ingest.text import strip_html, to_simplified
from shadow.ingest.transcript import Transcript, TimedChar
from shadow.jobs import Progress
from shadow.store.models import Segment

GAP_S = 0.5
_SOUND = re.compile(r"\[sound:[^\]]*\]")
_TS = re.compile(r"\s+(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})$")
_SUFFIX = re.compile(r"_\d+$")


class AnkiNoteIn(BaseModel):
    note_id: int
    text: str
    translation: str | None = None
    source: str | None = None
    url: str | None = None
    audio_b64: str
    filename: str


def parse_source(source: str | None) -> tuple[str, float | None]:
    if not source:
        return "", None
    s = strip_html(source)
    m = _TS.search(s)
    if m:
        h, mi, se, ms = (int(x) for x in m.groups())
        return s[: m.start()].strip(), h * 3600 + mi * 60 + se + ms / 1000
    return _SUFFIX.sub("", s).strip(), None


def clean_sentence(text: str) -> str:
    return to_simplified(strip_html(_SOUND.sub("", text))).strip()


def group_by_video(notes: list[AnkiNoteIn]) -> dict[str, list[AnkiNoteIn]]:
    groups: dict[str, list[AnkiNoteIn]] = defaultdict(list)
    for n in notes:
        groups[parse_source(n.source)[0]].append(n)
    for g in groups.values():
        g.sort(key=lambda n: (parse_source(n.source)[1] or 0.0, n.note_id))
    return dict(groups)


def existing_note_ids(engine: Engine, lesson_id: int) -> set[int]:
    with Session(engine) as db:
        return {s.anki_note_id for s in db.exec(select(Segment).where(Segment.lesson_id == lesson_id)).all() if s.anki_note_id}


def ingest_anki_group(deps: Deps, engine: Engine, lesson_id: int, notes: list[AnkiNoteIn], progress: Progress) -> None:
    try:
        _set_status(engine, lesson_id, "processing")
        progress("normalise", 0.0)
        with Session(engine) as db:
            existing = db.exec(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.idx)).all()
            start_idx = len(existing)
            cursor = max((s.end_s for s in existing), default=0.0) + GAP_S if existing else 0.0
        source_wav = deps.files.source_wav(lesson_id)
        existing_audio, _ = audio.read_wav(source_wav) if source_wav.exists() else (np.zeros(0, dtype="float32"), audio.SR)
        pieces = [existing_audio, np.zeros(int(GAP_S * audio.SR), dtype="float32")] if len(existing_audio) else []
        tr = Transcript()
        sentences: list[RectSentenceOut] = []
        note_ids: list[int] = []
        tmp = deps.files.lesson_dir(lesson_id) / "anki_tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        for i, n in enumerate(notes):
            raw, norm = tmp / f"{n.note_id}_{n.filename}", tmp / f"{n.note_id}.wav"
            raw.write_bytes(base64.b64decode(n.audio_b64))
            audio.normalise(raw, norm)
            clip, _ = audio.read_wav(norm)
            text = clean_sentence(n.text)
            if not text:
                continue
            dur = len(clip) / audio.SR
            a = len(tr.chars)
            tr.chars.extend([TimedChar(c, cursor, cursor + dur) for c in text])
            tr.segments.append((a, len(tr.chars) - 1))
            sentences.append(RectSentenceOut(a, len(tr.chars) - 1, text))
            note_ids.append(n.note_id)
            pieces.append(clip); pieces.append(np.zeros(int(GAP_S * audio.SR), dtype="float32"))
            cursor += dur + GAP_S
            progress("normalise", (i + 1) / len(notes))
        if not sentences:
            raise RuntimeError("no usable notes")
        audio.write_wav(source_wav, np.concatenate(pieces))
        build_segments(deps, engine, lesson_id, source_wav, tr, sentences, progress,
                       anki_note_ids=note_ids, idx_offset=start_idx)
        # translations provided by notes override the LLM
        with Session(engine) as db:
            by_note = {n.note_id: n for n in notes}
            for s in db.exec(select(Segment).where(Segment.lesson_id == lesson_id)).all():
                n = by_note.get(s.anki_note_id)
                if n and n.translation:
                    s.translation = strip_html(n.translation); db.add(s)
            db.commit()
        _set_status(engine, lesson_id, "ready", duration_s=cursor, transcript_json=tr.to_json())
        progress("done", 1.0)
    except Exception as e:  # noqa: BLE001
        _set_status(engine, lesson_id, "error", error=str(e))
        raise
```

Appended notes are numbered from `start_idx` via `build_segments(..., idx_offset=start_idx)`, so clip paths never collide with existing ones.

- [ ] **Step 4: Implement `api/anki.py` and include router**

```python
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session, select
from shadow.ingest.anki import AnkiNoteIn, group_by_video, existing_note_ids, ingest_anki_group
from shadow.store.db import get_session
from shadow.store.models import Lesson

router = APIRouter()


class AnkiImportIn(BaseModel):
    query_name: str
    notes: list[AnkiNoteIn]


@router.post("/lessons/anki", status_code=202)
def import_anki(body: AnkiImportIn, request: Request, db: Session = Depends(get_session)):
    deps, engine, jobs = request.app.state.deps, request.app.state.engine, request.app.state.jobs
    out = []
    for video, notes in group_by_video(body.notes).items():
        ref = f"{body.query_name}::{video}"
        lesson = db.exec(select(Lesson).where(Lesson.source_type == "anki", Lesson.source_ref == ref)).first()
        if lesson is None:
            lesson = Lesson(title=video or body.query_name, speaker=video or "Anki", source_type="anki", source_ref=ref)
            db.add(lesson); db.commit(); db.refresh(lesson)
        new_notes = [n for n in notes if n.note_id not in existing_note_ids(engine, lesson.id)]
        if not new_notes:
            continue
        lid = lesson.id
        job_id = jobs.submit(lambda p, lid=lid, ns=new_notes: ingest_anki_group(deps, engine, lid, ns, p), lid)
        out.append({"job_id": job_id, "lesson_id": lid, "title": lesson.title})
    return {"jobs": out}
```

In `main.py` add `from shadow.api import anki` and include `anki.router` **before** `lessons.router` is irrelevant for path matching here, but include it in the tuple.

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: Anki import, one lesson per source video, idempotent re-import"
```

---

### Task 13: Lessons and segments API (read, delete, patch, audio, resplit, merge)

**Files:**
- Create: `backend/shadow/api/segments.py`, `backend/shadow/ingest/reenrich.py`, `backend/tests/test_lessons_api.py`, `backend/tests/test_segments_api.py`
- Modify: `backend/shadow/api/lessons.py`, `backend/shadow/main.py`

**Interfaces:**
- `GET /lessons` → `list[LessonOut]` (with `segment_count`, `practised_count`, `mean_last_score`); `GET /lessons/{id}` → `LessonDetail`; `DELETE /lessons/{id}` (rows + files); `PATCH /lessons/{id}` `{title?, speaker?}`.
- `GET /segments/{id}/audio?fmt=opus|wav|mp3` (mp3 rendered on first request); `PATCH /segments/{id}` `{difficulty_flag?, text?}` — text change re-runs align + words + clips via `reenrich.reenrich_segment(deps, engine, segment_id)`; identical text is a no-op; `POST /segments/{id}/resplit {at_char_index}` → two segments, split time from `ref_alignment_json`; `POST /segments/{id}/merge-next`.
- `reenrich.py`: `reenrich_segment(deps, engine, segment_id) -> None`; `renumber(engine, lesson_id)` keeps `idx` dense and clip paths consistent (clips renamed by renumber).

- [ ] **Step 1: Failing tests**

`backend/tests/test_lessons_api.py`:
```python
from tests.helpers import make_tone_wav
from tests.conftest import wait_job


def _upload(client, tmp_path, title="L"):
    wav = make_tone_wav(tmp_path / f"{title}.wav", 8.0)
    with open(wav, "rb") as f:
        r = client.post("/lessons", files={"file": (f"{title}.wav", f, "audio/wav")}, data={"title": title, "speaker": "S"})
    wait_job(client, r.json()["job_id"])
    return r.json()["lesson_id"]


def test_list_get_patch_delete(client, tmp_path):
    lid = _upload(client, tmp_path)
    lst = client.get("/lessons").json()
    assert lst[0]["id"] == lid and lst[0]["segment_count"] == 3 and lst[0]["status"] == "ready"
    detail = client.get(f"/lessons/{lid}").json()
    assert len(detail["segments"]) == 3 and detail["segments"][0]["words_json"]
    assert client.patch(f"/lessons/{lid}", json={"speaker": "李子柒"}).json()["speaker"] == "李子柒"
    assert client.delete(f"/lessons/{lid}").status_code == 204
    assert client.get(f"/lessons/{lid}").status_code == 404
    assert not client.app.state.files.lesson_dir(lid).exists()
```

`backend/tests/test_segments_api.py`:
```python
from tests.test_lessons_api import _upload


def _segments(client, lid):
    return client.get(f"/lessons/{lid}").json()["segments"]


def test_audio_formats(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = _segments(client, lid)[0]["id"]
    for fmt, ctype in (("wav", "audio/wav"), ("opus", "audio/ogg"), ("mp3", "audio/mpeg")):
        r = client.get(f"/segments/{sid}/audio", params={"fmt": fmt})
        assert r.status_code == 200 and r.headers["content-type"].startswith(ctype), fmt


def test_patch_flag_and_text(client, tmp_path):
    lid = _upload(client, tmp_path)
    seg = _segments(client, lid)[1]
    assert client.patch(f"/segments/{seg['id']}", json={"difficulty_flag": True}).json()["difficulty_flag"] is True
    before = client.app.state.files.clip_wav(lid, 1).stat().st_mtime_ns
    same = client.patch(f"/segments/{seg['id']}", json={"text": seg["text"]}).json()
    assert client.app.state.files.clip_wav(lid, 1).stat().st_mtime_ns == before      # no-op
    changed = client.patch(f"/segments/{seg['id']}", json={"text": "其实办法有很多。"}).json()
    assert changed["text"] == "其实办法有很多。" and changed["words_json"][1]["word"] == "办法"
    assert len(changed["ref_alignment_json"]) == 7


def test_resplit_and_merge(client, tmp_path):
    lid = _upload(client, tmp_path)
    segs = _segments(client, lid)
    r = client.post(f"/segments/{segs[0]['id']}/resplit", json={"at_char_index": 7})
    assert r.status_code == 200
    segs2 = _segments(client, lid)
    assert len(segs2) == 4 and [s["idx"] for s in segs2] == [0, 1, 2, 3]
    assert segs2[0]["text"] == "我今天想跟你们" and segs2[1]["text"] == "聊一聊学中文的方法。"
    assert abs(segs2[0]["end_s"] - segs2[1]["start_s"]) < 0.3
    assert client.app.state.files.clip_wav(lid, 3).exists()
    r = client.post(f"/segments/{segs2[0]['id']}/merge-next")
    segs3 = _segments(client, lid)
    assert len(segs3) == 3 and segs3[0]["text"] == "我今天想跟你们聊一聊学中文的方法。"
    assert client.post(f"/segments/{segs3[-1]['id']}/merge-next").status_code == 409
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_lessons_api.py tests/test_segments_api.py -q`
Expected: FAIL

- [ ] **Step 3: Implement `reenrich.py`**

```python
from __future__ import annotations
from pathlib import Path
from sqlalchemy import Engine
from sqlmodel import Session, select
from shadow.deps import Deps
from shadow.ingest import audio
from shadow.ingest.align import align_in_window, sentence_bounds
from shadow.ingest.enrich import make_clips, words_for
from shadow.store.models import Lesson, Segment


def _neighbours(db: Session, seg: Segment) -> tuple[float, float]:
    prev = db.exec(select(Segment).where(Segment.lesson_id == seg.lesson_id, Segment.idx == seg.idx - 1)).first()
    nxt = db.exec(select(Segment).where(Segment.lesson_id == seg.lesson_id, Segment.idx == seg.idx + 1)).first()
    lesson = db.get(Lesson, seg.lesson_id)
    return (prev.end_s if prev else 0.0, nxt.start_s if nxt else lesson.duration_s)


def reenrich_segment(deps: Deps, engine: Engine, segment_id: int, window: tuple[float, float] | None = None) -> None:
    """Re-align `seg.text` inside `window` (defaults to the segment's current span ± 1 s), rebuild words and clips."""
    with Session(engine) as db:
        seg = db.get(Segment, segment_id)
        source = deps.files.source_wav(seg.lesson_id)
        wav, sr = audio.read_wav(source)
        total = len(wav) / sr
        w0, w1 = window or (max(0.0, seg.start_s - 1.0), min(total, seg.end_s + 1.0))
        spans = align_in_window(deps.aligner, wav, sr, seg.text, w0, w1)
        prev_end, next_start = _neighbours(db, seg)
        pad = deps.settings.segmentation.pad_ms / 1000
        if spans:
            seg.start_s, seg.end_s = sentence_bounds(spans, pad, prev_end, next_start, total)
        seg.ref_alignment_json = [{"ch": s.ch, "start": round(s.start, 3), "end": round(s.end, 3), "conf": round(s.conf, 3)} for s in spans]
        seg.words_json = words_for(seg.text)
        seg.translation = None
        wav_p, opus_p = make_clips(deps.files, seg.lesson_id, seg.idx, source, seg.start_s, seg.end_s)
        seg.clip_wav_path, seg.clip_opus_path = str(wav_p), str(opus_p)
        mp3 = deps.files.clip_mp3(seg.lesson_id, seg.idx)
        if mp3.exists():
            mp3.unlink()
        db.add(seg); db.commit()


def renumber(deps: Deps, engine: Engine, lesson_id: int) -> None:
    """Make idx dense (0..n-1) in time order and move clip files to match."""
    with Session(engine) as db:
        segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.start_s, Segment.idx)).all()
        moves: list[tuple[Path, Path]] = []
        for new_idx, seg in enumerate(segs):
            if seg.idx != new_idx:
                for old, new in ((seg.clip_wav_path, deps.files.clip_wav(lesson_id, new_idx)),
                                 (seg.clip_opus_path, deps.files.clip_opus(lesson_id, new_idx))):
                    if old:
                        tmp = Path(str(new) + ".tmp")
                        Path(old).rename(tmp); moves.append((tmp, new))
                seg.idx = new_idx
                seg.clip_wav_path = str(deps.files.clip_wav(lesson_id, new_idx))
                seg.clip_opus_path = str(deps.files.clip_opus(lesson_id, new_idx))
                db.add(seg)
        for tmp, new in moves:
            tmp.rename(new)
        db.commit()
```

- [ ] **Step 4: Implement the rest of `api/lessons.py`**

Append:
```python
import shutil
from fastapi import HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlalchemy import func
from shadow.schemas import LessonOut, LessonDetail, SegmentOut
from shadow.store.models import Segment, Attempt


def _segment_out(db: Session, seg: Segment) -> SegmentOut:
    atts = db.exec(select(Attempt).where(Attempt.segment_id == seg.id).order_by(Attempt.created_at)).all()
    scores = [a.score_json["overall"] for a in atts if a.score_json and "overall" in a.score_json]
    return SegmentOut(**seg.model_dump(), last_score=scores[-1] if scores else None,
                      best_score=max(scores) if scores else None, attempts=len(atts))


def _lesson_out(db: Session, lesson: Lesson) -> LessonOut:
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson.id)).all()
    outs = [_segment_out(db, s) for s in segs]
    last = [o.last_score for o in outs if o.last_score is not None]
    return LessonOut(**lesson.model_dump(exclude={"meta_json", "transcript_json"}), segment_count=len(segs),
                     practised_count=sum(1 for o in outs if o.attempts), mean_last_score=sum(last) / len(last) if last else None)


@router.get("/lessons", response_model=list[LessonOut])
def list_lessons(db: Session = Depends(get_session)):
    return [_lesson_out(db, l) for l in db.exec(select(Lesson).order_by(Lesson.created_at.desc())).all()]


@router.get("/lessons/{lesson_id}", response_model=LessonDetail)
def get_lesson(lesson_id: int, db: Session = Depends(get_session)):
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(404, "lesson not found")
    base = _lesson_out(db, lesson)
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.idx)).all()
    return LessonDetail(**base.model_dump(), segments=[_segment_out(db, s) for s in segs])


class LessonPatch(BaseModel):
    title: str | None = None
    speaker: str | None = None


@router.patch("/lessons/{lesson_id}", response_model=LessonOut)
def patch_lesson(lesson_id: int, body: LessonPatch, db: Session = Depends(get_session)):
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(404, "lesson not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(lesson, k, v)
    db.add(lesson); db.commit(); db.refresh(lesson)
    return _lesson_out(db, lesson)


@router.delete("/lessons/{lesson_id}", status_code=204)
def delete_lesson(lesson_id: int, request: Request, db: Session = Depends(get_session)):
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(404, "lesson not found")
    seg_ids = [s.id for s in db.exec(select(Segment).where(Segment.lesson_id == lesson_id)).all()]
    for a in db.exec(select(Attempt).where(Attempt.segment_id.in_(seg_ids))).all() if seg_ids else []:
        db.delete(a)
    for s in db.exec(select(Segment).where(Segment.lesson_id == lesson_id)).all():
        db.delete(s)
    db.delete(lesson); db.commit()
    shutil.rmtree(request.app.state.files.lesson_dir(lesson_id), ignore_errors=True)
```

(Attempt audio files are left in `data/attempts/`; `SyllableScore` and `PracticeSession` rows for the lesson are deleted in Task 14 where those tables gain writes.)

- [ ] **Step 5: Implement `api/segments.py`**

```python
from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select
from shadow.api.lessons import _segment_out
from shadow.ingest import audio
from shadow.ingest.reenrich import reenrich_segment, renumber
from shadow.schemas import SegmentOut
from shadow.store.db import get_session
from shadow.store.models import Segment

router = APIRouter()
MEDIA = {"wav": "audio/wav", "opus": "audio/ogg", "mp3": "audio/mpeg"}


def _get(db: Session, segment_id: int) -> Segment:
    seg = db.get(Segment, segment_id)
    if seg is None:
        raise HTTPException(404, "segment not found")
    return seg


@router.get("/segments/{segment_id}/audio")
def segment_audio(segment_id: int, request: Request, fmt: str = "opus", db: Session = Depends(get_session)):
    seg = _get(db, segment_id)
    files = request.app.state.files
    if fmt not in MEDIA:
        raise HTTPException(400, "fmt must be opus|wav|mp3")
    path = {"wav": Path(seg.clip_wav_path), "opus": Path(seg.clip_opus_path), "mp3": files.clip_mp3(seg.lesson_id, seg.idx)}[fmt]
    if fmt == "mp3" and not path.exists():
        audio.encode_mp3(Path(seg.clip_wav_path), path)
    return FileResponse(path, media_type=MEDIA[fmt])


class SegmentPatch(BaseModel):
    difficulty_flag: bool | None = None
    text: str | None = None


@router.patch("/segments/{segment_id}", response_model=SegmentOut)
def patch_segment(segment_id: int, body: SegmentPatch, request: Request, db: Session = Depends(get_session)):
    seg = _get(db, segment_id)
    if body.difficulty_flag is not None:
        seg.difficulty_flag = body.difficulty_flag
    text_changed = body.text is not None and body.text.strip() and body.text.strip() != seg.text
    if text_changed:
        from shadow.ingest.text import to_simplified
        seg.text = to_simplified(body.text.strip())
    db.add(seg); db.commit()
    if text_changed:
        reenrich_segment(request.app.state.deps, request.app.state.engine, segment_id)
    db.expire_all()
    return _segment_out(db, _get(db, segment_id))


class ResplitIn(BaseModel):
    at_char_index: int


@router.post("/segments/{segment_id}/resplit", response_model=list[SegmentOut])
def resplit(segment_id: int, body: ResplitIn, request: Request, db: Session = Depends(get_session)):
    seg = _get(db, segment_id)
    k = body.at_char_index
    if not (0 < k < len(seg.text)):
        raise HTTPException(400, "at_char_index out of range")
    left, right = seg.text[:k], seg.text[k:]
    from shadow.ingest.text import strip_punct
    if not strip_punct(left) or not strip_punct(right):
        raise HTTPException(400, "both halves need speech characters")
    speech_before = len(strip_punct(left))
    al = seg.ref_alignment_json or []
    split_t = al[speech_before - 1]["end"] if len(al) >= speech_before else (seg.start_s + seg.end_s) / 2
    deps, engine = request.app.state.deps, request.app.state.engine
    old_start, old_end, lesson_id, idx = seg.start_s, seg.end_s, seg.lesson_id, seg.idx
    # shift later segments' idx by one to make room
    for later in db.exec(select(Segment).where(Segment.lesson_id == lesson_id, Segment.idx > idx)).all():
        later.idx += 1; db.add(later)
    seg.text, seg.end_s = left, split_t
    new = Segment(lesson_id=lesson_id, idx=idx + 1, start_s=split_t, end_s=old_end, text=right,
                  char_from=None, char_to=None)
    db.add(seg); db.add(new); db.commit(); db.refresh(new)
    left_id, right_id = seg.id, new.id
    reenrich_segment(deps, engine, left_id, window=(old_start, split_t + 0.3))
    reenrich_segment(deps, engine, right_id, window=(max(0.0, split_t - 0.3), old_end))
    renumber(deps, engine, lesson_id)
    db.expire_all()
    return [_segment_out(db, _get(db, left_id)), _segment_out(db, _get(db, right_id))]


@router.post("/segments/{segment_id}/merge-next", response_model=SegmentOut)
def merge_next(segment_id: int, request: Request, db: Session = Depends(get_session)):
    seg = _get(db, segment_id)
    nxt = db.exec(select(Segment).where(Segment.lesson_id == seg.lesson_id, Segment.idx == seg.idx + 1)).first()
    if nxt is None:
        raise HTTPException(409, "no next segment")
    deps, engine = request.app.state.deps, request.app.state.engine
    seg.text, seg.end_s = seg.text + nxt.text, nxt.end_s
    for p in (nxt.clip_wav_path, nxt.clip_opus_path):
        if p and Path(p).exists():
            Path(p).unlink()
    db.delete(nxt); db.add(seg); db.commit()
    sid, lid = seg.id, seg.lesson_id
    reenrich_segment(deps, engine, sid)
    renumber(deps, engine, lid)
    db.expire_all()
    return _segment_out(db, _get(db, sid))
```

Include `segments.router` in `main.py`.

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest -q`
Expected: all pass. If `test_resplit_and_merge` fails on the `end_s`/`start_s` closeness assertion, check that `reenrich_segment` for the left half receives a window ending just after `split_t` (the fake aligner spreads spans over the window, so the window must be tight).

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: lessons and segments API with edit, resplit, merge"
```

---

### Task 14: Attempts and sessions API

**Files:**
- Create: `backend/shadow/api/attempts.py`, `backend/shadow/api/sessions.py`, `backend/tests/test_attempts_api.py`
- Modify: `backend/shadow/main.py`, `backend/shadow/api/lessons.py` (delete cascades)

**Interfaces:**
- `POST /sessions {lesson_id, mode}` → `SessionOut`; `PATCH /sessions/{id} {ended: true}` sets `ended_at`.
- `POST /segments/{id}/attempts` multipart `audio` (WAV) + form `session_id` (optional), `mode` → `AttemptOut` with `score_json: null` in Phase 1; stores the WAV at `files.attempt_wav(id)` after normalising to 16 kHz mono; rejects non-decodable audio with 400; increments `session.attempts_count`.
- `GET /segments/{id}/attempts` → `list[AttemptOut]` newest first; `GET /attempts/{id}/audio` → WAV.
- Scoring hook: `shadow/scoring/__init__.py` exposes `score_attempt(deps, segment, attempt_wav) -> dict | None`, returning `None` in Phase 1. Phase 2 fills it in; the attempt endpoint already calls it and stores the result.

- [ ] **Step 1: Failing tests**

`backend/tests/test_attempts_api.py`:
```python
from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload


def test_session_and_attempt_flow(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    sess = client.post("/sessions", json={"lesson_id": lid, "mode": "echo"}).json()
    assert sess["attempts_count"] == 0
    wav = make_tone_wav(tmp_path / "att.wav", 1.2)
    with open(wav, "rb") as f:
        r = client.post(f"/segments/{sid}/attempts", files={"audio": ("att.wav", f, "audio/wav")},
                        data={"session_id": sess["id"], "mode": "echo"})
    assert r.status_code == 201
    att = r.json()
    assert att["score_json"] is None and abs(att["duration_s"] - 1.2) < 0.05
    assert client.get(f"/attempts/{att['id']}/audio").headers["content-type"].startswith("audio/wav")
    hist = client.get(f"/segments/{sid}/attempts").json()
    assert [a["id"] for a in hist] == [att["id"]]
    assert client.patch(f"/sessions/{sess['id']}", json={"ended": True}).json()["ended_at"] is not None
    assert client.get(f"/lessons/{lid}").json()["practised_count"] == 1


def test_bad_audio_rejected(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    r = client.post(f"/segments/{sid}/attempts", files={"audio": ("x.wav", b"not audio", "audio/wav")}, data={"mode": "echo"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_attempts_api.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

`backend/shadow/scoring/__init__.py`:
```python
from __future__ import annotations
from pathlib import Path
from shadow.deps import Deps
from shadow.store.models import Segment


def score_attempt(deps: Deps, segment: Segment, attempt_wav: Path) -> dict | None:
    """Phase 2 implements tone scoring here. Phase 1: no score."""
    return None
```

`backend/shadow/api/sessions.py`:
```python
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session
from shadow.schemas import SessionOut
from shadow.store.db import get_session
from shadow.store.models import PracticeSession, Lesson

router = APIRouter()


class SessionIn(BaseModel):
    lesson_id: int
    mode: str


class SessionPatch(BaseModel):
    ended: bool = False


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: SessionIn, db: Session = Depends(get_session)):
    if db.get(Lesson, body.lesson_id) is None:
        raise HTTPException(404, "lesson not found")
    if body.mode not in {"echo", "chorus", "flow", "guided"}:
        raise HTTPException(400, "bad mode")
    s = PracticeSession(lesson_id=body.lesson_id, mode=body.mode)
    db.add(s); db.commit(); db.refresh(s)
    return s


@router.patch("/sessions/{session_id}", response_model=SessionOut)
def patch_session(session_id: int, body: SessionPatch, db: Session = Depends(get_session)):
    s = db.get(PracticeSession, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    if body.ended:
        s.ended_at = datetime.now(timezone.utc)
    db.add(s); db.commit(); db.refresh(s)
    return s
```

`backend/shadow/api/attempts.py`:
```python
from __future__ import annotations
import subprocess
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from shadow.ingest import audio
from shadow.schemas import AttemptOut
from shadow.scoring import score_attempt
from shadow.store.db import get_session
from shadow.store.models import Attempt, PracticeSession, Segment

router = APIRouter()


@router.post("/segments/{segment_id}/attempts", response_model=AttemptOut, status_code=201)
async def create_attempt(segment_id: int, request: Request, audio_file: UploadFile = File(..., alias="audio"),
                         session_id: int | None = Form(None), mode: str = Form("echo"), db: Session = Depends(get_session)):
    seg = db.get(Segment, segment_id)
    if seg is None:
        raise HTTPException(404, "segment not found")
    files, deps = request.app.state.files, request.app.state.deps
    tmp_dir = files.data_dir / "attempts" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    raw = tmp_dir / f"{uuid.uuid4().hex}.bin"
    raw.write_bytes(await audio_file.read())
    att = Attempt(segment_id=segment_id, session_id=session_id, mode=mode, audio_path="", duration_s=0.0)
    db.add(att); db.commit(); db.refresh(att)
    dst = files.attempt_wav(att.id)
    try:
        audio.normalise(raw, dst)
        att.duration_s = audio.duration_s(dst)
    except subprocess.CalledProcessError:
        db.delete(att); db.commit()
        raise HTTPException(400, "audio could not be decoded")
    finally:
        raw.unlink(missing_ok=True)
    att.audio_path = str(dst)
    att.score_json = score_attempt(deps, seg, dst)
    if session_id is not None:
        s = db.get(PracticeSession, session_id)
        if s is not None:
            s.attempts_count += 1; db.add(s)
    db.add(att); db.commit(); db.refresh(att)
    return att


@router.get("/segments/{segment_id}/attempts", response_model=list[AttemptOut])
def list_attempts(segment_id: int, db: Session = Depends(get_session)):
    return db.exec(select(Attempt).where(Attempt.segment_id == segment_id).order_by(Attempt.created_at.desc())).all()


@router.get("/attempts/{attempt_id}/audio")
def attempt_audio(attempt_id: int, db: Session = Depends(get_session)):
    att = db.get(Attempt, attempt_id)
    if att is None:
        raise HTTPException(404, "attempt not found")
    return FileResponse(att.audio_path, media_type="audio/wav")
```

Include both routers in `main.py`. In `delete_lesson` (lessons.py) also delete `PracticeSession` rows for the lesson and `SyllableScore` rows whose `segment_id` is in `seg_ids`, and unlink each attempt's `audio_path`.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: sessions and attempts API with scoring hook"
```

---

### Task 15: Stats endpoints (Phase 1 shapes) and lesson stats

**Files:**
- Create: `backend/shadow/api/stats.py`, `backend/tests/test_stats_api.py`
- Modify: `backend/shadow/main.py`

**Interfaces:**
- `GET /lessons/{id}/stats` → `{"segments": [{segment_id, idx, last, best, attempts, trend: [floats]}], "sessions": [{session_id, started_at, mean}]}`.
- `GET /stats/activity?days=30` → `{"days": [{"date": "YYYY-MM-DD", "minutes": float, "attempts": int}]}` (minutes = sum of attempt durations plus session wall time where available; Phase 1 uses session wall time when `ended_at` set, else attempt durations).
- `GET /stats/sentences` → `{"regressed": [...], "by_last": [...]}` from `Attempt.score_json`; `GET /stats/syllables` and `GET /stats/tones` → from `SyllableScore` (empty lists in Phase 1, but the SQL is written now).

- [ ] **Step 1: Failing test**

`backend/tests/test_stats_api.py`:
```python
from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload


def test_stats_shapes(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    sess = client.post("/sessions", json={"lesson_id": lid, "mode": "echo"}).json()
    wav = make_tone_wav(tmp_path / "a.wav", 1.0)
    with open(wav, "rb") as f:
        client.post(f"/segments/{sid}/attempts", files={"audio": ("a.wav", f, "audio/wav")}, data={"session_id": sess["id"], "mode": "echo"})
    ls = client.get(f"/lessons/{lid}/stats").json()
    assert ls["segments"][0]["attempts"] == 1 and ls["segments"][0]["last"] is None
    act = client.get("/stats/activity", params={"days": 7}).json()
    assert len(act["days"]) == 7 and act["days"][-1]["attempts"] == 1 and act["days"][-1]["minutes"] > 0
    assert client.get("/stats/sentences").json() == {"regressed": [], "by_last": []}
    assert client.get("/stats/syllables").json() == {"syllables": []}
    assert client.get("/stats/tones").json() == {"tones": [], "pairs": []}
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_stats_api.py -q`
Expected: FAIL

- [ ] **Step 3: Implement `api/stats.py`**

```python
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select
from shadow.store.db import get_session
from shadow.store.models import Attempt, Lesson, PracticeSession, Segment, SyllableScore

router = APIRouter()


def _overall(a: Attempt) -> float | None:
    return a.score_json.get("overall") if a.score_json else None


@router.get("/lessons/{lesson_id}/stats")
def lesson_stats(lesson_id: int, db: Session = Depends(get_session)):
    if db.get(Lesson, lesson_id) is None:
        raise HTTPException(404, "lesson not found")
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.idx)).all()
    out_segments = []
    for s in segs:
        atts = db.exec(select(Attempt).where(Attempt.segment_id == s.id).order_by(Attempt.created_at)).all()
        scores = [x for x in (_overall(a) for a in atts) if x is not None]
        out_segments.append({"segment_id": s.id, "idx": s.idx, "last": scores[-1] if scores else None,
                             "best": max(scores) if scores else None, "attempts": len(atts), "trend": scores})
    sessions = []
    for ps in db.exec(select(PracticeSession).where(PracticeSession.lesson_id == lesson_id).order_by(PracticeSession.started_at)).all():
        scores = [x for x in (_overall(a) for a in db.exec(select(Attempt).where(Attempt.session_id == ps.id)).all()) if x is not None]
        sessions.append({"session_id": ps.id, "started_at": ps.started_at, "mean": sum(scores) / len(scores) if scores else None})
    return {"segments": out_segments, "sessions": sessions}


@router.get("/stats/activity")
def activity(days: int = 30, db: Session = Depends(get_session)):
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    per_day: dict[str, dict] = {str(start + timedelta(d)): {"date": str(start + timedelta(d)), "minutes": 0.0, "attempts": 0} for d in range(days)}
    for a in db.exec(select(Attempt).where(Attempt.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))).all():
        key = str(a.created_at.date())
        if key in per_day:
            per_day[key]["attempts"] += 1
            per_day[key]["minutes"] += a.duration_s / 60
    for ps in db.exec(select(PracticeSession).where(PracticeSession.ended_at.is_not(None))).all():
        key = str(ps.started_at.date())
        if key in per_day:
            wall = (ps.ended_at - ps.started_at).total_seconds() / 60
            per_day[key]["minutes"] = max(per_day[key]["minutes"], wall)
    return {"days": [per_day[k] for k in sorted(per_day)]}


@router.get("/stats/sentences")
def sentences(db: Session = Depends(get_session)):
    by_seg: dict[int, list[float]] = defaultdict(list)
    for a in db.exec(select(Attempt).order_by(Attempt.created_at)).all():
        o = _overall(a)
        if o is not None:
            by_seg[a.segment_id].append(o)
    rows = [{"segment_id": sid, "last": v[-1], "best": max(v), "attempts": len(v)} for sid, v in by_seg.items()]
    return {"regressed": sorted([r for r in rows if r["best"] - r["last"] >= 0.15], key=lambda r: r["best"] - r["last"], reverse=True),
            "by_last": sorted(rows, key=lambda r: r["last"])}


@router.get("/stats/syllables")
def syllables(db: Session = Depends(get_session)):
    q = (select(SyllableScore.pinyin_toneless, SyllableScore.tone, func.avg(SyllableScore.tone_score), func.count())
         .where(SyllableScore.tone_score.is_not(None)).group_by(SyllableScore.pinyin_toneless, SyllableScore.tone)
         .order_by(func.avg(SyllableScore.tone_score)))
    return {"syllables": [{"pinyin": p, "tone": t, "mean": m, "n": n} for p, t, m, n in db.exec(q).all()]}


@router.get("/stats/tones")
def tones(db: Session = Depends(get_session)):
    q1 = select(SyllableScore.tone, func.avg(SyllableScore.tone_score), func.count()).where(SyllableScore.tone_score.is_not(None)).group_by(SyllableScore.tone)
    q2 = (select(SyllableScore.prev_tone, SyllableScore.tone, func.avg(SyllableScore.tone_score), func.count())
          .where(SyllableScore.tone_score.is_not(None), SyllableScore.prev_tone.is_not(None)).group_by(SyllableScore.prev_tone, SyllableScore.tone))
    return {"tones": [{"tone": t, "mean": m, "n": n} for t, m, n in db.exec(q1).all()],
            "pairs": [{"prev_tone": p, "tone": t, "mean": m, "n": n} for p, t, m, n in db.exec(q2).all()]}
```

Include in `main.py`.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: stats endpoints at lesson, activity, sentence, syllable and tone grain"
```

---

### Task 16: Static SPA serving, dev run, docker-compose, real-model install notes

**Files:**
- Create: `docker-compose.yml`, `backend/Dockerfile`, `docs/running.md`
- Modify: `backend/shadow/main.py`

**Interfaces:**
- When `frontend/dist/index.html` exists, `create_app` mounts it at `/` (after API routers) with SPA fallback to `index.html` for unknown non-API paths.

- [ ] **Step 1: Failing test**

Append to `backend/tests/test_health.py`:
```python
def test_spa_fallback_when_dist_exists(data_dir, tmp_path, monkeypatch):
    dist = tmp_path / "dist"; dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>")
    monkeypatch.setenv("SHADOW_FRONTEND_DIST", str(dist))
    from shadow.deps import fake_deps
    from shadow.ingest.transcript import Transcript
    s = Settings(data_dir=data_dir)
    app = create_app(s, deps=fake_deps(s, Transcript()))
    c = TestClient(app)
    assert c.get("/").text == "<html>spa</html>"
    assert c.get("/practice/12").text == "<html>spa</html>"
    assert c.get("/health").status_code == 200
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_health.py -q`
Expected: FAIL (404 on `/`)

- [ ] **Step 3: Implement**

In `main.py`, after routers:
```python
import os
from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

    dist = Path(os.environ.get("SHADOW_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets") if (dist / "assets").exists() else None

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            candidate = dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
```

`backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/ ./
COPY config.toml /app/config.toml
COPY frontend/dist /app/frontend/dist
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "shadow.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`docker-compose.yml`:
```yaml
services:
  shadow:
    build: { context: ., dockerfile: backend/Dockerfile }
    ports: ["127.0.0.1:8000:8000"]
    volumes: ["./data:/app/data", "./config.toml:/app/config.toml:ro"]
    environment: ["ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"]
```

`docs/running.md`:
```markdown
# Running

## Dev (WSL2, GPU)
    cd backend && uv sync --extra dev --extra models      # pulls torch cu128 from the PyTorch index
    export ANTHROPIC_API_KEY=...                          # optional; without it rectification/translation are skipped
    cd .. && make dev

First ingest downloads Paraformer-zh (~1 GB, ModelScope) and Qwen3-ForcedAligner-0.6B (~2 GB, Hugging Face).
Verify the GPU is seen: `curl -s localhost:8000/health` → `"device": "cuda"`.

## CPU only
Set `[models] device = "cpu"` in config.toml; the aligner falls back to MMS_FA automatically.

## Tests
    make test                       # fakes only, no models
    cd backend && uv run pytest -m models   # real-model smoke tests
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: serve SPA from backend, docker-compose, running notes"
```

---

## Self-review notes

- Spec coverage (Phase 0/1 backend): §1 layout/compute/hosting → Tasks 1, 2, 16; §3.1–3.6 → Tasks 4–11; §4 → Task 3 (SyllableScore created now, written in Phase 2); §5 → scoring hook only (Phase 2); §8.1 → Task 12; §8.2 export is browser-side (frontend plan) but needs `fmt=mp3` → Task 13; §9 all Phase 1 endpoints → Tasks 11–15 except `/lessons/youtube` (Phase 4); §10 → Task 2; §11 fakes/no-network → every task; Kokoro fixtures and TextGrids are Phase 2.
- Type consistency: `Progress = Callable[[str, float], None]` used identically in jobs, pipeline, anki; `RectSentenceOut(char_from, char_to, text)` consumed by `build_segments`; `Span(ch, start, end, conf)` serialised as `ref_alignment_json`; `build_segments(..., idx_offset=0)` per the Task 12 note.
- Review Focus tests: (1) Task 11 `test_ingest_upload_with_no_speech_sets_error`; (2) Task 6 `test_overlapping_and_unordered_cues_stay_monotonic`; (3) Task 8 `into_context` case; (4) Task 12 HTML + `[sound:]` note; (5) Task 13 no-op PATCH mtime check.
