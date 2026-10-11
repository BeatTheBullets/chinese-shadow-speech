"""Speech-model embeddings for the tone classifier (Phase 2 spec §10): one hidden layer of a pretrained Chinese
wav2vec2, mean-pooled over each aligned syllable. Raw 16 kHz input, fp32, exactly as the model was trained."""
from __future__ import annotations
import threading
from typing import Protocol
import numpy as np

FRAME_S = 0.02                           # wav2vec2 frame step at 16 kHz
DIM = 768
_CENTRE = 0.0125                         # frame i covers ~[i·20 ms, i·20 ms + 25 ms]


class Embedder(Protocol):
    def frames(self, wav: np.ndarray, sr: int) -> np.ndarray: ...


class FakeEmbedder:
    """Tests: every dimension of frame i holds the mean absolute amplitude of its 20 ms (no model)."""
    def frames(self, wav: np.ndarray, sr: int) -> np.ndarray:
        hop = int(FRAME_S * sr)
        n = max(len(wav) // hop, 1)
        e = np.abs(np.asarray(wav, np.float32)[: n * hop]).reshape(n, hop).mean(axis=1) if len(wav) >= hop else np.zeros(1)
        return np.repeat(e[:, None], DIM, axis=1).astype(np.float32)


class Wav2Vec2Embedder:
    def __init__(self, name: str, revision: str, layer: int, device: str):
        self.name, self.revision, self.layer, self.device = name, revision, layer, device
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            from transformers import Wav2Vec2Model
            self._model = Wav2Vec2Model.from_pretrained(self.name, revision=self.revision).to(self.device).eval()
        return self._model

    def frames(self, wav: np.ndarray, sr: int) -> np.ndarray:
        import torch
        import torchaudio.functional as AF
        with self._lock:
            model = self._load()
            x = torch.from_numpy(np.asarray(wav, np.float32))[None].to(self.device)
            if sr != 16000:
                x = AF.resample(x, sr, 16000)
            with torch.inference_mode():
                hs = model(x, output_hidden_states=True).hidden_states[self.layer]
            return hs[0].float().cpu().numpy()


def pool(frames: np.ndarray, spans: list[tuple[float, float]]) -> np.ndarray:
    """Mean of the frames whose centre lies inside each [start, end]; the nearest frame when none does."""
    if len(frames) == 0:
        raise ValueError("no embedding frames")
    centres = np.arange(len(frames)) * FRAME_S + _CENTRE
    out = np.zeros((len(spans), frames.shape[1]), np.float32)
    for i, (a, b) in enumerate(spans):
        idx = np.flatnonzero((centres >= a) & (centres <= b))
        out[i] = frames[idx].mean(axis=0) if len(idx) else frames[int(np.argmin(np.abs(centres - (a + b) / 2)))]
    return out
