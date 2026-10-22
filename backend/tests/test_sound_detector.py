from __future__ import annotations
from shadow.scoring.sounds.charctc import group_matrix


def test_group_matrix_pools_heteronyms():
    vocab = {"<pad>": 0, "吃": 1, "行": 2, "a": 3}
    M = group_matrix(vocab, 4, 0, ["chi", "hang", "xing"])
    assert M.shape == (4, 4)
    assert M[0, 0] == 1
    assert M[1, 1] == 1
    assert M[2, 2] == M[2, 3] == 1
    assert M[3].sum() == 0
