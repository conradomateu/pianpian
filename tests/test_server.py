"""The local server: pages, the library API and the guard on writes, on a throwaway library."""
import json
import ntpath
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path, PureWindowsPath

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


def test_windows_drive_paths_cannot_escape_app_or_library(tmp_path, monkeypatch):
    # Windows joins, mapped onto scratch files so the actual HTTP boundary is tested on every OS.
    class WindowsFiles(PureWindowsPath):
        def local(self):
            path = PureWindowsPath(ntpath.normpath(str(self)))
            return tmp_path / path.drive.rstrip(":").lower() / Path(*path.parts[1:])

        def exists(self): return self.local().exists()
        def is_file(self): return self.local().is_file()
        def is_dir(self): return self.local().is_dir()
        def stat(self): return self.local().stat()
        def open(self, *a, **kw): return self.local().open(*a, **kw)
        def write_text(self, *a, **kw): return self.local().write_text(*a, **kw)
        def unlink(self, *a, **kw): return self.local().unlink(*a, **kw)

    (tmp_path / "c/app").mkdir(parents=True)
    (tmp_path / "d/outside").mkdir(parents=True)
    (tmp_path / "c/app/public.md").write_text("public")
    (tmp_path / "c/private.md").write_text("private")
    (tmp_path / "d/private.md").write_text("private")
    outside = tmp_path / "d/outside/en.lines.txt"
    outside.write_text("1\tORIGINAL\n")
    monkeypatch.setattr(server, "Path", WindowsFiles)
    monkeypatch.setattr(server.engine, "WINDOWS", True)
    monkeypatch.setattr(server, "HERE", WindowsFiles("C:/app"))
    monkeypatch.setitem(server.CFG, "library", WindowsFiles("C:/library"))
    calls = []
    monkeypatch.setattr(server, "rebuild_job", lambda *a, **kw: calls.append(a))
    srv = server.LocalServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        assert urllib.request.urlopen(base + "/public.md").read() == b"public"
        for path in ("/D:private.md", "/assets/C:../C:../private.md", "/assets/D:private.md"):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + path)
            assert error.value.code == 404
        req = urllib.request.Request(base + "/api/videos/D%3Aoutside/english", data=b'{"text":"1\\tREPLACED"}',
                                     headers={"X-Kit": "1"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)
        assert error.value.code == 404 and outside.read_text() == "1\tORIGINAL\n" and not calls
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.skipif(sys.platform == "win32", reason="colons are valid filenames on macOS, not Windows")
def test_mac_library_names_with_colons_remain_accessible(tmp_path, monkeypatch):
    monkeypatch.setattr(server.engine, "WINDOWS", False)
    monkeypatch.setitem(server.CFG, "library", tmp_path)
    clip = tmp_path / "Lesson: 1_study"
    clip.mkdir()
    (clip / "source.mp4").write_bytes(b"video")
    srv = server.LocalServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_port}"
        info = json.load(urllib.request.urlopen(base + "/api/videos/Lesson%3A%201_study"))
        assert info["id"] == clip.name and info["video"] == "source.mp4"
    finally:
        srv.shutdown()
        srv.server_close()


def test_job_log_keeps_lines_whole_across_chunks(tmp_path):
    # a transcript line and a UTF-8 character cut across reads must stay one line, so redaction still drops it
    job = server.Job("t", [], str(tmp_path))
    data = "[00:00:03.000 --> 00:00:06.000]   私人会议内容\nRuntimeError: translation failed\n".encode()
    cut = data.index("私".encode()) + 1                         # inside the first character's three bytes
    for part in (data[:10], data[10:cut], data[cut:]):
        job.feed(part)
    job.feed(b"", final=True)
    assert job.log == ["[00:00:03.000 --> 00:00:06.000]   私人会议内容", "RuntimeError: translation failed"]
    assert server.report.redact("\n".join(job.log)) == "RuntimeError: translation failed"
    job.feed(b"no newline at the end")
    job.feed(b"", final=True)
    assert job.log[-1] == "no newline at the end"
