"""The local server: pages, the library API and the guard on writes, on a throwaway library."""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PIANPIAN_HOME", tempfile.mkdtemp())   # logs and settings in a throwaway folder, not your ~/Library
os.environ["PIANPIAN_NO_UPDATE_CHECK"] = "1"                 # and no calls to GitHub from a test
import server  # noqa: E402


def test_server(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"not really a video")
    srv = server.start(0, library=tmp_path)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        status = json.load(urllib.request.urlopen(base + "/api/status"))
        assert status["ok"] and status["library"] == str(tmp_path.resolve())
        videos = json.load(urllib.request.urlopen(base + "/api/videos"))
        assert [v["id"] for v in videos] == ["clip.mp4"] and videos[0]["kind"] == "file"
        assert urllib.request.urlopen(base + "/app.html").status == 200
        # writes need the X-Kit header, so another web page can't trigger downloads
        req = urllib.request.Request(base + "/api/add", data=b"{}", method="POST")
        try:
            urllib.request.urlopen(req)
            raise AssertionError("POST without X-Kit was accepted")
        except urllib.error.HTTPError as e:
            assert e.code == 403
        # files outside the app folder and the library are not served, however the path is written
        for bad in ("/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/assets/../../server.py", "/.git/HEAD",
                    "/assets/%2e%2e/app.html", "/design//icons/x.svg"):
            try:
                urllib.request.urlopen(base + bad)
                raise AssertionError(f"{bad} was served")
            except urllib.error.HTTPError as e:
                assert e.code == 404, bad
        # a video folder with a Chinese name: the page sends encodeURIComponent(id), so POST must unquote it
        (tmp_path / "视频_study").mkdir()
        vid = "%E8%A7%86%E9%A2%91_study"
        req = urllib.request.Request(base + f"/api/videos/{vid}/rebuild", data=b"{}", method="POST", headers={"X-Kit": "1"})
        try:
            urllib.request.urlopen(req)
            raise AssertionError("rebuild of a folder with no source video was accepted")
        except urllib.error.HTTPError as e:
            assert e.code == 404 and "no source video in 视频_study" in e.read().decode(), "POST did not unquote the video id"
    finally:
        srv.shutdown()
