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
    monkeypatch.setattr(bs, "_online", lambda: True)
    monkeypatch.setattr(bs, "LAUNCH_WAIT", 1)


def fake_runner(calls, sync_ok=True, prepare_lines=None):
    def run(cmd, env, on_line=None, cwd=None, timeout=None):
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
    (a / "backend" / "pyproject.toml").write_text('[project]\nname = "shadow"\nversion = "0.2.0"\n', encoding="utf-8")
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
    assert len(calls) == 1 and "yt-dlp[default]" in calls[0] and "yt-dlp-ejs" in calls[0]
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


def test_network_failure_gets_plain_message(tmp_path, monkeypatch):
    reports = []

    def run(cmd, env, on_line=None, cwd=None, timeout=None):
        on_line("error: Failed to fetch: dns error: failed to lookup address information")
        return 1
    monkeypatch.setattr(bs, "_run", run)
    assert bs.run_setup(tmp_path / "home", app_dir(tmp_path), reports.append) is False
    assert reports[-1] == {"error": bs.NO_INTERNET}


def test_port_file_under_umlaut_path(tmp_path):
    home = tmp_path / "Jöhn Doe" / "h"
    (home / "run").mkdir(parents=True)
    srv = serve_health()
    try:
        (home / "run" / "port").write_text(str(srv.server_address[1]), encoding="utf-8")
        assert bs.running_port(home) == srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def test_start_launcher_env_and_flags(tmp_path, monkeypatch):
    seen = {}

    class P:
        def __init__(self, cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
    monkeypatch.setattr(bs.subprocess, "Popen", P)
    home, app = tmp_path / "Jöhn" / "h", tmp_path / "app"
    bs.start_launcher(home, app, 4242, no_browser=True)
    env = seen["kw"]["env"]
    assert env["SHADOW_ICON"] == str(app / "icon.ico")
    assert env["SHADOW_FRONTEND_DIST"] == str(app / "frontend" / "dist")
    assert env["PATH"].startswith(str(app / "tools"))
    assert env["PYTHONUTF8"] == "1" and env["PYTHONPYCACHEPREFIX"] == str(home / "pycache")
    assert env["SHADOW_CONFIG"] == str(home / "config.toml")
    assert seen["cmd"][-3:] == ["--home", str(home), "--no-browser"]
    assert "--port" in seen["cmd"] and "4242" in seen["cmd"]


def patch_main(tmp_path, monkeypatch):
    home = tmp_path / "Jöhn Doe" / "home"
    monkeypatch.setattr(bs, "home_dir", lambda: home)
    monkeypatch.setattr(bs, "default_app_dir", lambda: app_dir(tmp_path))
    monkeypatch.setattr(bs, "open_browser", lambda url: None)
    monkeypatch.setattr(bs, "update_ytdlp", lambda *a: None)
    return home


def test_main_first_run_retry_keeps_lock_then_launches(tmp_path, monkeypatch):
    import time
    import urllib.request
    home = patch_main(tmp_path, monkeypatch)
    port = bs.choose_port(0)
    monkeypatch.setattr(bs, "choose_port", lambda *a: port)
    sync_results = iter([False, True])
    state = {"launched": None}

    def run(cmd, env, on_line=None, cwd=None, timeout=None):
        if "sync" in cmd:
            return 0 if next(sync_results) else 1
        on_line('{"step": "recogniser", "done": 1, "total": 1}')
        return 0
    monkeypatch.setattr(bs, "_run", run)

    def launcher(h, a, p, no_browser=False):
        state["launched"] = (p, no_browser)
        return type("P", (), {"kill": lambda self: None})()
    monkeypatch.setattr(bs, "start_launcher", launcher)
    monkeypatch.setattr(bs, "running_port", lambda h: 4321 if state["launched"] else None)

    result = []
    t = threading.Thread(target=lambda: result.append(bs.main()))
    t.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if "error" in json.load(urllib.request.urlopen(base + "/status")):
                break
        except OSError:
            pass
        time.sleep(0.05)
    else:
        pytest.fail("no error status")
    assert bs.setup_running(home)                   # still locked while waiting for Retry
    urllib.request.urlopen(urllib.request.Request(base + "/retry", method="POST"))
    t.join(10)
    assert result == [0]
    assert state["launched"] == (port, True)
    assert not bs.setup_running(home)


def test_second_instance_during_start_waits_for_app(tmp_path, monkeypatch):
    home = patch_main(tmp_path, monkeypatch)
    opened, answers = [], iter([None, None, None, 4321])
    monkeypatch.setattr(bs, "open_browser", opened.append)
    monkeypatch.setattr(bs, "running_port", lambda h: next(answers, 4321))
    monkeypatch.setattr(bs, "start_launcher", lambda *a, **k: pytest.fail("second launcher"))
    monkeypatch.setattr(bs.time, "sleep", lambda s: None)
    monkeypatch.setattr(bs, "LAUNCH_WAIT", 60)
    lock = bs.SetupLock(home)
    assert lock.acquire()
    try:
        assert bs.main() == 0
    finally:
        lock.release()
    assert opened == ["http://127.0.0.1:4321/"]


def test_installer_starts_bootstrap_without_writing_bytecode():
    # the shipped Python already carries its stdlib .pyc files (they are in the install log); -B keeps the bootstrap,
    # which runs before PYTHONPYCACHEPREFIX applies, from adding unlogged ones to the install folder
    iss = (Path(__file__).parent / "shadow.iss").read_text(encoding="utf-8")
    launches = [line for line in iss.splitlines() if "pythonw.exe" in line and "bootstrap.py" in line]
    assert len(launches) == 3
    assert all('Parameters: "-B ""{app}\\bootstrap.py"""' in line for line in launches)


def test_a_new_app_version_reruns_setup_with_the_same_lock(tmp_path, monkeypatch):
    # stored int8 copies are keyed by the app's quantisation format, which can change without uv.lock changing:
    # every new version must run prepare again so they are rebuilt here, not during the first take
    home, app = tmp_path / "home", app_dir(tmp_path)
    monkeypatch.setattr(bs, "_run", fake_runner([]))
    assert bs.run_setup(home, app, lambda r: None) is True
    assert not bs.setup_needed(home, bs.lock_hash(app))
    pyproject = app / "backend" / "pyproject.toml"
    pyproject.write_text(pyproject.read_text(encoding="utf-8").replace('version = "0.2.0"', 'version = "0.2.1"'),
                         encoding="utf-8")
    assert bs.setup_needed(home, bs.lock_hash(app))


def test_first_setup_means_no_ready_marker_and_no_models(tmp_path):
    home = tmp_path / "home"
    assert bs.first_setup(home)
    (home / "models" / "hf").mkdir(parents=True)
    assert bs.first_setup(home)                     # an empty models tree holds nothing to keep
    (home / "models" / "hf" / "weights.bin").write_bytes(b"x")
    assert not bs.first_setup(home)
    other = tmp_path / "other"
    bs.ready_marker(other, "oldlock").parent.mkdir(parents=True)
    bs.ready_marker(other, "oldlock").write_text("ok")
    assert not bs.first_setup(other)                # set up before, by an older version


def test_disk_check_on_a_re_setup_needs_only_a_little_space(tmp_path, monkeypatch):
    # every new app version reruns setup; the models are already there, so asking for 8 GB would block the upgrade
    home, app = tmp_path / "home", app_dir(tmp_path)
    bs.ready_marker(home, "oldlock").parent.mkdir(parents=True)
    bs.ready_marker(home, "oldlock").write_text("ok")
    monkeypatch.setattr(bs, "free_gb", lambda p: 3.0)
    monkeypatch.setattr(bs, "_run", fake_runner([]))
    assert bs.run_setup(home, app, lambda r: None) is True
    monkeypatch.setattr(bs, "free_gb", lambda p: 1.0)
    reports = []
    assert bs.run_setup(home, app, reports.append) is False
    assert reports[-1] == {"error": f"Not enough disk space: 1 GB free, about {bs.UPDATE_NEEDED_GB} GB needed"}
