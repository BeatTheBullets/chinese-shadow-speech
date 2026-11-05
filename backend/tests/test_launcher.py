import socket
from pathlib import Path

import httpx
from fastapi import FastAPI

from shadow import launcher


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}
    return app


def _closed(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def test_server_handle_starts_answers_and_stops():
    port = _free_port()
    h = launcher.ServerHandle(_app(), port)
    h.start()
    try:
        assert h.wait_ready(10) is True
        assert httpx.get(f"http://127.0.0.1:{port}/health").json() == {"ok": True}
    finally:
        h.stop()
    assert _closed(port)


def test_quit_stops_server(tmp_path: Path):
    port = _free_port()
    h = launcher.ServerHandle(_app(), port)
    h.start()
    assert h.wait_ready(10)
    launcher.write_port_file(tmp_path, port)
    assert (tmp_path / "run" / "port").read_text() == str(port)
    stopped = []
    launcher.make_quit(h, tmp_path, lambda: stopped.append(1))()
    assert _closed(port)
    assert not (tmp_path / "run" / "port").exists()
    assert stopped == [1]


def test_wait_ready_false_when_server_never_starts():
    h = launcher.ServerHandle(_app(), _free_port())
    assert h.wait_ready(0.3) is False


def test_ensure_streams_replaces_none(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    launcher.ensure_streams()
    print("x", file=sys.stderr)
    sys.stdout.write("y")
    from tqdm import tqdm
    for _ in tqdm(range(2)):
        pass


def test_stop_returns_with_open_sse_stream():
    import asyncio
    import threading
    import time
    from contextlib import asynccontextmanager
    from sse_starlette.sse import EventSourceResponse
    done = []

    @asynccontextmanager
    async def ls(app):
        yield
        done.append("shutdown")

    app = FastAPI(lifespan=ls)

    @app.get("/health")
    def health():
        return {}

    @app.get("/ev")
    async def ev():
        async def gen():
            while True:
                yield {"data": "x"}
                await asyncio.sleep(0.2)
        return EventSourceResponse(gen())

    port = _free_port()
    h = launcher.ServerHandle(app, port)
    h.start()
    assert h.wait_ready(10)

    def client():
        try:
            with httpx.stream("GET", f"http://127.0.0.1:{port}/ev", timeout=None) as r:
                for _ in r.iter_lines():
                    pass
        except Exception:
            pass
    threading.Thread(target=client, daemon=True).start()
    time.sleep(1)
    t0 = time.monotonic()
    h.stop()
    assert time.monotonic() - t0 < 8
    assert not h.thread.is_alive()
    assert done == ["shutdown"]


def test_wait_ready_false_fast_when_port_taken():
    import time
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        h = launcher.ServerHandle(_app(), port)
        h.start()
        t0 = time.monotonic()
        assert h.wait_ready(60) is False
        assert time.monotonic() - t0 < 10


def test_icon_falls_back_on_corrupt_ico(tmp_path, monkeypatch):
    bad = tmp_path / "icon.ico"
    bad.write_bytes(b"not an icon")
    monkeypatch.setenv("SHADOW_ICON", str(bad))
    img = launcher.load_icon_image()
    assert img.size == (64, 64)
