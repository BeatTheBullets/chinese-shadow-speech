from __future__ import annotations

import math

import numpy as np
import torch

from shadow.scoring.sounds.gop import ctc_ll, utt_gops, win_gop


def _spelled() -> torch.Tensor:
    """T=12 x C=4: blank,1,1,blank,2,2,blank,... with 0.97 on the intended class."""
    cls = [0, 1, 1, 0, 2, 2, 0, 0, 0, 0, 0, 0]
    p = torch.full((12, 4), 0.01)
    for t, c in enumerate(cls):
        p[t, c] = 0.97
    return p.log()


def test_ctc_ll_prefers_the_spoken_sequence():
    ll = ctc_ll(_spelled(), [[1, 2], [1, 3]], 0)
    assert ll[0] > ll[1] + 5


def test_utt_gops_returns_margin_and_best_alt():
    out = utt_gops(_spelled(), 0, [[1], [2]], [[], [[3], [1]]])
    assert out[0] is None
    g, k = out[1]
    assert g > 0
    # [1,1] needs a blank between repeats, so [1,3] is the likelier swap here; derive it independently
    lls = ctc_ll(_spelled(), [[1, 3], [1, 1]], 0)
    assert k == int(np.argmax(lls)) == 0


def test_win_gop_widens_at_edges():
    lp = _spelled()
    g = win_gop(lp, 0, [1, 2, 1], [[1, 2, 2]], (0.0, 0.001), 0.02)
    assert isinstance(g, float) and math.isfinite(g)
    assert win_gop(lp, 0, [1, 2, 1], [], (0.0, 0.001), 0.02) is None
