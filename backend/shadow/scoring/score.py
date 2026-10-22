"""Score one take against its reference (Phase 2 spec §1, §3). Pure: no database, no files."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
import logging
import numpy as np
from shadow.config import ScoringCfg
from shadow.ingest.align import Aligner
from shadow.scoring.embed import Embedder, pool
from shadow.scoring.features import FEATURE_VERSION, SylPitch, feature_matrix, syllable_pitch
from shadow.scoring.gate import align_gate, clipped_ratio, level_dbfs, pre_gate, text_similarity
from shadow.scoring.pitch import Baseline, Pitch, baseline_of, blend, normalise, track_pitch, trim_silence
from shadow.scoring.sounds.detector import Sounds
from shadow.scoring.windows import windows
from shadow.scoring.tone import ToneModel, contour_similarity, judge, sentence_overall, target_tone

log = logging.getLogger(__name__)
MIN_SPAN_S = 0.03                         # a learner span shorter than this was skipped or collapsed: missing


@dataclass
class RefData:
    pitch: Pitch                          # on the clip's own time axis
    spans: list[tuple[float, float]]      # each syllable's [start, end] on the same axis
    baseline: Baseline                    # the speaker over the whole lesson (spec §2)
    wav: np.ndarray                       # the reference clip's samples, for its embeddings
    sr: int


@dataclass
class TakeResult:
    json: dict
    rows: list[dict] = field(default_factory=list)
    voiced_f0: np.ndarray = field(default_factory=lambda: np.zeros(0))


def _syl_json(s: dict, status: str, **kw) -> dict:
    base = {"ch": s["ch"], "pinyin": s.get("pinyin", ""), "tone": s["tone"], "target_tone": None, "heard_tone": None,
            "status": status, "tone_score": None, "p_target": None, "contour": None, "seg_score": None,
            "ref_f0": None, "usr_f0": None, "ref_dur": None, "usr_dur": None, "sound": None}
    return {**base, **kw}


def failed_result(syllables: list[dict], warnings: list[str], quality: dict | None = None,
                  model_version: str | None = None, heard_text: str | None = None) -> TakeResult:
    """No score: every syllable missing, no rows, so stats and the voice profile ignore the take."""
    return TakeResult({"overall": None, "tone_overall": None, "segmental_overall": None, "rate_ratio": None,
                       "heard_text": heard_text, "ref_contour": None, "usr_contour": None, "syllables": [_syl_json(s, "missing") for s in syllables],
                       "pitch_range_st": None, "sounds_off": None, "sounds_checked": None, "warnings": warnings, "notices": [], "quality": quality,
                       "model_version": model_version, "feature_version": FEATURE_VERSION})


def _contour_json(t0: float, norm: np.ndarray, spans: list[tuple[float, float]]) -> dict:
    return {"t0_s": round(t0, 3), "step_ms": 10,
            "f0_st": [None if not np.isfinite(v) else round(float(v), 3) for v in norm],
            "spans": [[round(a, 3), round(b, 3)] for a, b in spans]}


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None else round(float(x), nd)


def score_take(*, ref: RefData, syllables: list[dict], text: str, wav: np.ndarray, sr: int, aligner: Aligner,
               embedder: Embedder, model: ToneModel | None, profile: Baseline | None, profile_voiced_s: float, cfg: ScoringCfg,
               hear: Callable[[], str | None] | None = None, sounds: Sounds | None = None,
               ref_key: str = "") -> TakeResult:
    """`hear` returns what the take says (the recogniser); without it, or when it returns None, the words check is
    skipped."""
    trimmed, off = trim_silence(wav, sr)
    ref_speech_s = ref.spans[-1][1] - ref.spans[0][0] if ref.spans else 0.0
    quality = {"dbfs": round(level_dbfs(trimmed), 1), "clipped": round(clipped_ratio(trimmed), 4), "align_conf": None,
               "text_sim": None}
    if warnings := pre_gate(trimmed, sr, ref_speech_s, cfg):
        return failed_result(syllables, warnings, quality)
    if model is None:
        return failed_result(syllables, ["no_tone_model"], quality)
    heard_text = hear() if hear is not None else None
    if heard_text is not None:
        quality["text_sim"] = round(text_similarity(syllables, heard_text), 3)
        if quality["text_sim"] < cfg.min_text_similarity:
            return failed_result(syllables, ["different_words"], quality, model.version, heard_text)
    spans = aligner.align(trimmed, sr, text)
    if len(spans) != len(syllables) or len(ref.spans) != len(syllables):
        return failed_result(syllables, ["align_failed"], quality, model.version, heard_text)
    ref_win = windows(ref.spans, len(ref.wav) / ref.sr)
    usr_win = windows([(s.start, s.end) for s in spans], len(trimmed) / sr)
    quality["align_conf"] = round(float(np.mean([s.conf for s in spans])), 3) if spans else None
    if warnings := align_gate(spans, cfg):
        return failed_result(syllables, warnings, quality, model.version, heard_text)

    pitch = track_pitch(trimmed, sr, cfg.f0_floor, cfg.f0_ceiling)
    w_take = max(0.0, 1.0 - profile_voiced_s / cfg.profile_seconds)
    base = blend(profile, baseline_of(pitch.voiced()), w_take)
    if base is None:
        return failed_result(syllables, ["no_voice"], quality, model.version, heard_text)
    norm_r = normalise(ref.pitch.f0, ref.baseline, cfg.normalise_span)
    norm_u = normalise(pitch.f0, base, cfg.normalise_span)
    syl_r = [syllable_pitch(norm_r, ref.pitch.t0, a, b, cfg.min_voiced_frames) for a, b in ref_win]
    syl_u = [syllable_pitch(norm_u, pitch.t0, a, b, cfg.min_voiced_frames) for a, b in usr_win]
    emb_r = pool(embedder.frames(ref.wav, ref.sr), ref_win)
    emb_u = pool(embedder.frames(trimmed, sr), usr_win)
    P_r, P_u = model.proba(feature_matrix(syl_r, emb_r)), model.proba(feature_matrix(syl_u, emb_u))

    out_syl, rows, prev = [], [], None
    for i, (s, r, u) in enumerate(zip(syllables, syl_r, syl_u)):
        common = {"ref_dur": _r(r.duration), "usr_dur": _r(u.duration),
                  "ref_f0": None if r.contour is None else [_r(v) for v in r.contour],
                  "usr_f0": None if u.contour is None else [_r(v) for v in u.contour]}
        if spans[i].end - spans[i].start < MIN_SPAN_S:
            js = _syl_json(s, "missing", tone_score=0.0, **common)
            target = heard = None
        elif s["tone"] < 0:
            js = _syl_json(s, "unvoiced", **common)
            target = heard = None
        else:
            # a syllable without voiced pitch (either track) is still classified; it just has no contour term (§10)
            target = target_tone(P_r[i], s["tone"], cfg.ref_confidence)
            sim = (None if target == 0 or r.contour is None or u.contour is None
                   else contour_similarity(r.contour, u.contour, cfg.dtw_band, model.dtw_norm))
            v = judge(P_u[i], target, sim, cfg)
            heard = v.heard
            js = _syl_json(s, v.status, target_tone=target, heard_tone=heard, tone_score=_r(v.tone_score),
                           p_target=_r(v.p_target), contour=_r(v.contour), **common)
        out_syl.append(js)
        rows.append({"idx": i, "ch": s["ch"], "pinyin_toneless": s.get("pinyin_toneless", ""), "tone": s["tone"],
                     "prev_tone": prev, "target_tone": target, "heard_tone": heard,
                     "tone_score": js["tone_score"], "status": js["status"], "sound_status": None, "heard_syllable": None})
        prev = target if target is not None else s["tone"]

    sounds_off = sounds_checked = None
    if sounds is not None:
        # a sound failure never fails a take: the tone result above is already final and stays identical without sounds
        try:
            found = sounds.check(take=trimmed, sr=sr, usr_win=usr_win, ref_wav=ref.wav, ref_sr=ref.sr, ref_key=ref_key,
                                 syllables=syllables, statuses=[x["status"] for x in out_syl])
        except Exception:  # noqa: BLE001
            log.exception("the sound check failed; the take keeps its tone score")
        else:
            sounds_checked = sum(f is not None for f in found)
            sounds_off = sum(f is not None and f["status"] == "slip" for f in found)
            for js, row, f in zip(out_syl, rows, found):
                js["sound"] = f
                row["sound_status"] = None if f is None else f["status"]
                row["heard_syllable"] = None if f is None else f["heard_pinyin"]
                row["seg_score"] = None if f is None else _r(f["z"])

    overall = sentence_overall([(x["status"], x["tone_score"]) for x in out_syl])
    usr_spans = [(a + off, b + off) for a, b in usr_win]
    return TakeResult({
        "overall": _r(overall), "heard_text": heard_text, "tone_overall": _r(overall), "segmental_overall": None,
        "rate_ratio": _r((spans[-1].end - spans[0].start) / ref_speech_s) if ref_speech_s > 0 else None,
        "ref_contour": _contour_json(ref.pitch.t0, norm_r, ref_win),
        "usr_contour": _contour_json(pitch.t0 + off, norm_u, usr_spans),
        "syllables": out_syl, "sounds_off": sounds_off, "sounds_checked": sounds_checked, "pitch_range_st": {"ref": _r(ref.baseline.spread_st), "usr": _r(base.spread_st)},
        "warnings": [], "quality": quality, "model_version": model.version, "feature_version": FEATURE_VERSION,
        # scored, but some words sounded different (spec §1): `warnings` stays empty, as it does for every scored take
        "notices": ["words_differ"] if quality["text_sim"] is not None and quality["text_sim"] < cfg.words_ok_at else [],
    }, rows, pitch.voiced())
