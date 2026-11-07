"""The local server: pages, the library API and the guard on writes, on a throwaway library."""
import io
import json
import ntpath
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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


def test_stop_closes_http_worker_and_job_admission(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CLOSING", False)
    monkeypatch.setattr(server, "WORKER", None)
    monkeypatch.setattr(server, "QUEUE", type(server.QUEUE)())  # no workers from earlier server fixtures share this queue
    monkeypatch.setattr(server.engine, "CLOSING", False)
    srv = server.start(0, library=tmp_path)
    serving = threading.Thread(target=srv.serve_forever, daemon=True)
    serving.start()
    base = f"http://127.0.0.1:{srv.server_port}/api/status"
    assert urllib.request.urlopen(base).status == 200
    server.stop(srv)
    serving.join(timeout=5)
    assert not serving.is_alive() and not server.WORKER.is_alive() and server.CLOSING
    with pytest.raises(RuntimeError, match="closing"):
        server.enqueue(server.Job("too late", [sys.executable, "-c", "pass"], str(tmp_path)))
    with pytest.raises(OSError):
        urllib.request.urlopen(base, timeout=1)


def test_windows_status_never_probes_gpu(monkeypatch):
    monkeypatch.setattr(server.engine, "WINDOWS", True)
    monkeypatch.setattr(server.engine, "config", lambda: {})
    monkeypatch.setattr(server.engine.runtimes, "backend_for", lambda tool: (_ for _ in ()).throw(AssertionError("GPU probe ran")))
    handler = server.Handler.__new__(server.Handler)
    handler.path, handler.headers = "/api/status", {}
    handler.send_json = lambda body, status=200, **kwargs: setattr(handler, "response", (status, body))
    handler.do_GET()
    assert handler.response[0] == 200 and handler.response[1]["accel"] == "auto"


def test_windows_report_never_probes_gpu(tmp_path, monkeypatch):
    monkeypatch.setattr(server.engine, "WINDOWS", True)
    monkeypatch.setattr(server.engine.models, "status", lambda: [])
    monkeypatch.setattr(server.engine.runtimes, "backend_for", lambda tool: (_ for _ in ()).throw(AssertionError("GPU probe ran")))
    monkeypatch.setattr(server, "JOBS", [])
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path))
    monkeypatch.delenv("PIANPIAN_ACCEL", raising=False)
    result = server.problem_report({})
    assert "auto (GPU detected during setup)" in result["details"]


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
    (lib / "vid" / "zh.srt").write_bytes(b"1\n")
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


