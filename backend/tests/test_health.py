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
