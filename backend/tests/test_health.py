from fastapi.testclient import TestClient
from shadow.main import create_app
from shadow.config import Settings


def test_health(data_dir):
    app = create_app(Settings(data_dir=data_dir))
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["device"] in {"cpu", "cuda"}
    assert body["models_loaded"] == []
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
    for path in ("/..%2fconfig.toml", "/..%2f..%2fconfig.toml", "/../config.toml",
                 "/../../config.toml", "/%2e%2e/config.toml", "/..%5cconfig.toml",
                 "//" + str(tmp_path / "config.toml").lstrip("/")):
        r = c.get(path)
        assert "SECRET" not in r.text, path
        assert r.text == "<html>spa</html>", path


def test_health_reports_the_tone_model(client):
    tm = client.get("/health").json()["tone_model"]
    assert tm == {"loaded": True, "version": "fake", "accuracy": None}
