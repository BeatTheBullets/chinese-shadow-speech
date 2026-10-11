"""Train the tone classifier on AISHELL-3 (Phase 2 spec §4). Run once; the two output files are committed.

    cd backend && ~/.local/bin/uv run python scripts/tone_model.py --labels canonical
Stages, each resumable: download and unpack (~19 GB, curl -C) → per-speaker features cached under
<root>/features_v<FEATURE_VERSION>/ → train → evaluate on held-out speakers → write
shadow/scoring/models/<name>.{joblib,json}. Alignment needs the models extra and the GPU (~1–2 h for 30 h)."""
from __future__ import annotations
import argparse
import json
import random
import subprocess
import tarfile
from collections import defaultdict
from datetime import date
from pathlib import Path
import numpy as np
import soundfile as sf
from shadow.config import load_settings
from shadow.ingest.align import make_aligner
from shadow.scoring.corpus import Utterance, read_split, realise
from shadow.scoring.features import FEATURE_VERSION, POINTS, dtw_distance, syllable_pitch
from shadow.scoring.features import N_PITCH as N_FEATURES, pitch_matrix as feature_matrix   # rewritten in Task 18
from shadow.scoring.pitch import baseline_of, normalise, track_pitch
from shadow.scoring.tone import MODELS_DIR, TONES

URL = "https://www.openslr.org/resources/93/data_aishell3.tgz"
TEST_SHARE = 0.15
MAX_PAIRS = 20000


def download(root: Path) -> None:
    if list(root.rglob("content.txt")):
        return
    root.mkdir(parents=True, exist_ok=True)
    tgz = root / "data_aishell3.tgz"
    subprocess.run(["curl", "-L", "-C", "-", "-o", str(tgz), URL], check=True)
    with tarfile.open(tgz) as t:
        t.extractall(root, filter="data")
    tgz.unlink()


def pick(root: Path, hours: float) -> list[Utterance]:
    """A fixed random subset of all utterances (both official splits) adding up to `hours`."""
    utts = [u for c in sorted(root.rglob("content.txt")) for u in read_split(c.parent)]
    random.Random(0).shuffle(utts)
    out, total = [], 0.0
    for u in utts:
        if total >= hours * 3600:
            break
        if u.wav.exists():
            total += sf.info(u.wav).duration
            out.append(u)
    print(f"{len(out)} utterances, {total / 3600:.1f} h, {len({u.speaker for u in out})} speakers")
    return out


def speaker_features(aligner, cfg, utts: list[Utterance], labels: str) -> dict[str, np.ndarray]:
    """Rows for every labelled, voiced syllable of one speaker, normalised to that speaker's baseline over all of
    their utterances (the same definition as the app, spec §2)."""
    done = []
    for u in utts:
        wav, sr = sf.read(u.wav, dtype="float32", always_2d=False)
        spans = aligner.align(wav, sr, "".join(u.chars))
        if len(spans) == len(u.chars):
            done.append((u, track_pitch(wav, sr, cfg.f0_floor, cfg.f0_ceiling), spans))
    base = baseline_of(np.concatenate([p.voiced() for _, p, _ in done])) if done else None
    X, y, ctx, contours = [], [], [], []
    for u, p, spans in done if base else []:
        norm = normalise(p.f0, base, cfg.normalise_span)
        sylls = [syllable_pitch(norm, p.t0, s.start, s.end, cfg.min_voiced_frames) for s in spans]
        F = feature_matrix(sylls)
        tones = realise(u) if labels == "canonical" else list(u.tones)
        for i, (t, s) in enumerate(zip(tones, sylls)):
            if t is None or s.contour is None:
                continue
            X.append(F[i]); y.append(t); contours.append(s.contour)
            ctx.append((tones[i - 1] if i and tones[i - 1] is not None else -1,
                        tones[i + 1] if i + 1 < len(tones) and tones[i + 1] is not None else -1))
    return {"X": np.asarray(X, np.float32).reshape(-1, N_FEATURES), "y": np.asarray(y, np.int64),
            "ctx": np.asarray(ctx, np.int64).reshape(-1, 2), "contours": np.asarray(contours, np.float32).reshape(-1, POINTS)}


def features_dir(root: Path, labels: str) -> Path:
    """Keyed by labels too: cached rows carry the label mode they were built with."""
    return root / f"features_v{FEATURE_VERSION}_{labels}"


