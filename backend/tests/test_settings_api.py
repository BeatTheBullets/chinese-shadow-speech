import os
import stat

NETSCAPE = b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsecret\n"


def _put(client, content: bytes):
    return client.put("/settings/youtube-cookies", files={"file": ("cookies.txt", content, "text/plain")})


def test_youtube_cookies_round_trip(client):
    path = client.app.state.files.data_dir / "youtube-cookies.txt"
    assert client.get("/settings/youtube-cookies").json() == {"present": False}
    r = _put(client, NETSCAPE)
    assert r.status_code == 200 and r.json() == {"present": True}
    assert client.get("/settings/youtube-cookies").json() == {"present": True}
    assert path.read_bytes() == NETSCAPE
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []
    assert client.delete("/settings/youtube-cookies").status_code == 204
    assert client.get("/settings/youtube-cookies").json() == {"present": False}
    assert not path.exists()
    assert client.delete("/settings/youtube-cookies").status_code == 204        # removing nothing is fine


def test_accepts_the_other_header_after_blank_lines_and_a_bom(client):
    assert _put(client, b"\xef\xbb\xbf\n\r\n# HTTP Cookie File\n").status_code == 200


def test_rejects_a_file_that_is_not_a_cookies_file_and_keeps_the_old_one(client):
    path = client.app.state.files.data_dir / "youtube-cookies.txt"
    assert _put(client, b"<html>not cookies</html>\n").status_code == 400
    assert not path.exists()
    _put(client, NETSCAPE)
    assert _put(client, b"hello\n").status_code == 400
    assert _put(client, b"\xff\xfe\x00binary").status_code == 400
    assert path.read_bytes() == NETSCAPE
