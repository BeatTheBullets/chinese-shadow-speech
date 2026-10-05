from tests.helpers import make_tone_wav
from tests.conftest import wait_job


def test_post_lesson_runs_job_and_streams_events(client, tmp_path):
    wav = make_tone_wav(tmp_path / "u.wav", 8.0)
    with open(wav, "rb") as f:
        r = client.post("/lessons", files={"file": ("u.wav", f, "audio/wav")}, data={"title": "Up", "speaker": "Me"})
    assert r.status_code == 202
    job_id, lesson_id = r.json()["job_id"], r.json()["lesson_id"]
    j = wait_job(client, job_id)
    assert j["status"] == "done" and j["lesson_id"] == lesson_id
    with client.stream("GET", f"/jobs/{job_id}/events") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert '"status": "done"' in body or '"status":"done"' in body


def test_unknown_job_404(client):
    assert client.get("/jobs/nope").status_code == 404


def test_failing_job_reports_error_and_ends_stream(client):
    def boom(progress):
        progress("transcribe", 0.5)
        raise RuntimeError("no speech found in the recording")

    job_id = client.app.state.jobs.submit(boom, None)
    j = wait_job(client, job_id)
    assert j["status"] == "error" and j["error"] == "no speech found in the recording"
    with client.stream("GET", f"/jobs/{job_id}/events") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "no speech found" in body


async def test_job_manager_events_stream_live_progress_until_done():
    # TestClient buffers whole responses, so live streaming is tested on JobManager directly
    import threading
    from shadow.jobs import JobManager
    gate = threading.Event()

    def job(progress):
        progress("align", 0.5)
        assert gate.wait(5)
        progress("enrich", 1.0)

    jm = JobManager()
    jm.start()
    job_id = jm.submit(job, 7)
    snaps = []
    async for snap in jm.events(job_id):
        snaps.append(snap)
        if snap["stage"] == "align":
            gate.set()                      # only now may the job continue
    await jm.stop()
    stages = [x["stage"] for x in snaps]
    assert "align" in stages and stages.index("align") < stages.index("enrich")
    assert snaps[-1]["status"] == "done" and snaps[-1]["lesson_id"] == 7