def features(root: Path, utts: list[Utterance], labels: str) -> Path:
    cfg = load_settings().scoring
    out = features_dir(root, labels)
    out.mkdir(exist_ok=True)
    aligner = make_aligner("mms_fa", load_settings().resolved_device())
    by_spk: dict[str, list[Utterance]] = defaultdict(list)
    for u in utts:
        by_spk[u.speaker].append(u)
    for n, (spk, us) in enumerate(sorted(by_spk.items()), 1):
        f = out / f"{spk}.npz"
        if not f.exists():
            np.savez(f, **speaker_features(aligner, cfg, us, labels))
        print(f"[{n}/{len(by_spk)}] {spk}: {len(us)} utterances")
    return out


def dtw_norm(test: list[tuple[str, dict]], band: int) -> float:
    """median DTW over same-tone, same-context pairs from two different held-out speakers, / 0.1 (spec §4.4)."""
    groups: dict[tuple[int, int, int], list[tuple[str, np.ndarray]]] = defaultdict(list)
    for spk, d in test:
        for t, (p, nx), c in zip(d["y"], d["ctx"], d["contours"]):
            groups[(int(p), int(t), int(nx))].append((spk, c))
    keys = [k for k, v in groups.items() if len({s for s, _ in v}) > 1]
    rng, dists = random.Random(0), []
    for _ in range(MAX_PAIRS * 3):
        if len(dists) >= MAX_PAIRS or not keys:
            break
        g = groups[rng.choice(keys)]
        (s1, a), (s2, b) = rng.sample(g, 2)
        if s1 != s2:
            dists.append(dtw_distance(a, b, band))
    if not dists or not np.isfinite(np.median(dists)):
        raise SystemExit("no cross-speaker same-context pairs for dtw_norm: too few held-out speakers")
    return float(np.median(dists) / 0.1)


def train(root: Path, name: str, hours: float, labels: str) -> None:
    import joblib
    import sklearn
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import confusion_matrix
    cfg = load_settings().scoring
    files = sorted(features_dir(root, labels).glob("*.npz"))
    spks = [f.stem for f in files]
    random.Random(0).shuffle(spks)
    test_spk = set(spks[: max(1, int(len(spks) * TEST_SHARE))])
    tr, te = [], []
    for f in files:
        d = dict(np.load(f))
        (te if f.stem in test_spk else tr).append((f.stem, d))
    Xtr = np.concatenate([d["X"] for _, d in tr]); ytr = np.concatenate([d["y"] for _, d in tr])
    Xte = np.concatenate([d["X"] for _, d in te]); yte = np.concatenate([d["y"] for _, d in te])
    clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.1, early_stopping=True, random_state=0)
    clf.fit(Xtr, ytr)
    pred = clf.predict(Xte)
    acc = float(np.mean(pred == yte))
    per_tone = {str(t): float(np.mean(pred[yte == t] == t)) for t in TONES if np.any(yte == t)}
    meta = {"version": f"{name}-{date.today().isoformat()}", "feature_version": FEATURE_VERSION, "classes": list(TONES),
            "dtw_norm": dtw_norm(te, cfg.dtw_band), "accuracy": acc, "per_tone": per_tone,
            "confusion": confusion_matrix(yte, pred, labels=list(TONES)).tolist(),
            "n_train": int(len(ytr)), "n_test": int(len(yte)), "test_speakers": sorted(test_spk),
            "hours": hours, "labels": labels, "corpus": "AISHELL-3 (OpenSLR SLR93, Apache-2.0)",
            "sklearn": sklearn.__version__, "date": date.today().isoformat()}
    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(clf, MODELS_DIR / f"{name}.joblib", compress=3)
    (MODELS_DIR / f"{name}.json").write_text(json.dumps(meta, indent=1, allow_nan=False))
    print(json.dumps({k: meta[k] for k in ("accuracy", "per_tone", "dtw_norm", "n_train", "n_test")}, indent=1))
    print("ACCEPT" if acc >= 0.85 else "BELOW 0.85 — stop and decide (spec §4.4)")


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=load_settings().data_dir / "corpora" / "aishell3")
    ap.add_argument("--hours", type=float, default=30.0)
    ap.add_argument("--labels", choices=["canonical", "realised"], required=True)
    ap.add_argument("--name", default="tone_v1")
    ap.add_argument("--stage", choices=["all", "features", "train"], default="all")
    a = ap.parse_args()
    if a.stage in ("all", "features"):
        download(a.root)
        features(a.root, pick(a.root, a.hours), a.labels)
    if a.stage in ("all", "train"):
        train(a.root, a.name, a.hours, a.labels)


if __name__ == "__main__":
    main()
