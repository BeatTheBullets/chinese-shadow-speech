import json
from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from shadow.schemas import JobOut

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, request: Request):
    st = request.app.state.jobs.get(job_id)
    if st is None:
        raise HTTPException(404, "job not found")
    return JobOut(**asdict(st))


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    jobs = request.app.state.jobs
    if jobs.get(job_id) is None:
        raise HTTPException(404, "job not found")

    async def gen():
        async for snap in jobs.events(job_id):
            yield {"event": "progress", "data": json.dumps(snap)}
    return EventSourceResponse(gen())
