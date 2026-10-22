"""Parity gate for the wrong-sound detector (3a spike): the user's 29 recorded slip pairs through the real models.

Needs his data (SHADOW_DATA_DIR, else the settings' data dir) and a GPU; run by hand with the backend stopped."""
from __future__ import annotations
import json
import os
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlmodel import Session
from shadow.config import Settings, load_settings
from shadow.ingest.align import MmsAligner
from shadow.ingest.audio import read_wav
from shadow.scoring.pitch import trim_silence
from shadow.scoring.reference import reference_audio, segment_syllables
from shadow.scoring.sounds.charctc import CharCtc
from shadow.scoring.sounds.detector import SoundDetector
from shadow.scoring.windows import windows
from shadow.store.models import Attempt, Segment

pytestmark = pytest.mark.models

# (item n, normal attempt id, slip attempt id): pinned by id because the user keeps practising these sentences
PAIRS = [(1,151,152),(2,153,154),(3,155,156),(4,157,158),(5,161,162),(6,163,164),(7,166,167),(8,168,169),(9,170,171),(10,172,173),(11,174,175),(13,176,177),(14,178,179),(15,180,181),(16,182,183),(17,184,185),(18,186,187),(19,189,190),(20,191,192),(21,203,204),(22,205,206),(23,209,210),(24,211,212),(25,215,216),(26,217,218),(27,219,220),(28,221,222),(29,223,224),(30,227,228)]


def _data_dir() -> Path:
    env = os.environ.get("SHADOW_DATA_DIR")
    return Path(env) if env else Path(load_settings().data_dir)


def test_check_set_parity():
    data = _data_dir()
    db, check = data / "shadow.db", data / "reports" / "phase3-checkset.json"
    if not db.exists() or not check.exists():
        pytest.skip(f"no check-set data under {data}")
    items = {it["n"]: it for it in json.loads(check.read_text())}
    cfg = Settings().sounds
    aligner = MmsAligner("cuda")
    det = SoundDetector(aligner, CharCtc(cfg.model, cfg.revision, "cuda"), cfg)
    engine = create_engine(f"sqlite:///file:{db}?mode=ro&uri=true")   # read-only: never writes the user's data

    def run(db_: Session, attempt_id: int, seg: Segment) -> list[dict | None]:
        att = db_.get(Attempt, attempt_id)
        syls = segment_syllables(seg)
        wav, sr = read_wav(Path(att.audio_path))
        trimmed, _ = trim_silence(wav, sr)
        spans = aligner.align(trimmed, sr, seg.text)
        assert len(spans) == len(syls), (attempt_id, "align count")
        usr_win = windows([(s.start, s.end) for s in spans], len(trimmed) / sr)
        statuses = [s["status"] for s in att.score_json["syllables"]]
        ref_wav, ref_sr = reference_audio(seg)
        return det.check(take=trimmed, sr=sr, usr_win=usr_win, ref_wav=ref_wav, ref_sr=ref_sr,
                         ref_key=f"{seg.clip_wav_path}|{seg.text}", syllables=syls, statuses=statuses)

    marked = bad_heard = normal_marked = normal_syls = 0
    with Session(engine) as s:
        for n, normal_id, slip_id in PAIRS:
            it = items[n]
            seg = s.get(Segment, it["segment_id"])
            want = it["slipped_pinyin_toneless"].replace("ü", "v")
            i = it["syl_index"]
            nres, sres = run(s, normal_id, seg), run(s, slip_id, seg)
            normal_syls += len(nres)
            normal_marked += sum(1 for r in nres if r and r["status"] == "slip")
            r = sres[i]
            hit = bool(r and r["status"] == "slip")
            marked += hit
            if hit and r["heard"] != want:
                bad_heard += 1
            print(f"n={n:2d} {it['expected_pinyin_toneless']}->{want} marked={hit} heard={r and r['heard']} "
                  f"z={r and round(r['z'], 2)} normal_marked={sum(1 for x in nres if x and x['status'] == 'slip')}")
    rate = normal_marked / normal_syls
    print(f"slips marked {marked}/{len(PAIRS)}; normal-take false marks {normal_marked}/{normal_syls} = {rate:.1%}; "
          f"wrong heard {bad_heard} (spike: 23/29, 3.9%)")
    assert marked >= 22
    assert rate <= 0.06
    assert bad_heard == 0
