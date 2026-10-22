"""CTC goodness-of-pronunciation over a frame log-prob matrix (MMS letters and char-CTC share it).

Ported from the 3a spike (gop.py): thresholds downstream were calibrated on this exact arithmetic,
so window rules, padding and the widening loop must not change."""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F


def ctc_ll(logp: torch.Tensor, targets: list[list[int]], blank: int) -> np.ndarray:
    """log P(target | frames) for each target (logp: T x C, possibly unnormalised)."""
    T, C = logp.shape
    N = len(targets)
    if N == 0:
        return np.zeros(0)
    lp = logp.unsqueeze(1).expand(T, N, C).contiguous()
    tl = torch.tensor([len(t) for t in targets], dtype=torch.long)
    flat = torch.tensor([x for t in targets for x in t], dtype=torch.long)
    il = torch.full((N,), T, dtype=torch.long)
    with torch.backends.cudnn.flags(enabled=False):
        nll = F.ctc_loss(lp.float(), flat.to(lp.device), il, tl, blank=blank, reduction="none", zero_infinity=False)
    return -nll.double().cpu().numpy()


def need(t: list[int]) -> int:
    # repeated labels need an intervening blank frame, so they cost an extra frame
    return len(t) + sum(1 for a, b in zip(t, t[1:]) if a == b)


def frames_of(win, rate: float, T: int, pad: int = 0) -> tuple[int, int]:
    a = int(np.floor(win[0] / rate - 0.5)) + 1 - pad
    b = int(np.ceil(win[1] / rate - 0.5)) + pad
    return max(0, a), min(T, max(b, a + 1))


def utt_gops(logp: torch.Tensor, blank: int, seq: list[list[int]],
             alts: list[list[list[int]]]) -> list[tuple[float, int] | None]:
    """Per syllable: ll(full) - max_k ll(full with syllable i swapped for alts[i][k]), and the argmax k."""
    full = [x for s in seq for x in s]
    hyps = [full]
    owner: list[int] = []
    for i, al in enumerate(alts):
        for a in al:
            hyps.append([x for j, s in enumerate(seq) for x in (a if j == i else s)])
            owner.append(i)
    ll = ctc_ll(logp, hyps, blank)
    out: list[tuple[float, int] | None] = []
    for i in range(len(seq)):
        alt_ll = [ll[k + 1] for k, o in enumerate(owner) if o == i]
        if not alt_ll:
            out.append(None)
            continue
        k = int(np.argmax(alt_ll))
        out.append((float(ll[0] - alt_ll[k]), k))
    return out


def win_gop(logp: torch.Tensor, blank: int, target: list[int], alts: list[list[int]],
            win: tuple[float, float], frame_s: float) -> float | None:
    """Windowed CTC: ll(target) - max ll(alts) over the syllable's frames, widened until all fit."""
    if not alts:
        return None
    T = logp.shape[0]
    a, b = frames_of(win, frame_s, T, 0)
    req = max(need(t) for t in [target, *alts])
    while b - a < req + 1 and (a > 0 or b < T):
        a, b = max(0, a - 1), min(T, b + 1)
    wl = ctc_ll(logp[a:b], [target, *alts], blank)
    return float(wl[0] - wl[1:].max())
