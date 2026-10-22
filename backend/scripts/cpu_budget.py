"""CPU memory benchmark: runs the real app on a fresh temporary data dir and reports peak RSS per phase.

    CUDA_VISIBLE_DEVICES="" uv run python scripts/cpu_budget.py --clip CLIP.wav --device cpu --threads 4 [--int8] [--budget]

CLIP is a 5-minute 16 kHz mono clip; make one from any lesson's source.wav with
    ffmpeg -i source.wav -t 300 -ar 16000 -ac 1 clip.wav
Always run with CUDA_VISIBLE_DEVICES="" so nothing lands on a GPU. Phases (default all): startup (app serves,
/health answers), build (upload the clip as a lesson), practice (8 scored takes, the lesson's own clips as audio),
build+practice (a second lesson builds while 8 more takes are scored). Prints one JSON line
{"phases": [{"name", "seconds", "peak_mb"}], "take_seconds": [...]}. --budget exits 1 when a phase peak is over its
budget (startup/practice 3000 MB, build/build+practice 3500 MB). RSS over --hard-cap-mb (default 5000) aborts the run
at once with exit 3, so a runaway run cannot make the kernel OOM-killer pick other processes."""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

BUDGET_MB = {"startup": 3000, "build": 3500, "practice": 3000, "build+practice": 3500}
PHASES = list(BUDGET_MB)
N_TAKES = 8


class Sampler(threading.Thread):
    """Samples this process's RSS every 0.1 s into the current phase's peak; aborts the process over the hard cap."""

    def __init__(self, hard_cap_mb: float):
        super().__init__(daemon=True)
        self.proc, self.cap = psutil.Process(), hard_cap_mb
        self.phase, self.peaks = "startup", {}
        self.halt = threading.Event()

    def run(self) -> None:
        while not self.halt.wait(0.1):
            mb = self.proc.memory_info().rss / 1e6
            self.peaks[self.phase] = max(self.peaks.get(self.phase, 0.0), mb)
            if mb > self.cap:
                print(f"over hard cap: phase {self.phase} RSS {mb:.0f} MB > {self.cap:.0f} MB; aborting",
                      file=sys.stderr, flush=True)
                print(json.dumps({"aborted": True, "phase": self.phase, "rss_mb": round(mb),
                                  "peaks_mb": {k: round(v) for k, v in self.peaks.items()}}), flush=True)
                os._exit(3)


def wait_job(client, job_id: str) -> None:
    while True:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            if job["status"] != "done":
                raise SystemExit(f"job {job_id} {job['status']}: {job.get('error')}")
            return
        time.sleep(0.5)


def upload(client, clip: Path, title: str) -> dict:
    with clip.open("rb") as f:
        r = client.post("/lessons", files={"file": (clip.name, f, "audio/wav")}, data={"title": title})
    r.raise_for_status()
    return r.json()


def take_audio(client, files, lesson_id: int) -> list[tuple[int, Path]]:
    segs = client.get(f"/lessons/{lesson_id}").json()["segments"]
    if not segs:
        raise SystemExit(f"lesson {lesson_id} has no segments")
    return [(s["id"], files.clip_wav(lesson_id, s["idx"])) for s in segs]


def score_takes(client, takes: list[tuple[int, Path]], times: list[float]) -> None:
    for i in range(N_TAKES):
        seg_id, wav = takes[i % len(takes)]
        t0 = time.time()
        with wav.open("rb") as f:
            r = client.post(f"/segments/{seg_id}/attempts", files={"audio": (wav.name, f, "audio/wav")})
        r.raise_for_status()
        times.append(round(time.time() - t0, 2))


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--int8", action="store_true")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--budget", action="store_true")
    ap.add_argument("--phases", default=",".join(PHASES))
    ap.add_argument("--hard-cap-mb", type=float, default=5000)
    a = ap.parse_args()
    phases = a.phases.split(",")
    if bad := [p for p in phases if p not in PHASES]:
        raise SystemExit(f"unknown phases {bad}; choose from {PHASES}")
    if not a.clip.is_file():
        raise SystemExit(f"no such clip: {a.clip}")

    import torch
    from fastapi.testclient import TestClient
    from shadow.config import load_settings
    from shadow.deps import build_deps
    from shadow.main import create_app

    torch.set_num_threads(a.threads)
    settings = load_settings()
    settings.data_dir = Path(tempfile.mkdtemp(prefix="cpu_budget_"))          # never the user's data
    settings.models.device = a.device
    if a.int8 and hasattr(settings.models, "int8"):
        settings.models.int8 = True

    sampler = Sampler(a.hard_cap_mb)
    sampler.start()
    seconds: dict[str, float] = {}
    take_times: list[float] = []

    t0 = time.time()
    app = create_app(settings, deps=build_deps(settings))
    with TestClient(app) as client:
        client.get("/health").raise_for_status()
        seconds["startup"] = time.time() - t0
        files = app.state.files
        takes: list[tuple[int, Path]] = []
        if any(p in phases for p in ("build", "practice", "build+practice")):
            t0 = time.time(); sampler.phase = "build"      # practice needs a lesson, so one is built even if "build" is skipped
            made = upload(client, a.clip, "bench 1")
            wait_job(client, made["job_id"])
            seconds["build"] = time.time() - t0
            takes = take_audio(client, files, made["lesson_id"])
        if "practice" in phases:
            t0 = time.time(); sampler.phase = "practice"
            score_takes(client, takes, take_times)
            seconds["practice"] = time.time() - t0
        if "build+practice" in phases:
            t0 = time.time(); sampler.phase = "build+practice"
            made = upload(client, a.clip, "bench 2")
            score_takes(client, takes, take_times)
            wait_job(client, made["job_id"])
            seconds["build+practice"] = time.time() - t0
    sampler.halt.set(); sampler.join()

    out = [{"name": n, "seconds": round(seconds[n], 1), "peak_mb": round(sampler.peaks.get(n, 0.0))}
           for n in PHASES if n in phases and n in seconds]
    print(json.dumps({"phases": out, "take_seconds": take_times}))
    if a.budget and any(p["peak_mb"] > BUDGET_MB[p["name"]] for p in out):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
