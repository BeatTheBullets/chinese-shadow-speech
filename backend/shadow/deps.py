from __future__ import annotations
import logging
from dataclasses import dataclass
from shadow.config import Settings
from shadow.ingest.align import Aligner, FakeAligner, LockedAligner, MmsAligner, make_aligner
from shadow.ingest.asr import ASR, AsrHearer, FakeASR, Hearer, ParaformerASR
from shadow.ingest.transcript import Transcript
from shadow.quant import cpu_threads, int8_wanted
from shadow.ingest.youtube import Downloader, YtDlpDownloader
from shadow.scoring.embed import Embedder, FakeEmbedder, Wav2Vec2Embedder
from shadow.scoring.sounds.charctc import CharCtc
from shadow.scoring.sounds.detector import SoundDetector, Sounds
from shadow.scoring.tone import FakeToneModel, ToneModel, load_tone_model
from shadow.store.files import FileLayout

log = logging.getLogger(__name__)


@dataclass
class Deps:
    asr: ASR
    aligner: Aligner
    files: FileLayout
    settings: Settings
    downloader: Downloader | None = None       # YouTube (addendum §2); None in fake_deps until a test sets one
    tone_model: ToneModel | None = None
    embedder: Embedder | None = None
    sounds: Sounds | None = None               # wrong-sound detector (Phase 3a); None when disabled or unsupported
    sounds_error: str | None = None            # why it is off, for /health
    hearer: Hearer | None = None               # the words check of attempt scoring; None in fake_deps (FakeASR is the lesson)

    def loaded_models(self) -> list[str]:
        out = []
        for name, obj in (("asr", self.asr), ("aligner", self.aligner)):
            if getattr(obj, "_model", None) is not None:
                out.append(name)
        if self.tone_model is not None:
            out.append("tone")
        if getattr(self.embedder, "_model", None) is not None:
            out.append("embedder")
        if getattr(getattr(self.sounds, "chars", None), "_model", None) is not None:
            out.append("sounds")
        return out


def build_deps(settings: Settings) -> Deps:
    """Real adapters. Models load lazily on first use."""
    device = settings.resolved_device()
    if device == "cpu":
        try:
            import torch
            torch.set_num_threads(cpu_threads(settings))
        except ImportError:                    # no `models` extra installed: nothing to cap
            log.debug("torch is not installed; thread cap skipped")
    int8 = int8_wanted(settings)
    files = FileLayout(settings.data_dir)
    asr = ParaformerASR(settings.models.asr, device, punctuation=settings.models.punctuation,
                       segmentation=settings.segmentation, int8=int8)
    aligner = LockedAligner(make_aligner(settings.resolved_aligner(), device, int8))
    sounds, sounds_error = None, None
    if settings.sounds.enabled:
        cfg = settings.sounds
        if isinstance(aligner.inner, MmsAligner):
            sounds = SoundDetector(aligner, CharCtc(cfg.model, cfg.revision, device, int8), cfg)
        else:
            sounds_error = "sounds need the MMS aligner"
    return Deps(asr=asr, hearer=AsrHearer(asr), sounds=sounds, sounds_error=sounds_error,
                aligner=aligner, files=files, settings=settings,
                downloader=YtDlpDownloader(settings.youtube.cookies_file),
                tone_model=load_tone_model(settings.scoring.tone_model),
                embedder=Wav2Vec2Embedder(settings.models.tone_embedder, settings.models.tone_embedder_revision,
                                          settings.models.tone_layer, device))


def fake_deps(settings: Settings, transcript: Transcript) -> Deps:
    return Deps(asr=FakeASR(transcript), aligner=FakeAligner(),
                files=FileLayout(settings.data_dir), settings=settings, tone_model=FakeToneModel(),
                embedder=FakeEmbedder())
