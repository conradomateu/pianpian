"""The local server: pages, the library API and the guard on writes, on a throwaway library."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

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
        # Playback and seeking read only the requested bytes, including a tail range.
        for byte_range, expected, content_range in (("bytes=0-3", b"not ", "bytes 0-3/18"),
                                                    ("bytes=-5", b"video", "bytes 13-17/18")):
            req = urllib.request.Request(base + "/library/clip.mp4", headers={"Range": byte_range})
            with urllib.request.urlopen(req) as response:
                assert response.status == 206
                assert response.headers["Accept-Ranges"] == "bytes"
                assert response.headers["Content-Range"] == content_range
                assert int(response.headers["Content-Length"]) == len(expected)
                assert response.read() == expected
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
    finally:
        srv.shutdown()


def test_library_poster_and_thumbnail(tmp_path, monkeypatch):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe required")
    monkeypatch.setattr(server.engine, "ffmpeg", lambda: ffmpeg)
    clip = tmp_path / "clip"
    clip.mkdir()
    shutil.copy(Path(__file__).resolve().parents[1] / "demo/library/pianpian-day/source.mp4", clip)
    srv = server.start(0, library=tmp_path)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/library/clip/"
    try:
        for name, dimensions in (("thumb", "480x270"), ("poster", "1280x720")):
            image = clip / f"{name}.jpg"
            with urllib.request.urlopen(base + image.name) as response:
                assert response.headers["Content-Type"] == "image/jpeg"
                assert response.read() == image.read_bytes()
            actual = subprocess.check_output([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                              "stream=width,height", "-of", "csv=s=x:p=0", str(image)], text=True)
            assert actual.strip() == dimensions
        # Reusing either image must not regenerate it or overwrite the other size.
        before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in clip.glob("*.jpg")}
        for image, (_, content) in before.items():
            with urllib.request.urlopen(base + image.name) as response:
                assert response.read() == content
        assert before == {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in before}
    finally:
        srv.shutdown()