def test_setup_and_jobs_never_overlap(tmp_path, monkeypatch):
    (tmp_path / "vid").mkdir()
    (tmp_path / "vid" / "source.mp4").write_bytes(b"video")
    monkeypatch.setitem(server.CFG, "library", tmp_path)
    monkeypatch.setattr(server, "JOBS", [])
    monkeypatch.setattr(server, "QUEUE", server.queue.Queue())         # no worker: queued jobs stay queued
    started = []
    monkeypatch.setattr(server.engine.SETUP, "start", lambda *a, **kw: started.append(a))
    srv = server.LocalServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"

    def call(path, data=b"{}", method="POST"):
        req = urllib.request.Request(base + path, data=data, method=method, headers={"X-Kit": "1"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    try:
        assert call("/api/videos/vid/rebuild")[0] == 200
        code, body = call("/api/setup")
        assert code == 409 and "Rebuild" in body["error"] and not started
        server.JOBS[0].state = "done"
        monkeypatch.setattr(server.engine.SETUP, "state", "running")
        assert call("/api/setup")[0] == 200 and started
        server.CFG["library"] = tmp_path                                 # the fake setup saved no config to re-read
        for path in ("/api/videos/vid/rebuild", "/api/videos/vid/translate", "/api/update-downloader"):
            code, body = call(path)
            assert code == 409 and body["error"] == server.SETUP_RUNS, path
        assert call("/api/import?name=new.mp4", b"video", "PUT")[0] == 409
        assert not (tmp_path / "new.mp4").exists() and len(server.JOBS) == 1
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def anki_setup_requests(tmp_path, monkeypatch):
    """Real handlers and relocation; no sockets, package installation or Anki collection."""
    e = server.engine
    old, library = tmp_path / "old", tmp_path / "library"
    clip = library / "clip"
    clip.mkdir(parents=True)
    (clip / "source.mp4").write_bytes(b"source")
    (clip / "zh.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
    (clip / "zh.words.json").write_text('{"cues": []}')
    monkeypatch.setattr(e, "SUPPORT", old)
    monkeypatch.setattr(e, "CONFIG", old / "config.json")
    monkeypatch.setattr(e, "SETUP", e.Setup())
    monkeypatch.setattr(e, "STATE", {"engine": True, "current": True})
    monkeypatch.setattr(e, "PATH_OVERRIDES", dict.fromkeys(e.PATH_OVERRIDES))
    for key in e.PATH_OVERRIDES:
        monkeypatch.setenv(key, "")                            # restore setup's process-environment writes afterwards
    monkeypatch.setattr(e, "python", lambda: sys.executable)
    monkeypatch.setattr(e, "mirror_env", lambda: {})
    monkeypatch.setattr(e, "check", lambda: {"engine": True, "current": True})
    monkeypatch.setattr(e.models, "status", lambda: [])
    monkeypatch.setattr(e.runtimes, "status", lambda **kwargs: {"label": "runtime", "size": 0})
    monkeypatch.setattr(e.runtimes, "backend_for", lambda tool: "cpu")
    monkeypatch.setattr(e.Setup, "_exec", lambda *a: None)
    monkeypatch.setattr(server, "JOBS", [])
    monkeypatch.setattr(server, "ANKI_ACTIVE", 0)
    monkeypatch.setitem(server.CFG, "library", library)
    e.save_config(library=str(library))

    def call(path, data=None):
        handler = server.Handler.__new__(server.Handler)
        handler.path, handler.headers = path, {"X-Kit": "1"}
        if path == "/api/setup" and data is None:
            data = {"library": str(library), "data": str(tmp_path / "new"), "models": []}
        handler.body = lambda: data
        handler.send_json = lambda body, status=200: setattr(handler, "response", (status, body))
        handler.send_file = lambda path: setattr(handler, "response", (200, path.read_bytes()))
        if path.startswith(("/library/", "/api/anki/audio/")):
            handler.do_GET()
        else:
            handler.do_POST()
        return handler.response

    yield call
    if e.SETUP.thread:
        e.SETUP.thread.join(5)
        assert not e.SETUP.thread.is_alive()


def test_setup_cannot_move_an_active_preview(anki_setup_requests, tmp_path, monkeypatch):
    call, anki = anki_setup_requests, server.anki_export
    started, finish = threading.Event(), threading.Event()

    def render(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"mp3")
        started.set()
        assert finish.wait(5)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(anki, "duration", lambda path: 2)
    monkeypatch.setattr(anki, "_ffmpeg", lambda: "stub-ffmpeg")
    monkeypatch.setattr(anki.engine, "run", render)
    with ThreadPoolExecutor(2) as pool:
        preview = pool.submit(call, "/api/anki/preview", {
            "id": "clip", "start": 0, "end": 1, "selection": {"cueStart": 0, "cueEnd": 0},
        })
        try:
            assert started.wait(5)
            code, body = pool.submit(call, "/api/setup").result(timeout=2)
            assert code == 409 and "Anki" in body["error"]
            assert server.engine.data_dir() == tmp_path / "old"
        finally:
            finish.set()
        code, body = preview.result(timeout=5)
    assert code == 200 and server.ANKI_ACTIVE == 0
    name = body["url"].rsplit("/", 1)[1]
    assert (tmp_path / "old/cache/anki" / name).read_bytes() == b"mp3"
    assert call("/api/setup")[0] == 200
    server.engine.SETUP.thread.join(5)
    assert server.engine.SETUP.state == "done"
    assert (tmp_path / "new/cache/anki" / name).read_bytes() == b"mp3"


@pytest.mark.parametrize("action,path", [
    ("preview", "/api/anki/preview"), ("export", "/api/anki/export"),
    ("study_words", "/library/clip/zh.words.json"),
    ("audio_path", "/api/anki/audio/pianpian-" + "0" * 64 + ".mp3"),
])
def test_setup_and_anki_exclude_each_other(anki_setup_requests, tmp_path, monkeypatch, action, path):
    call = anki_setup_requests
    started, finish = threading.Event(), threading.Event()
    calls = []

    def work(*args):
        calls.append(args)
        started.set()
        assert finish.wait(5)
        return tmp_path / "library/clip/source.mp4" if action == "audio_path" else {}

    monkeypatch.setattr(server.anki_export, action, work)
    # Setup first: no operation reaches its engine/cache code.
    server.engine.SETUP.state = "running"
    assert call(path, {"id": "clip"}) == (409, {"error": server.SETUP_RUNS})
    assert not calls and server.ANKI_ACTIVE == 0
    server.engine.SETUP.state = "idle"
    # Anki first: setup returns promptly, without waiting for the operation.
    with ThreadPoolExecutor(2) as pool:
        operation = pool.submit(call, path, {"id": "clip"})
        try:
            assert started.wait(5)
            assert pool.submit(call, "/api/setup").result(timeout=2)[0] == 409
        finally:
            finish.set()
        assert operation.result(timeout=5)[0] == 200
    assert server.ANKI_ACTIVE == 0 and call("/api/setup")[0] == 200


@pytest.mark.parametrize("action,path,error,status", [
    ("preview", "/api/anki/preview", ValueError("extraction failed"), 400),
    ("preview", "/api/anki/preview", subprocess.TimeoutExpired("ffmpeg", 60), 503),
    ("export", "/api/anki/export", OSError("media unavailable"), 500),
    ("study_words", "/library/clip/zh.words.json", ValueError("bad words"), 404),
    ("audio_path", "/api/anki/audio/pianpian-" + "0" * 64 + ".mp3", FileNotFoundError("expired"), 404),
])
def test_anki_errors_release_setup_exclusion(anki_setup_requests, monkeypatch, action, path, error, status):
    def fail(*args):
        raise error
    monkeypatch.setattr(server.anki_export, action, fail)
    assert anki_setup_requests(path, {"id": "clip"})[0] == status
    assert server.ANKI_ACTIVE == 0
    assert anki_setup_requests("/api/setup")[0] == 200


@pytest.mark.parametrize("path", ["/api/anki/preview", "/api/anki/export"])
def test_anki_validation_releases_setup_exclusion(anki_setup_requests, path):
    assert anki_setup_requests(path, {})[0] == 400
    assert server.ANKI_ACTIVE == 0
    assert anki_setup_requests("/api/setup")[0] == 200


def test_setup_waits_for_every_admitted_anki_request(anki_setup_requests, monkeypatch):
    started = [threading.Event(), threading.Event()]
    finish = [threading.Event(), threading.Event()]

    def work(entry, library, data):
        index = data["index"]
        started[index].set()
        assert finish[index].wait(5)
        return {}

    monkeypatch.setattr(server.anki_export, "export", work)
    with ThreadPoolExecutor(3) as pool:
        operations = [pool.submit(anki_setup_requests, "/api/anki/export", {"id": "clip", "index": i}) for i in range(2)]
        try:
            assert all(event.wait(5) for event in started)
            finish[0].set()
            assert operations[0].result(timeout=5)[0] == 200
            assert pool.submit(anki_setup_requests, "/api/setup").result(timeout=2)[0] == 409
        finally:
            for event in finish:
                event.set()
        assert operations[1].result(timeout=5)[0] == 200
    assert server.ANKI_ACTIVE == 0
    assert anki_setup_requests("/api/setup")[0] == 200


def import_request(payload, reader=None, name="clip.mp4"):
    handler = server.Handler.__new__(server.Handler)
    handler.path = f"/api/import?name={name}"
    handler.headers = {"X-Kit": "1", "Content-Length": str(len(payload))}
    handler.rfile = reader or io.BytesIO(payload)
    handler.send_json = lambda body, status=200: setattr(handler, "response", (status, body))
    return handler


def fake_import_job(monkeypatch):
    names = []
    class FakeJob:
        kind = "add"
        def __init__(self, name):
            self.name = name
        def public(self):
            return {"name": self.name}
    monkeypatch.setattr(server, "rebuild_job", lambda name, **kwargs: names.append(name) or FakeJob(name))
    return names


@pytest.mark.parametrize("first,second,expected", [
    ("clip.mp4", "clip.mp4", "clip (2).mp4"),
    ("clip.mp4", "CLIP.mp4", "clip (2).mp4"),
    ("café.mp4", "cafe\u0301.mp4", "café (2).mp4"),
])
def test_concurrent_imports_reserve_distinct_destinations(tmp_path, monkeypatch, first, second, expected):
    monkeypatch.setitem(server.CFG, "library", tmp_path)
    monkeypatch.setattr(server, "IMPORTS_ACTIVE", 0)
    monkeypatch.setattr(server, "IMPORT_TARGETS", set())
    monkeypatch.setattr(server.engine.SETUP, "state", "idle")
    names = fake_import_job(monkeypatch)
    ready, lock, both = 0, threading.Lock(), threading.Event()

    class Reader(io.BytesIO):
        def read(self, size=-1):
            nonlocal ready
            with lock:
                ready += 1
                if ready == 2:
                    both.set()
            assert both.wait(5)
            return super().read(size)

    payloads = (b"AAAAAA", b"BBBBBB")
    requests = [import_request(payload, Reader(payload), name) for payload, name in zip(payloads, (first, second))]
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda h: h.do_PUT(), requests))
    assert [h.response[0] for h in requests] == [200, 200]
    key = lambda name: unicodedata.normalize("NFC", name.casefold())
    assert {key(name) for name in names} == {key(first), key(expected)}
    for h, payload in zip(requests, payloads):
        assert (tmp_path / h.response[1]["name"]).read_bytes() == payload
    assert not list(tmp_path.glob("*.part")) and server.IMPORTS_ACTIVE == 0 and not server.IMPORT_TARGETS


def test_setup_cannot_change_library_during_import(tmp_path, monkeypatch):
    monkeypatch.setitem(server.CFG, "library", tmp_path)
    monkeypatch.setattr(server, "IMPORTS_ACTIVE", 0)
    monkeypatch.setattr(server, "IMPORT_TARGETS", set())
    monkeypatch.setattr(server, "ANKI_ACTIVE", 0)
    monkeypatch.setattr(server, "JOBS", [])
    monkeypatch.setattr(server.engine.SETUP, "state", "idle")
    monkeypatch.setattr(server.engine, "config", lambda: {"library": str(tmp_path)})
    names = fake_import_job(monkeypatch)
    starts = []
    monkeypatch.setattr(server.engine.SETUP, "start", lambda *args, **kwargs: starts.append(args))

    def setup():
        handler = server.Handler.__new__(server.Handler)
        handler.path, handler.headers = "/api/setup", {"X-Kit": "1"}
        handler.body = lambda: {"library": str(tmp_path), "data": str(tmp_path), "models": []}
        handler.send_json = lambda body, status=200: setattr(handler, "response", (status, body))
        handler.do_POST()
        return handler.response

    class Reader(io.BytesIO):
        def read(self, size=-1):
            if not hasattr(self, "checked"):
                self.checked = setup()
            return super().read(size)

    request = import_request(b"video", Reader(b"video"))
    request.do_PUT()
    assert request.response[0] == 200 and request.rfile.checked[0] == 409
    assert names == ["clip.mp4"] and not starts
    assert setup()[0] == 200 and len(starts) == 1
    assert server.IMPORTS_ACTIVE == 0 and not server.IMPORT_TARGETS
