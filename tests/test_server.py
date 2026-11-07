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


def test_host_header_and_cross_origin_status(tmp_path, monkeypatch):
    # DNS rebinding: only this server's own Host is served; other sites see that the app runs, not the library path
    import http.client
    monkeypatch.setitem(server.CFG, "library", tmp_path)
    srv = server.LocalServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_port

    def get(path, method="GET", **headers):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.putrequest(method, path, skip_host=True)
        for k, v in headers.items():
            c.putheader(k.replace("_", "-"), v)
        c.endheaders()
        r = c.getresponse()
        return r.status, r.headers, r.read()

    try:
        for host in ("rebind.attacker.example:%d" % port, "127.0.0.1", "127.0.0.1:1", "evil.localhost:%d" % port):
            assert get("/api/videos", Host=host)[0] == 403, host
        assert get("/api/videos", "POST", Host="rebind.example:%d" % port, X_Kit="1", Content_Length="0")[0] == 403
        assert get("/api/videos")[0] == 403                     # no Host at all
        for host in (f"127.0.0.1:{port}", f"LOCALHOST:{port}"):
            assert get("/api/videos", Host=host)[0] == 200, host
        full = json.loads(get("/api/status", Host=f"127.0.0.1:{port}")[2])
        assert full["library"] == str(tmp_path)
        same = get("/api/status", Host=f"localhost:{port}", Origin=f"http://localhost:{port}")
        assert json.loads(same[2])["library"] == str(tmp_path) and "Access-Control-Allow-Origin" not in same[1]
        for origin in ("https://pianpian.app", "null"):
            status, headers, body = get("/api/status", Host=f"127.0.0.1:{port}", Origin=origin)
            assert status == 200 and headers["Access-Control-Allow-Origin"] == "*"
            assert json.loads(body) == {"ok": True, "version": server.VERSION}, origin
    finally:
        srv.shutdown()
        srv.server_close()


def test_links_in_the_library_do_not_lead_out_of_it(tmp_path, monkeypatch):
    lib, outside = tmp_path / "lib", tmp_path / "outside"
    (lib / "vid").mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (lib / "vid" / "zh.srt").write_text("1\n")
    (lib / "vid" / "link.srt").symlink_to(outside / "secret.txt")
    (lib / "vid" / "thumb.jpg").symlink_to(outside / "secret.txt")
    (lib / "vid" / "poster.jpg").symlink_to(outside / "new.jpg")       # dangling: ffmpeg must not write through it
    (lib / "linkdir").symlink_to(outside, target_is_directory=True)
    monkeypatch.setitem(server.CFG, "library", lib)
    monkeypatch.setattr(server.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("ffmpeg ran")))
    srv = server.LocalServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        assert urllib.request.urlopen(base + "/library/vid/zh.srt").read() == b"1\n"
        for path in ("/library/vid/link.srt", "/library/vid/thumb.jpg", "/library/vid/poster.jpg",
                     "/library/linkdir/secret.txt", "/api/videos/linkdir"):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + path)
            assert error.value.code == 404, path
        assert [v["id"] for v in json.load(urllib.request.urlopen(base + "/api/videos"))] == ["vid"]
        assert not (outside / "new.jpg").exists()
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("name", ["CON", "nul.mp4", "Com1.srt", "lpt9", "AUX .txt", "CONIN$", "x.mp4.", "zh.srt "])
def test_windows_device_names_are_not_safe(monkeypatch, name):
    monkeypatch.setattr(server.engine, "WINDOWS", True)
    assert not server.safe_name(name)
    monkeypatch.setattr(server.engine, "WINDOWS", False)
    assert server.safe_name(name) == (not name.startswith(".")), "macOS keeps every one of these names"


def test_windows_names_that_only_look_like_devices_are_safe(monkeypatch):
    monkeypatch.setattr(server.engine, "WINDOWS", True)
    for name in ("CONSOLE.mp4", "COM10.srt", "nullable", "lpt.txt", "zh.srt", "con_study"):
        assert server.safe_name(name), name


def test_an_os_error_on_a_path_answers_instead_of_dropping_the_connection(tmp_path, monkeypatch):
    monkeypatch.setitem(server.CFG, "library", tmp_path)

    def refused(vid_id):
        raise OSError(22, "Invalid argument", vid_id)
    monkeypatch.setattr(server, "entry_path", refused)
    srv = server.LocalServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        for req, code in ((base + "/api/videos/x", 404), (base + "/library/x/zh.srt", 404),
                          (urllib.request.Request(base + "/api/videos/x/rebuild", data=b"{}", headers={"X-Kit": "1"}), 400),
                          (urllib.request.Request(base + "/api/add", data=b"{bad", headers={"X-Kit": "1"}), 400)):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(req)
            assert error.value.code == code
    finally:
        srv.shutdown()
        srv.server_close()
