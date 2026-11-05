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
