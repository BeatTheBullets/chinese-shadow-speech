"""Train the tone classifier on AISHELL-3 (Phase 2 spec §4, §10, §10.1). Run once; the two output files are committed.

    cd backend && ~/.local/bin/uv run python scripts/tone_model.py --labels realised
Stages, each resumable: download and unpack (~19 GB, curl -C) → per-speaker features (native rows plus pitch-altered
copies) cached under <root>/features_v<FEATURE_VERSION>_<labels>/ → train → evaluate on held-out speakers (native,
altered and flat copies) → write shadow/scoring/models/<name>.{joblib,json}. Features need the models extra
and the GPU."""
from __future__ import annotations
import argparse
import json
import random
import subprocess
import tarfile
import zlib
from collections import defaultdict
from datetime import date
from pathlib import Path
import numpy as np
import soundfile as sf
from shadow.config import load_settings
from shadow.ingest.align import make_aligner
from shadow.scoring.augment import FRACS, LEVEL, TEMPLATES, alter_choices, contour_units, resynth
from shadow.scoring.corpus import Utterance, read_split, realise
from shadow.scoring.embed import Wav2Vec2Embedder, pool
from shadow.scoring.features import FEATURE_VERSION, N_FEATURES, POINTS, dtw_distance, feature_matrix, syllable_pitch
from shadow.scoring.pitch import baseline_of, normalise, track_pitch
from shadow.scoring.tone import MODELS_DIR, TONES
from shadow.scoring.windows import windows

URL = "https://www.openslr.org/resources/93/data_aishell3.tgz"
TEST_SHARE = 0.15
MAX_PAIRS = 20000
NATIVE, ALTERED, FLAT = 0, 1, 2           # row kinds; flat copies exist only for test speakers
ALTERED_COPIES = 2                        # per training utterance (test speakers get one)
MAX_TRAIN_ROWS = 120_000                  # a uniform sample, ≈ 1.1 GB of float32: fit + early stopping fit 8 GB


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


def held_out(spks: list[str]) -> set[str]:
    """The test speakers, fixed by the speaker list: the feature stage must know them (they get the flat copy)."""
    s = sorted(spks)
    random.Random(0).shuffle(s)
    return set(s[: max(1, int(len(s) * TEST_SHARE))])


def speaker_features(aligner, embedder, cfg, utts: list[Utterance], labels: str, test: bool,
                     rng: np.random.Generator) -> dict[str, np.ndarray]:
    """Rows for one speaker (spec §10.1): every labelled native syllable, then pitch-altered copies of each utterance
    (two for a training speaker; one plus an all-flat copy for a test speaker). Each copy's pitch is re-tracked and
    normalised to the speaker's native baseline over all of their utterances, as the app does (spec §2)."""
    done = []
    for u in utts:
        wav, sr = sf.read(u.wav, dtype="float32", always_2d=False)
        spans = aligner.align(wav, sr, "".join(u.chars))
        if len(spans) == len(u.chars):
            tones = realise(u) if labels == "canonical" else list(u.tones)
            done.append((tones, wav, sr, windows([(s.start, s.end) for s in spans], len(wav) / sr),
                         track_pitch(wav, sr, cfg.f0_floor, cfg.f0_ceiling)))
    base = baseline_of(np.concatenate([p.voiced() for *_, p in done])) if done else None
    kinds = [NATIVE, ALTERED] + ([FLAT] if test else [ALTERED] * (ALTERED_COPIES - 1))
    rows: dict[str, list] = {k: [] for k in ("X", "y", "ctx", "contours", "voiced", "kind", "orig")}
    for kind in kinds if base else []:
        for tones, wav, sr, wins, p0 in done:
            orig = [t if t is not None else -1 for t in tones]
            if kind == NATIVE:
                audio, p, lab = wav, p0, orig
            else:
                if kind == FLAT:
                    units = [contour_units("flat", rng) for _ in wins]
                    lab = [1 if t in (1, 2, 3, 4) else -1 for t in orig]
                else:
                    choices, lab = alter_choices(tones, rng)
                    units = [contour_units(c, rng) for c in choices]
                audio = resynth(wav, sr, wins, units, base, cfg.f0_floor, cfg.f0_ceiling)
                p = track_pitch(audio, sr, cfg.f0_floor, cfg.f0_ceiling)
            norm = normalise(p.f0, base, cfg.normalise_span)
            sylls = [syllable_pitch(norm, p.t0, a, b, cfg.min_voiced_frames) for a, b in wins]
            F = feature_matrix(sylls, pool(embedder.frames(audio, sr), wins))
            for i, (y, s) in enumerate(zip(lab, sylls)):
                if y == -1:
                    continue
                rows["X"].append(F[i]); rows["y"].append(y); rows["kind"].append(kind); rows["orig"].append(orig[i])
                rows["ctx"].append((orig[i - 1] if i else -1, orig[i + 1] if i + 1 < len(orig) else -1))
                rows["voiced"].append(s.contour is not None)
                rows["contours"].append(s.contour if s.contour is not None else np.full(POINTS, np.nan))
    return {"X": np.asarray(rows["X"], np.float32).reshape(-1, N_FEATURES), "y": np.asarray(rows["y"], np.int64),
            "ctx": np.asarray(rows["ctx"], np.int64).reshape(-1, 2),
            "contours": np.asarray(rows["contours"], np.float32).reshape(-1, POINTS),
            "voiced": np.asarray(rows["voiced"], bool), "kind": np.asarray(rows["kind"], np.int8),
            "orig": np.asarray(rows["orig"], np.int64)}


