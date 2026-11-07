from fastapi.testclient import TestClient
from shadow.main import create_app
from shadow.config import Settings


def test_health(data_dir):
    app = create_app(Settings(data_dir=data_dir))
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["device"] in {"cpu", "cuda"}
    assert set(body["models_loaded"]) <= {"tone"}   # the committed tone model loads at start-up
    assert "versions" in body


def _spa_client(data_dir, dist, monkeypatch):
    monkeypatch.setenv("SHADOW_FRONTEND_DIST", str(dist))
    from shadow.deps import fake_deps
    from shadow.ingest.transcript import Transcript
    s = Settings(data_dir=data_dir)
    return TestClient(create_app(s, deps=fake_deps(s, Transcript())))


def test_spa_fallback_when_dist_exists(data_dir, tmp_path, monkeypatch):
    dist = tmp_path / "dist"; dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>")
    c = _spa_client(data_dir, dist, monkeypatch)
    assert c.get("/").text == "<html>spa</html>"
    assert c.get("/practice/12").text == "<html>spa</html>"
    assert c.get("/health").status_code == 200


def test_spa_serves_stats_pages(data_dir, tmp_path, monkeypatch):
    dist = tmp_path / "dist"; dist.mkdir(); (dist / "index.html").write_text("<html>spa</html>")
    c = _spa_client(data_dir, dist, monkeypatch)
    for p in ("/stats", "/stats/characters", "/stats/tones", "/stats/sounds", "/stats/sentences", "/stats/activity", "/stats/drills"):
        assert c.get(p).text == "<html>spa</html>", p
    assert c.get("/api/stats/tones").json()["tones"] == []


def test_spa_serves_real_files_and_assets(data_dir, tmp_path, monkeypatch):
    dist = tmp_path / "dist"; (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "favicon.svg").write_text("<svg/>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    c = _spa_client(data_dir, dist, monkeypatch)
    assert c.get("/favicon.svg").text == "<svg/>"
    assert c.get("/assets/app.js").text == "console.log(1)"


def test_spa_not_mounted_without_dist(data_dir, tmp_path, monkeypatch):
    c = _spa_client(data_dir, tmp_path / "missing", monkeypatch)
    assert c.get("/").status_code == 404


def test_spa_catch_all_never_serves_files_outside_dist(data_dir, tmp_path, monkeypatch):
    dist = tmp_path / "dist"; dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>")
    (tmp_path / "config.toml").write_text("SECRET=1")
    c = _spa_client(data_dir, dist, monkeypatch)
    secret = tmp_path / "config.toml"
    from urllib.parse import quote
    abs_posix = quote(secret.as_posix().lstrip("/"), safe="/:")  # "/C:/..." on Windows, "/tmp/..." elsewhere
    for path in ("/..%2fconfig.toml", "/..%2f..%2fconfig.toml", "/../config.toml",
                 "/../../config.toml", "/%2e%2e/config.toml", "/..%5cconfig.toml",
                 "/..%5c..%5cconfig.toml", "/%2e%2e%5cconfig.toml",
                 "/" + abs_posix, "/" + quote(str(secret), safe=""), "/" + quote(str(secret), safe=":\\")):
        r = c.get(path)
        assert "SECRET" not in r.text, path
        assert r.text == "<html>spa</html>", path


def test_health_reports_the_tone_model(client):
    tm = client.get("/health").json()["tone_model"]
    assert tm == {"loaded": True, "version": "fake", "accuracy": None}


def test_health_reports_sounds_error(client):
    assert client.get("/health").json()["sounds_error"] is None
    client.app.state.deps.sounds_error = "boom"
    assert client.get("/health").json()["sounds_error"] == "boom"


def test_a_failed_sounds_warm_up_switches_sounds_off():
    import threading
    from types import SimpleNamespace
    from shadow.main import watch_sounds_warm_up
    chars = SimpleNamespace(_model=None, load_error="download failed")
    deps = SimpleNamespace(sounds=SimpleNamespace(chars=chars), sounds_error=None)
    t = threading.Thread(target=lambda: None); t.start()
    watch_sounds_warm_up(deps, t)
    assert deps.sounds is None and deps.sounds_error == "download failed"
    ok = SimpleNamespace(sounds=SimpleNamespace(chars=SimpleNamespace(_model=object())), sounds_error=None)
    watch_sounds_warm_up(ok, t)
    assert ok.sounds is not None and ok.sounds_error is None


def test_foreign_host_header_is_refused(client):
    # DNS rebinding: a page on evil.example whose name now resolves to 127.0.0.1 reaches the fixed local port with
    # its own Host header; only the loopback names (any port) are served
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/health", headers={"Host": "evil.example:47231"}).status_code == 400
    for host in ("localhost:8000", "127.0.0.1:47231", "[::1]:47231", "localhost:5173", "127.0.0.1"):
        assert client.get("/health", headers={"Host": host}).status_code == 200, host


def test_allowed_hosts_come_from_the_server_settings(data_dir, fake_transcript):
    from shadow.deps import fake_deps
    from shadow.config import ServerCfg
    assert {"127.0.0.1", "localhost", "::1", "testserver"} <= set(ServerCfg().allowed_hosts)
    s = Settings(data_dir=data_dir, server=ServerCfg(allowed_hosts=["shadow.lan", "testserver"]))
    c = TestClient(create_app(s, deps=fake_deps(s, fake_transcript)))
    assert c.get("/health", headers={"Host": "shadow.lan:8000"}).status_code == 200
    assert c.get("/health", headers={"Host": "localhost:8000"}).status_code == 400


def test_spa_catch_all_leaves_unknown_api_paths_as_404(data_dir, tmp_path, monkeypatch):
    # a mistyped or removed API route must not come back as the app's HTML page with 200
    dist = tmp_path / "dist"; dist.mkdir(); (dist / "index.html").write_text("<html>spa</html>")
    c = _spa_client(data_dir, dist, monkeypatch)
    for p in ("/api/stats/syllables", "/api/nope", "/api"):
        assert c.get(p).status_code == 404, p
    assert c.get("/library").status_code == 200
