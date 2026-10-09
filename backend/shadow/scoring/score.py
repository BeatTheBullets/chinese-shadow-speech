"""Score one take against its reference (Phase 2 spec §1, §3). Pure: no database, no files."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from shadow.config import ScoringCfg
from shadow.ingest.align import Aligner
from shadow.scoring.features import FEATURE_VERSION, SylPitch, feature_matrix, syllable_pitch
from shadow.scoring.gate import align_gate, clipped_ratio, level_dbfs, pre_gate
from shadow.scoring.pitch import Baseline, Pitch, baseline_of, blend, normalise, track_pitch, trim_silence
from shadow.scoring.tone import ToneModel, contour_similarity, judge, sentence_overall, target_tone

MIN_SPAN_S = 0.03                         # a learner span shorter than this was skipped or collapsed: missing


@dataclass
class RefData:
    pitch: Pitch                          # on the clip's own time axis
    spans: list[tuple[float, float]]      # each syllable's [start, end] on the same axis
    baseline: Baseline                    # the speaker over the whole lesson (spec §2)


@dataclass
class TakeResult:
    json: dict
    rows: list[dict] = field(default_factory=list)
    voiced_f0: np.ndarray = field(default_factory=lambda: np.zeros(0))


def _syl_json(s: dict, status: str, **kw) -> dict:
    base = {"ch": s["ch"], "pinyin": s.get("pinyin", ""), "tone": s["tone"], "target_tone": None, "heard_tone": None,
            "status": status, "tone_score": None, "p_target": None, "contour": None, "seg_score": None,
            "ref_f0": None, "usr_f0": None, "ref_dur": None, "usr_dur": None}
    return {**base, **kw}


def failed_result(syllables: list[dict], warnings: list[str], quality: dict | None = None,
                  model_version: str | None = None) -> TakeResult:
    """No score: every syllable missing, no rows, so stats and the voice profile ignore the take."""
    return TakeResult({"overall": None, "tone_overall": None, "segmental_overall": None, "rate_ratio": None,
                       "ref_contour": None, "usr_contour": None, "syllables": [_syl_json(s, "missing") for s in syllables],
                       "pitch_range_st": None, "warnings": warnings, "quality": quality,
                       "model_version": model_version, "feature_version": FEATURE_VERSION})


def _contour_json(t0: float, norm: np.ndarray, spans: list[tuple[float, float]]) -> dict:
    return {"t0_s": round(t0, 3), "step_ms": 10,
            "f0_st": [None if not np.isfinite(v) else round(float(v), 3) for v in norm],
            "spans": [[round(a, 3), round(b, 3)] for a, b in spans]}


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None else round(float(x), nd)


def score_take(*, ref: RefData, syllables: list[dict], text: str, wav: np.ndarray, sr: int, aligner: Aligner,
               model: ToneModel | None, profile: Baseline | None, profile_voiced_s: float, cfg: ScoringCfg) -> TakeResult:
    trimmed, off = trim_silence(wav, sr)
    ref_speech_s = ref.spans[-1][1] - ref.spans[0][0] if ref.spans else 0.0
    quality = {"dbfs": round(level_dbfs(trimmed), 1), "clipped": round(clipped_ratio(trimmed), 4), "align_conf": None}
    if warnings := pre_gate(trimmed, sr, ref_speech_s, cfg):
        return failed_result(syllables, warnings, quality)
    if model is None:
        return failed_result(syllables, ["no_tone_model"], quality)
    spans = aligner.align(trimmed, sr, text)
    if len(spans) != len(syllables) or len(ref.spans) != len(syllables):
        return failed_result(syllables, ["align_failed"], quality, model.version)
    quality["align_conf"] = round(float(np.mean([s.conf for s in spans])), 3) if spans else None
    if warnings := align_gate(spans, cfg):
        return failed_result(syllables, warnings, quality, model.version)

    pitch = track_pitch(trimmed, sr, cfg.f0_floor, cfg.f0_ceiling)
    w_take = max(0.0, 1.0 - profile_voiced_s / cfg.profile_seconds)
    base = blend(profile, baseline_of(pitch.voiced()), w_take)
    if base is None:
        return failed_result(syllables, ["no_voice"], quality, model.version)
    norm_r = normalise(ref.pitch.f0, ref.baseline, cfg.normalise_span)
    norm_u = normalise(pitch.f0, base, cfg.normalise_span)
    syl_r = [syllable_pitch(norm_r, ref.pitch.t0, a, b, cfg.min_voiced_frames) for a, b in ref.spans]
    syl_u = [syllable_pitch(norm_u, pitch.t0, s.start, s.end, cfg.min_voiced_frames) for s in spans]
    P_r, P_u = model.proba(feature_matrix(syl_r)), model.proba(feature_matrix(syl_u))

    out_syl, rows, prev = [], [], None
    for i, (s, r, u) in enumerate(zip(syllables, syl_r, syl_u)):
        common = {"ref_dur": _r(r.duration), "usr_dur": _r(u.duration),
                  "ref_f0": None if r.contour is None else [_r(v) for v in r.contour],
                  "usr_f0": None if u.contour is None else [_r(v) for v in u.contour]}
        if u.duration < MIN_SPAN_S:
            js = _syl_json(s, "missing", tone_score=0.0, **common)
            target = heard = None
        elif s["tone"] < 0 or r.contour is None or u.contour is None:
            js = _syl_json(s, "unvoiced", **common)
            target = heard = None
        else:
            target = target_tone(P_r[i], s["tone"], cfg.ref_confidence)
            sim = None if target == 0 else contour_similarity(r.contour, u.contour, cfg.dtw_band, model.dtw_norm)
            v = judge(P_u[i], target, sim, cfg)
            heard = v.heard
            js = _syl_json(s, v.status, target_tone=target, heard_tone=heard, tone_score=_r(v.tone_score),
                           p_target=_r(v.p_target), contour=_r(v.contour), **common)
        out_syl.append(js)
        rows.append({"idx": i, "ch": s["ch"], "pinyin_toneless": s.get("pinyin_toneless", ""), "tone": s["tone"],
                     "prev_tone": prev, "target_tone": target, "heard_tone": heard,
                     "tone_score": js["tone_score"], "status": js["status"]})
        prev = target if target is not None else s["tone"]

    overall = sentence_overall([(x["status"], x["tone_score"]) for x in out_syl])
    usr_spans = [(s.start + off, s.end + off) for s in spans]
    return TakeResult({
        "overall": _r(overall), "tone_overall": _r(overall), "segmental_overall": None,
        "rate_ratio": _r((spans[-1].end - spans[0].start) / ref_speech_s) if ref_speech_s > 0 else None,
        "ref_contour": _contour_json(ref.pitch.t0, norm_r, ref.spans),
        "usr_contour": _contour_json(pitch.t0 + off, norm_u, usr_spans),
        "syllables": out_syl, "pitch_range_st": {"ref": _r(ref.baseline.spread_st), "usr": _r(base.spread_st)},
        "warnings": [], "quality": quality, "model_version": model.version, "feature_version": FEATURE_VERSION,
    }, rows, pitch.voiced())
