"""CPU memory benchmark: runs the real app on a fresh temporary data dir and reports peak RSS per phase.

    CUDA_VISIBLE_DEVICES="" uv run python scripts/cpu_budget.py --clip CLIP.wav --device cpu --threads 4 [--int8] [--budget]

CLIP is a 5-minute 16 kHz mono clip; make one from any lesson's source.wav with
    ffmpeg -i source.wav -t 300 -ar 16000 -ac 1 clip.wav
Always run with CUDA_VISIBLE_DEVICES="" so nothing lands on a GPU. Phases (default all): startup (app serves,
/health answers), build (upload the clip as a lesson), practice (8 scored takes, the lesson's own clips as audio),
build+practice (a second lesson builds while 8 more takes are scored). Prints one JSON line
{"phases": [{"name", "seconds", "peak_mb"}], "take_seconds": [...]}. --budget exits 1 when a phase peak is over its
budget (startup 3000 MB, practice 3100 MB, build/build+practice 3500 MB). RSS over --hard-cap-mb (default: the smaller of 5000 and the free memory minus 500) aborts the run
with exit 3: the script re-runs itself as a child and a parent watchdog polls the child tree's RSS every 0.05 s and
kills it over the cap, so a runaway run cannot make the kernel OOM-killer pick other processes."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

BUDGET_MB = {"startup": 3000, "build": 3500, "practice": 3100, "build+practice": 3500}
PHASES = list(BUDGET_MB)
N_TAKES = 8


def tree_rss_mb(proc: psutil.Process) -> float:
    total = 0
    for p in [proc, *proc.children(recursive=True)]:
        try:
            total += p.memory_info().rss
        except psutil.Error:
            pass
    return total / 1e6


def watch(cmd: list[str], cap_mb: float, phase_file: Path | None = None) -> int:
    """Runs cmd; kills its whole process tree and returns 3 as soon as the tree's RSS passes cap_mb, otherwise returns
    the child's exit code. It runs in the parent process so weight loading in the child can neither starve nor outrun it."""
    child = subprocess.Popen(cmd)
    proc = psutil.Process(child.pid)
    last = 0.0                      # peak seen
    while child.poll() is None:
        try:
            mb = tree_rss_mb(proc)
        except psutil.Error as e:
            print(f"watchdog: lost the child ({e!r})", file=sys.stderr, flush=True)
            break
        if mb > cap_mb:
            phase = phase_file.read_text().strip() if phase_file and phase_file.exists() else ""
            for p in [*proc.children(recursive=True), proc]:
                try:
                    p.kill()
                except psutil.Error:
                    pass
            child.wait()
            print(f"over hard cap: phase {phase or 'unknown'} RSS {mb:.0f} MB > {cap_mb:.0f} MB; aborted",
                  file=sys.stderr, flush=True)
            print(json.dumps({"aborted": True, "phase": phase or None, "rss_mb": round(mb)}), flush=True)
            return 3
        last = max(last, mb)
        time.sleep(0.05)
    code = child.wait()
    if code < 0:                         # killed by a signal (the kernel's OOM killer) before the cap tripped
        phase = phase_file.read_text().strip() if phase_file and phase_file.exists() else ""
        print(f"child died on signal {-code} in phase {phase or 'unknown'}; peak RSS seen {last:.0f} MB",
              file=sys.stderr, flush=True)
        return 128 - code
    return code


class Sampler(threading.Thread):
    """Samples this process tree's RSS every 0.1 s into the current phase's peak (child side). Setting `phase` also
    writes it to phase_file so the watchdog can say where an abort happened."""

    def __init__(self, phase_file: Path | None):
        super().__init__(daemon=True)
        self.proc, self.phase_file = psutil.Process(), phase_file
        self.peaks: dict[str, float] = {}
        self.halt = threading.Event()
        self.phase = "startup"

    @property
    def phase(self) -> str:
        return self._phase

    @phase.setter
    def phase(self, name: str) -> None:
        self._phase = name
        if self.phase_file:
            self.phase_file.write_text(name)

    def run(self) -> None:
        while not self.halt.wait(0.1):
            mb = tree_rss_mb(self.proc)
            self.peaks[self.phase] = max(self.peaks.get(self.phase, 0.0), mb)


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
    ap.add_argument("--hard-cap-mb", type=float, default=None)
    ap.add_argument("--_child", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if not a._child:                      # parent: the watchdog around a re-run of this script
        cap = a.hard_cap_mb if a.hard_cap_mb is not None else min(5000.0, psutil.virtual_memory().available / 1e6 - 500)
        print(f"hard cap: {cap:.0f} MB", flush=True)
        phase_file = Path(tempfile.mkdtemp(prefix="cpu_budget_phase_")) / "phase"
        os.environ["CPU_BUDGET_PHASE_FILE"] = str(phase_file)
        raise SystemExit(watch([sys.executable, os.path.abspath(__file__), *sys.argv[1:], "--_child"],
                               cap, phase_file))
    phases = a.phases.split(",")
    if bad := [p for p in phases if p not in PHASES]:
        raise SystemExit(f"unknown phases {bad}; choose from {PHASES}")
    if not a.clip.is_file():
        raise SystemExit(f"no such clip: {a.clip}")

    from shadow.memory import release_freed_memory_eagerly
    release_freed_memory_eagerly()          # the measured child, before any model loads (create_app repeats it)
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

    pf = os.environ.get("CPU_BUDGET_PHASE_FILE")
    sampler = Sampler(Path(pf) if pf else None)
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
