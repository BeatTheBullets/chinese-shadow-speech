from __future__ import annotations
import os
from dataclasses import dataclass
from shadow.config import Settings
from shadow.ingest.align import Aligner, FakeAligner, LockedAligner, make_aligner
from shadow.ingest.asr import ASR, FakeASR, ParaformerASR
from shadow.ingest.llm import LLM, AnthropicLLM, FakeLLM, RectifyOutput
from shadow.ingest.transcript import Transcript
from shadow.ingest.youtube import Downloader, YtDlpDownloader
from shadow.store.files import FileLayout


@dataclass
class Deps:
    asr: ASR
    llm: LLM | None
    aligner: Aligner
    files: FileLayout
    settings: Settings
    downloader: Downloader | None = None       # YouTube (addendum §2); None in fake_deps until a test sets one

    def loaded_models(self) -> list[str]:
        out = []
        for name, obj in (("asr", self.asr), ("aligner", self.aligner)):
            if getattr(obj, "_model", None) is not None:
                out.append(name)
        return out


def build_deps(settings: Settings) -> Deps:
    """Real adapters. Models load lazily on first use; the LLM is used only with an API key."""
    device = settings.resolved_device()
    files = FileLayout(settings.data_dir)
    llm = None
    if os.environ.get("ANTHROPIC_API_KEY") and (settings.llm.rectify or settings.llm.translate):
        llm = AnthropicLLM(settings.llm.model, settings.llm.effort, files.cache_dir("llm"),
                           settings.segmentation.min_chars, settings.segmentation.max_chars)
    return Deps(asr=ParaformerASR(settings.models.asr, device), llm=llm,
                aligner=LockedAligner(make_aligner(settings.resolved_aligner(), device)), files=files, settings=settings,
                downloader=YtDlpDownloader(settings.youtube.cookies_file))


def fake_deps(settings: Settings, transcript: Transcript) -> Deps:
    def rectify(chunk_chars, ctx):
        return RectifyOutput(sentences=[])          # forces punctuation fallback in tests
    llm = FakeLLM(rectify, lambda xs: [f"en:{x}" for x in xs])
    return Deps(asr=FakeASR(transcript), llm=llm, aligner=FakeAligner(),
                files=FileLayout(settings.data_dir), settings=settings)
