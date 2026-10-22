from __future__ import annotations
import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from typing import AsyncIterator, Callable

from shadow.memory import trim_heap

log = logging.getLogger(__name__)

Progress = Callable[[str, float], None]

TERMINAL = ("done", "error")


@dataclass
class JobState:
    id: str
    stage: str = "queued"
    fraction: float = 0.0
    status: str = "queued"           # queued | running | done | error
    error: str | None = None
    lesson_id: int | None = None


class JobManager:
    """Runs submitted jobs one at a time on a worker thread; state lives on the event loop thread."""

    def __init__(self):
        self._jobs: dict[str, JobState] = {}
        self._subs: dict[str, list[asyncio.Queue]] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._worker = self._loop.create_task(self._run())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def get(self, job_id: str) -> JobState | None:
        return self._jobs.get(job_id)

    def submit(self, fn: Callable[[Progress], None], lesson_id: int | None) -> str:
        job_id = uuid.uuid4().hex[:12]
        self._jobs[job_id] = JobState(id=job_id, lesson_id=lesson_id)
        self._subs[job_id] = []
        self._queue.put_nowait((job_id, fn))
        return job_id

    def _publish(self, job_id: str) -> None:
        snap = asdict(self._jobs[job_id])
        for q in self._subs.get(job_id, []):
            q.put_nowait(snap)

    def _progress_cb(self, job_id: str) -> Progress:
        def cb(stage: str, fraction: float) -> None:
            def apply():
                st = self._jobs[job_id]
                if st.status in TERMINAL:
                    return
                st.stage, st.fraction, st.status = stage, fraction, "running"
                self._publish(job_id)
            assert self._loop is not None
            self._loop.call_soon_threadsafe(apply)
        return cb

    async def _run(self) -> None:
        while True:
            job_id, fn = await self._queue.get()
            st = self._jobs[job_id]
            st.status = "running"
            self._publish(job_id)
            try:
                await asyncio.get_running_loop().run_in_executor(self._pool, fn, self._progress_cb(job_id))
                st.status, st.stage, st.fraction = "done", "done", 1.0
            except Exception as e:  # noqa: BLE001
                log.exception("job %s failed", job_id)
                st.status, st.stage, st.error = "error", "error", str(e) or type(e).__name__
            finally:
                trim_heap()
            self._publish(job_id)

    async def events(self, job_id: str) -> AsyncIterator[dict]:
        """Current state, then every change, ending after `done` or `error`."""
        q: asyncio.Queue = asyncio.Queue()
        self._subs[job_id].append(q)
        try:
            yield asdict(self._jobs[job_id])
            if self._jobs[job_id].status in TERMINAL:
                return
            while True:
                snap = await q.get()
                yield snap
                if snap["status"] in TERMINAL:
                    return
        finally:
            self._subs[job_id].remove(q)