def features_dir(root: Path, labels: str) -> Path:
    """Keyed by labels too: cached rows carry the label mode they were built with."""
    return root / f"features_v{FEATURE_VERSION}_{labels}"


def features(root: Path, utts: list[Utterance], labels: str) -> Path:
    settings = load_settings()
    cfg, m, device = settings.scoring, settings.models, settings.resolved_device()
    out = features_dir(root, labels)
    out.mkdir(exist_ok=True)
    aligner = make_aligner("mms_fa", device)
    embedder = Wav2Vec2Embedder(m.tone_embedder, m.tone_embedder_revision, m.tone_layer, device)
    by_spk: dict[str, list[Utterance]] = defaultdict(list)
    for u in utts:
        by_spk[u.speaker].append(u)
    test = held_out(list(by_spk))
    for n, (spk, us) in enumerate(sorted(by_spk.items()), 1):
        f = out / f"{spk}.npz"
        if not f.exists():
            rng = np.random.default_rng(zlib.crc32(spk.encode()))
            tmp = out / f"{spk}.npz.part"          # an interrupted write must not look like a finished speaker
            with open(tmp, "wb") as fh:
                np.savez(fh, **speaker_features(aligner, embedder, cfg, us, labels, spk in test, rng))
            tmp.rename(f)
        print(f"[{n}/{len(by_spk)}] {spk}: {len(us)} utterances", flush=True)
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
    from sklearn.metrics import confusion_matrix
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    settings = load_settings()
    cfg = settings.scoring
    files = sorted(features_dir(root, labels).glob("*.npz"))
    test_spk = held_out([f.stem for f in files])
    tr = [f for f in files if f.stem not in test_spk]
    # Native + altered rows of the training speakers: count them, draw a uniform sample of at most MAX_TRAIN_ROWS,
    # then copy only the sampled rows speaker by speaker into one float32 array
    counts = []
    for f in tr:
        with np.load(f) as d:
            if np.any(d["kind"] == FLAT):
                raise SystemExit(f"{f.name} has a flat copy but is a training speaker: cache built for another speaker set")
            counts.append(len(d["kind"]))
    total = int(sum(counts))
    sel = np.sort(np.random.default_rng(0).choice(total, size=min(total, MAX_TRAIN_ROWS), replace=False))
    n = len(sel)
    Xtr, ytr, i, n_alt, off = np.empty((n, N_FEATURES), np.float32), np.empty(n, np.int64), 0, 0, 0
    for f, k in zip(tr, counts):
        local = sel[(sel >= off) & (sel < off + k)] - off
        off += k
        if len(local):
            with np.load(f) as d:
                Xtr[i: i + len(local)], ytr[i: i + len(local)] = d["X"][local], d["y"][local]
                i, n_alt = i + len(local), n_alt + int(np.sum(d["kind"][local] == ALTERED))
    clf = make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(256,), early_stopping=True, random_state=0))
    clf.set_params(standardscaler__copy=False)      # scale Xtr in place: no second copy next to early stopping's split
    clf.fit(Xtr, ytr)
    clf.set_params(standardscaler__copy=True)       # the app's rows must not be rewritten by proba
    del Xtr
    te = [(f.stem, dict(np.load(f))) for f in files if f.stem in test_spk]
    T = {k: np.concatenate([d[k] for _, d in te]) for k in ("X", "y", "kind", "orig")}
    P = clf.predict_proba(T["X"])
    classes = np.asarray([int(c) for c in clf.classes_])
    pred, y, kind = classes[P.argmax(axis=1)], T["y"], T["kind"]
    if not np.isin(y, classes).all():
        raise SystemExit(f"test labels {sorted(set(y.tolist()) - set(classes.tolist()))} never seen in training")
    p_true = P[np.arange(len(y)), np.searchsorted(classes, y)]
    nat, alt = kind == NATIVE, kind == ALTERED
    flat = (kind == FLAT) & np.isin(T["orig"], (2, 3, 4))
    acc, acc_alt = float(np.mean(pred[nat] == y[nat])), float(np.mean(pred[alt] == y[alt]))
    native_voiced = [(s, {k: d[k][(d["kind"] == NATIVE) & d["voiced"]] for k in ("y", "ctx", "contours")})
                     for s, d in te]
    m = settings.models
    meta = {"version": f"{name}-{date.today().isoformat()}", "feature_version": FEATURE_VERSION, "classes": list(TONES),
            "dtw_norm": dtw_norm(native_voiced, cfg.dtw_band), "accuracy": acc,
            "per_tone": {str(t): float(np.mean(pred[nat & (y == t)] == t)) for t in TONES if np.any(nat & (y == t))},
            "confusion": confusion_matrix(y[nat], pred[nat], labels=list(TONES)).tolist(),
            "accuracy_altered": acc_alt,
            "per_tone_altered": {str(t): float(np.mean(pred[alt & (y == t)] == t))
                                 for t in TONES if np.any(alt & (y == t))},
            "false_wrong_native": float(np.mean((P.max(axis=1) - p_true)[nat] >= cfg.wrong_margin)),
            "flat_still_original": float(np.mean(pred[flat] == T["orig"][flat])),
            "n_train": n, "n_train_altered": n_alt, "train_rows_total": total, "train_rows_used": n,
            "n_test": int(nat.sum()), "n_test_altered": int(alt.sum()), "n_test_flat": int(flat.sum()),
            "test_speakers": sorted(test_spk), "hours": hours, "labels": labels,
            "embedder": m.tone_embedder, "embedder_revision": m.tone_embedder_revision, "layer": m.tone_layer,
            "augmentation": {"level": LEVEL, "templates": {str(k): v for k, v in TEMPLATES.items()}, "fracs": FRACS,
                             "altered_copies_train": ALTERED_COPIES, "altered_copies_test": 1, "flat_copy_test": 1},
            "corpus": "AISHELL-3 (OpenSLR SLR93, Apache-2.0)", "sklearn": sklearn.__version__,
            "date": date.today().isoformat()}
    text = json.dumps(meta, indent=1, allow_nan=False)      # a NaN metric fails here, before any file is written
    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(clf, MODELS_DIR / f"{name}.joblib", compress=3)
    (MODELS_DIR / f"{name}.json").write_text(text)
    print(json.dumps({k: meta[k] for k in ("accuracy", "per_tone", "accuracy_altered", "per_tone_altered",
                                           "false_wrong_native", "flat_still_original", "dtw_norm",
                                           "train_rows_total", "train_rows_used", "n_test")}, indent=1))
    print("ACCEPT" if acc >= 0.85 and acc_alt >= 0.85 else "BELOW 0.85 — stop and decide (spec §10.1)")


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=load_settings().data_dir / "corpora" / "aishell3")
    ap.add_argument("--hours", type=float, default=10.0)
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
