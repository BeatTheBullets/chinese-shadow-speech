import importlib.util
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("bootstrap", Path(__file__).with_name("bootstrap.py"))
bs = importlib.util.module_from_spec(SPEC)
sys.modules["bootstrap"] = bs
SPEC.loader.exec_module(bs)


@pytest.fixture(autouse=True)
def plenty_of_disk(monkeypatch):
    monkeypatch.setattr(bs, "free_gb", lambda p: 100.0)


def fake_runner(calls, sync_ok=True, prepare_lines=None):
    def run(cmd, env, on_line=None, cwd=None):
        calls.append(cmd)
        if "sync" in cmd:
            return 0 if sync_ok else 1
        if "prepare" in cmd:
            for line in prepare_lines or ['{"step": "recogniser", "done": 1, "total": 1}']:
                on_line(line)
            return 0
        return 0
    return run


def app_dir(tmp_path):
    a = tmp_path / "app"
    (a / "backend").mkdir(parents=True, exist_ok=True)
    (a / "backend" / "uv.lock").write_text("lock")
    return a


def serve_health():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_paths_with_space_and_umlaut(tmp_path):
    home = tmp_path / "Jöhn Doe" / "chinese-shadow-speech"
    assert bs.setup_needed(home, "abc")
    m = bs.ready_marker(home, "abc")
    m.parent.mkdir(parents=True)
    m.write_text("ok")
    assert not bs.setup_needed(home, "abc")
    lock = bs.SetupLock(home)
    assert lock.acquire()
    assert bs.setup_running(home)
    lock.release()
    assert not bs.setup_running(home)
    assert bs.running_port(home) is None
    cfg = bs.ensure_laptop_config(home)
    import tomllib
    assert tomllib.loads(cfg.read_text(encoding="utf-8"))["data_dir"].endswith("Jöhn Doe/chinese-shadow-speech/data")


def test_port_fallback_and_port_file(tmp_path):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    taken = s.getsockname()[1]
    try:
        assert bs.choose_port(taken) != taken
    finally:
        s.close()
    home = tmp_path / "h"
    (home / "run").mkdir(parents=True)
    srv = serve_health()
    try:
        p = srv.server_address[1]
        (home / "run" / "port").write_text(str(p))
        assert bs.running_port(home) == p
    finally:
        srv.shutdown()
        srv.server_close()
    assert bs.running_port(home) is None            # file there, nobody answers


def test_second_start_during_setup_opens_progress(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(bs, "home_dir", lambda: home)
    monkeypatch.setattr(bs, "default_app_dir", lambda: app_dir(tmp_path))
    opened, ran = [], []
    monkeypatch.setattr(bs, "open_browser", opened.append)
    monkeypatch.setattr(bs, "run_setup", lambda *a: ran.append(a) or True)
    (home / "run").mkdir(parents=True)
    bs.setup_port_file(home).write_text("47999")
    lock = bs.SetupLock(home)
    assert lock.acquire()
    try:
        assert bs.main() == 0
    finally:
        lock.release()
    assert opened == ["http://127.0.0.1:47999/"]
    assert ran == []


def test_failed_setup_is_not_marked_ready(tmp_path, monkeypatch):
    home, app = tmp_path / "home", app_dir(tmp_path)
    reports, calls = [], []
    monkeypatch.setattr(bs, "_run", fake_runner(calls, sync_ok=False))
    assert bs.run_setup(home, app, reports.append) is False
    assert "error" in reports[-1]
    assert bs.setup_needed(home, bs.lock_hash(app))
    monkeypatch.setattr(bs, "_run", fake_runner(calls))
    assert bs.run_setup(home, app, reports.append) is True
    assert not bs.setup_needed(home, bs.lock_hash(app))
    stages = [r.get("stage") for r in reports]
    assert "Setting up Python" in stages and "Downloading speech models (about 4 GB)" in stages
    assert "Preparing models" in stages
    sync = next(c for c in calls if "sync" in c)
    assert "--extra" in sync and "desktop" in sync


def test_prepare_error_line_fails_setup(tmp_path, monkeypatch):
    home, app = tmp_path / "home", app_dir(tmp_path)
    reports = []
    monkeypatch.setattr(bs, "_run", fake_runner([], prepare_lines=['{"error": "recogniser: boom"}']))
    assert bs.run_setup(home, app, reports.append) is False
    assert reports[-1] == {"error": "recogniser: boom"}
    assert bs.setup_needed(home, bs.lock_hash(app))


def test_disk_check_reports_shortfall(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "free_gb", lambda p: 3.0)
    calls, reports = [], []
    monkeypatch.setattr(bs, "_run", fake_runner(calls))
    assert bs.run_setup(tmp_path / "home", app_dir(tmp_path), reports.append) is False
    assert reports[-1] == {"error": "Not enough disk space: 3 GB free, about 8 GB needed"}
    assert calls == []


def test_ytdlp_update_once_a_day(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bs, "_run", fake_runner(calls))
    home = tmp_path / "home"
    bs.update_ytdlp(home, tmp_path)
    bs.update_ytdlp(home, tmp_path)
    assert len(calls) == 1 and "yt-dlp" in calls[0]
    for m in (home / "run").glob("ytdlp-*"):
        m.unlink()
    monkeypatch.setattr(bs, "_run", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    bs.update_ytdlp(home, tmp_path)                 # errors swallowed


def test_progress_server_status_and_retry():
    import urllib.request
    p = bs.Progress()
    port = bs.choose_port(0)
    srv = bs.make_progress_server(p, port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        p.report({"error": "x"})
        base = f"http://127.0.0.1:{port}"
        assert json.load(urllib.request.urlopen(base + "/status")) == {"error": "x"}
        assert b"Retry" in urllib.request.urlopen(base + "/").read()
        urllib.request.urlopen(urllib.request.Request(base + "/retry", method="POST"))
        assert p.retry.is_set()
    finally:
        srv.shutdown()
        srv.server_close()


def test_mapping_matches_shadow_laptop(tmp_path):
    from shadow import laptop
    home = tmp_path / "Jöhn Doe" / "h"
    assert bs.model_env(home) == laptop.model_env(home)
    assert bs.laptop_config_text(home) == laptop.laptop_config_text(home)
