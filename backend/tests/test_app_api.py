import pytest
from shadow.api import app as app_api


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(app_api, "_cache", None)
    monkeypatch.setattr(app_api, "current_version", lambda: "1.2.3")


def _release(monkeypatch, tag, url="https://example.test/r"):
    calls = []

    def fake(api_url):
        calls.append(api_url)
        return {"tag_name": tag, "html_url": url}
    monkeypatch.setattr(app_api, "fetch_release", fake)
    return calls


def test_newer(client, monkeypatch):
    _release(monkeypatch, "v1.10.0")
    assert client.get("/app/update").json() == {"current": "1.2.3", "latest": "1.10.0",
                                                "url": "https://example.test/r", "newer": True}


def test_same_and_older(client, monkeypatch):
    _release(monkeypatch, "1.2.3")
    assert client.get("/app/update").json()["newer"] is False
    monkeypatch.setattr(app_api, "_cache", None)
    _release(monkeypatch, "v1.2.0")
    r = client.get("/app/update").json()
    assert r["newer"] is False and r["latest"] == "1.2.0"


def test_network_error(client, monkeypatch):
    def boom(api_url):
        raise OSError("offline")
    monkeypatch.setattr(app_api, "fetch_release", boom)
    assert client.get("/app/update").json() == {"current": "1.2.3", "latest": None, "url": None, "newer": False}


@pytest.mark.parametrize("tag", ["nightly", "v1.2", "v1.x.3", "", None])
def test_malformed_tag(client, monkeypatch, tag):
    _release(monkeypatch, tag)
    assert client.get("/app/update").json() == {"current": "1.2.3", "latest": None, "url": None, "newer": False}


def test_cache_prevents_second_fetch_within_a_day(client, monkeypatch):
    calls = _release(monkeypatch, "v2.0.0")
    client.get("/app/update"); client.get("/app/update")
    assert len(calls) == 1
    t = app_api._cache[0]
    monkeypatch.setattr(app_api.time, "monotonic", lambda: t + 24 * 3600 + 1)
    client.get("/app/update")
    assert len(calls) == 2
