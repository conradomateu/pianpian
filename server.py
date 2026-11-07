#!/usr/bin/env python3
"""Pianpian local server. Python standard library only.

    python3 server.py                 # http://127.0.0.1:8770 · the library chosen in the setup · opens the browser
    python3 server.py --no-browser --library ~/Movies/other

Serves the pages in this folder and the videos in the library, and runs pipeline/study.py
(one job at a time) so the app can download a link, make subtitles and rebuild a video.
Everything it knows about a video lives in that video's folder (see PLAN.md), so the app and
the command line always agree. Listens on 127.0.0.1 only.
"""
import argparse
import codecs
import json
import logging
import mimetypes
import os
import queue
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import webbrowser
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import engine  # noqa: E402  (next to this file: the engine's Python, the settings, the first-run setup)
import report  # noqa: E402  (problem hints and reports)
import updates  # noqa: E402  (a new app version, a fresh downloader)
import anki_export  # noqa: E402  (local audio clips and AnkiConnect; standard library only)
import links  # noqa: E402  (pipeline/links.py: pasted text to a link; engine.py put pipeline/ on the path)

HERE = Path(__file__).resolve().parent
LOG = logging.getLogger("pianpian")
SCRIPT = HERE / "pipeline" / "study.py"
VIDEO_EXT = anki_export.VIDEO_EXT
SAFE_ID = re.compile(r"^[^/\\\x00]+$")                  # one name: no separators or NUL
# Windows opens these as devices whatever the folder or extension (NUL.mp4 is NUL); it also drops a trailing dot or space
DEVICE = re.compile(r"(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³]|CONIN\$|CONOUT\$) *(\..*)?|.*[. ]", re.I | re.S)
TRACK_FILES = {"zh": "zh.srt", "pinyin": "zh.pinyin.srt", "en": "zh.en.srt", "mkv": "study.mkv"}
mimetypes.add_type("text/plain; charset=utf-8", ".srt")
mimetypes.add_type("text/vtt; charset=utf-8", ".vtt")
mimetypes.add_type("video/x-matroska", ".mkv")
mimetypes.add_type("text/javascript; charset=utf-8", ".js")
mimetypes.add_type("application/json; charset=utf-8", ".json")

CFG = {"library": Path(engine.config()["library"]).expanduser()}
_m = re.search(r'^version = "([^"]+)"', (HERE / "pyproject.toml").read_text(encoding="utf-8"), re.M) if (HERE / "pyproject.toml").exists() else None
_v = HERE / "VERSION"                                       # written into the app by tools/build_app.py
VERSION = os.environ.get("PIANPIAN_VERSION") or (_v.read_text().strip() if _v.exists() else _m[1] if _m else "dev")


# ---------------------------------------------------------------- library
def video_in(folder: Path):
    vids = sorted(p for p in folder.iterdir() if p.name.startswith("source.") and p.suffix.lower() in VIDEO_EXT)
    return vids[0] if vids else None


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


_LEVELS: dict = {}                                       # zh.words.json path -> (mtime, video HSK level)


def video_hsk(folder: Path) -> int:
    """The video's HSK level from zh.words.json (srt_tool.py words), 0 if it hasn't been worked out."""
    f = folder / "zh.words.json"
    if not f.exists():
        return 0
    m = f.stat().st_mtime
    if _LEVELS.get(f, (None,))[0] != m:
        try:
            _LEVELS[f] = (m, int(json.loads(f.read_text(encoding="utf-8")).get("hsk", {}).get("level", 0)))
        except (ValueError, OSError):
            _LEVELS[f] = (m, 0)
    return _LEVELS[f][1]


def describe(entry: Path) -> dict:
    """One library item: a pipeline folder, or a loose video file not processed yet."""
    if entry.is_file():
        return {"id": entry.name, "kind": "file", "title": entry.stem, "url": "", "video": entry.name,
                "has": {k: False for k in TRACK_FILES}, "subs": [], "hardsubs": False,
                "needsEnglish": False, "mtime": entry.stat().st_mtime}
    vid = video_in(entry)
    has = {k: (entry / f).exists() for k, f in TRACK_FILES.items()}
    return {"id": entry.name, "kind": "folder", "title": read(entry / "title.txt") or entry.name,
            "url": read(entry / "source.url"), "video": vid.name if vid else None, "has": has,
            "subs": sorted(p.name for p in entry.glob("*.srt") if not p.name.startswith("source.") and not p.name.endswith(".long.srt")),
            "words": "zh.words.json" if (entry / "zh.words.json").exists() else None,
            "align": "zh.align.json" if (entry / "zh.align.json").exists() else None,
            "hardsubs": (entry / ".hardsubs").exists(),
            "englishAuto": (entry / ".english-auto").exists(),
            "split": int(read(entry / ".split")) if read(entry / ".split").isdigit() else None,
            "needsEnglish": (entry / "zh.lines.txt").exists() and not has["en"],
            "hsk": video_hsk(entry),
            "mtime": max((p.lstat().st_mtime for p in entry.iterdir()), default=entry.stat().st_mtime)}


def inside_library(f: Path) -> bool:
    """By the real path: a link in the library must not lead out of it. (The app's own files are checked by name.)"""
    try:
        return f.resolve().is_relative_to(CFG["library"].resolve())
    except (OSError, RuntimeError):                          # a link loop, a name the system refuses
        return False


def library() -> list:
    lib = CFG["library"]
    lib.mkdir(parents=True, exist_ok=True)
    folders = [p for p in lib.iterdir() if p.is_dir() and not p.name.startswith(".") and inside_library(p)]
    done = {p.name[:-len("_study")] for p in folders if p.name.endswith("_study")}
    files = [p for p in lib.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT and p.stem not in done and inside_library(p)]
    return sorted((describe(p) for p in folders + files), key=lambda v: -v["mtime"])


def safe_name(name: str) -> bool:
    return bool(SAFE_ID.fullmatch(name)) and not name.startswith(".") and \
        (not engine.WINDOWS or ":" not in name and not DEVICE.fullmatch(name))


def entry_path(vid_id: str) -> Path:
    if not safe_name(vid_id):
        raise ValueError("bad id")
    p = CFG["library"] / vid_id
    if not p.exists() or not inside_library(p):
        raise FileNotFoundError(vid_id)
    return p


# ---------------------------------------------------------------- jobs (one at a time)
class Job:
    _n = 0

    def __init__(self, label, cmd, cwd, env=None, video=None):
        Job._n += 1
        self.id, self.label, self.cmd, self.cwd, self.env, self.video = Job._n, label, cmd, cwd, env or {}, video
        self.state, self.log, self.started, self.ended, self.code = "queued", [], None, None, None
        self.kind = "rebuild"
        self.on_done = None                                   # called after a successful run
        # Output arrives in chunks that can cut a line or a UTF-8 character in two. A cut transcript line would lose its
        # [00:..-->] prefix and slip past report.TRANSCRIPT, so only whole lines reach the log.
        self._tail, self._utf8 = "", codecs.getincrementaldecoder("utf-8")("replace")

    def feed(self, chunk: bytes, final=False):
        lines = re.split(r"[\r\n]+", self._tail + self._utf8.decode(chunk, final))
        self._tail = "" if final else lines.pop()[:64 * 1024]   # a line that never ends: bounded, still one line
        self.add("\n".join(lines))

    def add(self, text):
        for part in re.split(r"[\r\n]+", text):
            part = part.rstrip()
            if not part:
                continue
            if self.log and part.startswith("[download]") and self.log[-1].startswith("[download]") and "%" in part:
                self.log[-1] = part                           # keep one live progress line, not hundreds
            else:
                self.log.append(part)
            if self.video is None and (m := re.match(r"folder: (.+)$", part)):
                self.video = Path(m[1]).name                # study.py says which folder it works in
        del self.log[:-400]

    def public(self, tail=60):
        return {"id": self.id, "kind": self.kind, "label": self.label, "state": self.state, "video": self.video, "log": self.log[-tail:],
                "started": self.started, "ended": self.ended, "code": self.code,
                "problem": (report.explain(self.log) or {"code": "JOB-FAILED", "hint": ""}) if self.state == "failed" else None}


JOBS: list = []
QUEUE: "queue.Queue[Job]" = queue.Queue()
STARTING = threading.Lock()                                  # setup cannot replace paths used by jobs, imports or Anki media
CLOSING = False
WORKER = None
ANKI_ACTIVE = 0
IMPORTS_ACTIVE = 0
IMPORT_TARGETS = set()
SETUP_RUNS = "The setup is running. Try again when it has finished."


@contextmanager
def anki_media():
    global ANKI_ACTIVE
    with STARTING:
        if engine.SETUP.state == "running":
            raise RuntimeError(SETUP_RUNS)
        ANKI_ACTIVE += 1
    try:
        yield
    finally:
        with STARTING:
            ANKI_ACTIVE -= 1


@contextmanager
def import_operation(name):
    """Reserve one destination while copying; setup stays out until the job is queued."""
    global IMPORTS_ACTIVE
    with STARTING:
        if engine.SETUP.state == "running":
            raise RuntimeError(SETUP_RUNS)
        lib = CFG["library"]
        target, n = lib / name, 2
        # APFS also folds canonical Unicode forms; avoid case/NFC/NFD aliases on every filesystem.
        key = lambda p: unicodedata.normalize("NFC", str(p.absolute()).casefold())
        while target.exists() or key(target) in IMPORT_TARGETS or (lib / (target.stem + "_study")).exists():
            target, n = lib / f"{Path(name).stem} ({n}){Path(name).suffix}", n + 1
        IMPORT_TARGETS.add(key(target))
        IMPORTS_ACTIVE += 1
    try:
        yield lib, target
    finally:
        with STARTING:
            IMPORT_TARGETS.remove(key(target))
            IMPORTS_ACTIVE -= 1


def worker():
    while True:
        job = QUEUE.get()
        if job is None:                                       # stop(): let the worker finish before app exit
            return
        job.state, job.started = "running", time.time()
        job.add("$ " + " ".join(str(c) for c in job.cmd))
        try:
            # The native launcher bypasses main(); every job must match the UTF-8 log decoder below.
            with engine.process(job.cmd, cwd=job.cwd, env={**os.environ, **job.env, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=engine.NO_WINDOW) as p:
                while chunk := p.stdout.read1(4096):
                    job.feed(chunk)
                job.feed(b"", final=True)
                job.code = p.wait()
                job.state = "done" if job.code == 0 else "failed"
        except Exception as e:                                # missing tool, permissions, shutdown…
            job.add(f"error: {e}")
            job.state = "failed"
        job.ended = time.time()
        if job.state == "done" and job.on_done:
            job.on_done()
        LOG.info("job %s %s: %s (%.0f s)", job.id, job.kind, job.state, job.ended - job.started)
        if job.state == "failed":                             # the whole log of a failure, for a report later
            LOG.info("job %s log:\n%s", job.id, "\n".join(job.log[-200:]))


def enqueue(job: Job) -> Job:
    with STARTING:
        if CLOSING:
            raise RuntimeError("Pianpian is closing")
        if engine.SETUP.state == "running":
            raise RuntimeError(SETUP_RUNS)
        JOBS.append(job)
        del JOBS[:-30]
        QUEUE.put(job)
    return job


def rebuild_job(vid_id: str, translate=False, split=None) -> Job:
    p = entry_path(vid_id)
    env = {"AUTO_EN": "1"} if translate else {}
    if split is not None:
        env.update(RESPLIT="1", SPLIT_MAX=str(split))
    if p.is_file():                                           # loose video: the script makes <name>_study/
        return enqueue(Job(f"Make subtitles · {p.name}", [engine.python(), str(SCRIPT), str(p)], str(p.parent), env, video=p.stem + "_study"))
    src = video_in(p)
    if not src:
        raise FileNotFoundError("no source video in " + vid_id)
    if translate:
        env["FORCE_EN"] = "1"
    verb = "Translate" if translate else f"Lines of {split or 'any'} characters" if split is not None else "Rebuild"
    return enqueue(Job(f"{verb} · {read(p / 'title.txt') or vid_id}", [engine.python(), str(SCRIPT), str(src)], str(p), env, video=vid_id))


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "Pianpian/1"

    def log_message(self, fmt, *args):                        # quiet: the app shows what matters
        pass

    def own_origins(self) -> set:
        port = self.server.server_port
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def parse_request(self):
        # DNS rebinding: a site can point its own name at 127.0.0.1 and then count as same-origin, so the
        # X-Kit guard would no longer hold. Every request must name this server in its Host header.
        if not super().parse_request():
            return False
        if (self.headers.get("Host") or "").lower() not in self.own_origins():
            self.close_connection = True                     # its body, if any, is never read
            self.fail(403, "wrong Host header")
            return False
        return True

    # ---- helpers
    def send_json(self, obj, status=200, cors=False):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cors:                                              # only /api/status: lets another page see that the app runs
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(body)

    def fail(self, status, msg):
        self.send_json({"error": msg}, status)

    def send_file(self, path: Path):
        size = path.stat().st_size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end, status = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
        if m and size:                                        # byte ranges, so <video> can seek
            if m[1]:
                start, end = int(m[1]), min(int(m[2]) if m[2] else size - 1, size - 1)
            else:
                start = max(0, size - int(m[2]))
            if start > end:
                self.send_response(416); self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with path.open("rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0 and (buf := f.read(min(256 * 1024, left))):
                    self.wfile.write(buf)
                    left -= len(buf)
        except OSError:                                       # the browser cancels ranges all the time; headers are out
            pass

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    # ---- GET
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/api/status":
                busy = any(j.state in ("queued", "running") for j in JOBS)
                accel = "mlx"
                if engine.WINDOWS:                    # status never probes hardware: use the saved choice or "auto"
                    accel = "auto"
                    choice = engine.PATH_OVERRIDES["PIANPIAN_ACCEL"] or engine.config().get("accel")
                    if choice in ("cpu", "vulkan", "cuda"):
                        bw = choice if ("whisper", choice) in engine.runtimes.ASSETS else "cpu"
                        bl = choice if ("llama", choice) in engine.runtimes.ASSETS else "cpu"
                        accel = bw if bw == bl else f"whisper.cpp {bw} · llama.cpp {bl}"
                origin = self.headers.get("Origin")
                if origin and origin.lower().removeprefix("http://") not in self.own_origins():
                    # another site (or a page from disk) may only learn that the app runs, never the library path
                    return self.send_json({"ok": True, "version": VERSION}, cors=True)
                return self.send_json({"ok": True, "version": VERSION, "library": str(CFG["library"]), "engine": engine.STATE["engine"], "current": engine.STATE["current"],
                                       "platform": "win32" if engine.WINDOWS else "darwin", "accel": accel, "browsers": engine.installed_browsers(),
                                       "busy": busy, "update": UPDATE.get("app")})
            if path == "/api/videos":
                return self.send_json(library())
            if path == "/api/anki/status":
                return self.send_json(anki_export.status())
            if m := re.fullmatch(r"/api/anki/audio/(pianpian-[0-9a-f]{64}\.mp3)", path):
                with anki_media():
                    return self.send_file(anki_export.audio_path(m[1]))
            if m := re.fullmatch(r"/api/videos/([^/]+)", path):
                p = entry_path(m[1])
                info = describe(p)
                if p.is_dir():
                    info["lines"] = read(p / "zh.lines.txt")
                    info["english"] = read(p / "en.lines.txt")
                return self.send_json(info)
            if path == "/api/setup":                       # what the first-run setup would do, and how it is going
                return self.send_json({**engine.SETUP.plan(), "progress": engine.SETUP.public()})
            if path == "/api/report":                      # ?job=<id>, or the setup's failure, or a general report
                return self.send_json(problem_report(parse_qs(urlparse(self.path).query)))
            if path == "/api/jobs":
                return self.send_json([j.public() for j in reversed(JOBS)])
            if m := re.fullmatch(r"/library/([^/]+)/(thumb|poster)\.jpg", path):
                return self.thumb(entry_path(m[1]), m[2])
            if m := re.fullmatch(r"/library/([^/]+)(?:/([^/]+))?", path):
                p = entry_path(m[1])
                if m[2] and not safe_name(m[2]):
                    return self.fail(404, "bad filename")
                f = p / m[2] if m[2] else p
                if f.is_file() and not f.name.startswith(".") and f.parent in (p, CFG["library"]) and inside_library(f):
                    if p.is_dir() and f.name == "zh.words.json":
                        with anki_media():
                            return self.send_json(anki_export.study_words(p))
                    return self.send_file(f)
                return self.fail(404, "not found")
            # the app's own page and assets
            # checked by name, not by resolving links: inside Pianpian.app the files are links into Contents/Resources
            rel = path.lstrip("/") or "app.html"
            parts = Path(rel).parts
            f = HERE.joinpath(*parts) if parts else HERE / "app.html"
            if parts and all(safe_name(part) for part in parts) and f.is_file() \
                    and f.suffix in (".html", ".css", ".js", ".svg", ".png", ".md"):
                return self.send_file(f)
            self.fail(404, "not found")
        except RuntimeError as e:
            self.fail(409, str(e))
        except (ValueError, OSError) as e:                    # OSError: a name the system refuses, a file it can't read
            self.fail(404, str(e))

    def thumb(self, p: Path, name: str):
        if p.is_file():
            return self.fail(404, "no thumbnail for a loose file")
        out = p / f"{name}.jpg"
        if not inside_library(out):                           # a link: never write through it or serve it
            return self.fail(404, "no thumbnail")
        width = 1280 if name == "poster" else 480
        if not out.exists() and (src := video_in(p)):
            engine.run([engine.ffmpeg() or "ffmpeg", "-loglevel", "error", "-y", "-ss", "4", "-i", str(src), "-frames:v", "1",
                        "-vf", f"scale={width}:-2", str(out)], timeout=30, creationflags=engine.NO_WINDOW)
        return self.send_file(out) if out.exists() else self.fail(404, "no thumbnail")

    def do_OPTIONS(self):                                     # preflight for /api/status only
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET")
        self.end_headers()

    # ---- PUT /api/import?name=…&translate=1: a video dropped on the window, copied into the library
    #      and then made into subtitles like a loose file (needs X-Kit, like POST)
    def do_PUT(self):
        if self.headers.get("X-Kit") != "1":
            return self.fail(403, "missing X-Kit header")
        u = urlparse(self.path)
        if u.path != "/api/import":
            return self.fail(404, "not found")
        q = dict(p.split("=", 1) for p in u.query.split("&") if "=" in p)
        name = Path(unquote(q.get("name", ""))).name.strip()
        size = int(self.headers.get("Content-Length") or 0)
        if not safe_name(name) or Path(name).suffix.lower() not in VIDEO_EXT:
            return self.fail(400, "drop a video file (" + ", ".join(VIDEO_EXT) + ")")
        if not size:
            return self.fail(400, "empty file")
        try:
            with import_operation(name) as (lib, target):
                part = None
                try:
                    with tempfile.NamedTemporaryFile(mode="wb", dir=lib, prefix=f".{target.name}.", suffix=".part", delete=False) as f:
                        part = Path(f.name)
                        left = size
                        while left > 0 and (buf := self.rfile.read(min(1 << 20, left))):
                            f.write(buf)
                            left -= len(buf)
                    if left:
                        raise ConnectionError("upload stopped early")
                    part.rename(target)
                except (OSError, ConnectionError) as e:
                    if part:
                        part.unlink(missing_ok=True)
                    return self.fail(500, f"could not copy the video into the library: {e}")
                try:
                    job = rebuild_job(target.name, translate=q.get("translate") == "1")
                except (RuntimeError, FileNotFoundError) as e:
                    return self.fail(409, str(e))
                job.kind = "add"                              # like a new link: the app opens it when it is done
                return self.send_json(job.public())
        except RuntimeError as e:
            return self.fail(409, str(e))

    # ---- POST (needs X-Kit: other sites cannot send that header without a preflight we never grant)
    def do_POST(self):
        if self.headers.get("X-Kit") != "1":
            return self.fail(403, "missing X-Kit header")
        path = unquote(urlparse(self.path).path)               # the page sends encodeURIComponent(id): Chinese names arrive %-encoded
        try:
            if path.startswith("/api/anki/") and int(self.headers.get("Content-Length") or 0) > 256 * 1024:
                return self.fail(413, "Anki request is too large.")
            data = self.body()
            if path.startswith("/api/anki/"):
                return self.anki_request(path, data)
            if path == "/api/add":
                try:                                       # a bare link, or the text a Share button copies; tracking removed
                    url = links.normalize(str(data.get("url", "")))
                except ValueError:
                    return self.fail(400, "paste a link (the text a Share button copies works too)")
                browser = str(data.get("browser") or "")
                if browser and browser not in engine.BROWSERS:
                    return self.fail(400, "unknown browser")
                cmd = [engine.python(), str(SCRIPT), url] + ([browser] if browser else [])
                env = {**({"HARDSUBS": "1"} if data.get("burned") else {}), **({"AUTO_EN": "1"} if data.get("translate") else {})}
                job = Job(f"Download · {url}", cmd, str(CFG["library"]), env)
                job.kind = "add"
                return self.send_json(enqueue(job).public())
            if path == "/api/setup":                       # {library, data, models: [ids]}: install what is missing
                library = str(data.get("library") or "").strip() or None
                folder = str(data.get("data") or "").strip() or None
                for d in (library, folder):
                    if d and not Path(d).expanduser().is_absolute():
                        return self.fail(400, f"not a full folder path: {d}")
                with STARTING:
                    if ANKI_ACTIVE:
                        return self.fail(409, "Wait for Anki audio and word processing to finish, then run the setup.")
                    if IMPORTS_ACTIVE:
                        return self.fail(409, "Wait for the video import to finish, then run the setup.")
                    if busy := next((j for j in JOBS if j.state in ("queued", "running")), None):
                        return self.fail(409, f"Wait for “{busy.label}” to finish, then run the setup.")
                    try:
                        engine.SETUP.start(library, folder, [str(m) for m in data.get("models") or []], cleanup=bool(data.get("cleanup")))
                    except RuntimeError as e:
                        return self.fail(409, str(e))
                CFG["library"] = Path(engine.config()["library"]).expanduser()
                CFG["library"].mkdir(parents=True, exist_ok=True)
                return self.send_json(engine.SETUP.public())
            if path == "/api/update-downloader":           # sites change; yt-dlp follows them
                job = downloader_job()
                return self.send_json(job.public()) if job else self.fail(409, "uv was not found, so the downloader can't be updated")
            if m := re.fullmatch(r"/api/videos/([^/]+)/rebuild", path):
                return self.send_json(rebuild_job(m[1]).public())
            if m := re.fullmatch(r"/api/videos/([^/]+)/split", path):
                n = int(data.get("max", 18))
                if not 0 <= n <= 60:
                    return self.fail(400, "max must be 0–60 characters")
                return self.send_json(rebuild_job(m[1], split=n).public())
            if m := re.fullmatch(r"/api/videos/([^/]+)/translate", path):
                return self.send_json(rebuild_job(m[1], translate=True).public())
            if m := re.fullmatch(r"/api/videos/([^/]+)/english", path):
                p = entry_path(m[1])
                text = str(data.get("text", "")).replace("\r\n", "\n").strip()
                bad = [l for l in text.split("\n") if l.strip() and not re.match(r"^\s*\d+\t", l)]
                if not text or bad:
                    return self.fail(400, f"every line must be: number, TAB, English. First bad line: {bad[0][:60]!r}" if bad else "paste the reply first")
                (p / "en.lines.txt").write_text(text + "\n", encoding="utf-8")
                (p / ".english-auto").unlink(missing_ok=True)      # now a hand-made translation
                return self.send_json(rebuild_job(m[1]).public())
            if m := re.fullmatch(r"/api/videos/([^/]+)/open", path):
                engine.reveal(entry_path(m[1]))
                return self.send_json({"ok": True})
            self.fail(404, "not found")
        except json.JSONDecodeError:                          # before ValueError, its parent
            self.fail(400, "bad JSON")
        except RuntimeError as e:                             # enqueue: the setup is running
            self.fail(409, str(e))
        except (ValueError, FileNotFoundError) as e:
            self.fail(404, str(e))
        except OSError as e:                                  # a name the system refuses, a folder it can't write
            self.fail(400, str(e))

    def anki_request(self, path, data):
        try:
            if not isinstance(data, dict):
                raise ValueError("Expected an Anki request object.")
            if path == "/api/anki/settings":
                return self.send_json(anki_export.settings(data))
            if path == "/api/anki/open":
                return self.send_json(anki_export.open_note(data))
            if path in ("/api/anki/preview", "/api/anki/export"):
                with anki_media():
                    if not isinstance(data.get("id"), str):
                        raise ValueError("Select a library item first.")
                    entry = entry_path(data["id"])
                    action = anki_export.preview if path.endswith("/preview") else anki_export.export
                    return self.send_json(action(entry, CFG["library"], data))
            self.fail(404, "not found")
        except anki_export.AnkiError as e:
            self.send_json({"error": str(e), "code": e.code}, 503)
        except (ValueError, FileNotFoundError, KeyError, TypeError) as e:
            self.fail(400, str(e))
        except subprocess.TimeoutExpired:
            self.fail(503, "Audio processing timed out. Select a shorter clip and retry.")
        except OSError:
            self.fail(500, "Could not read or save the audio. Check the library and data-folder permissions.")


def problem_report(q: dict) -> dict:
    """What went wrong and the details to share, redacted, plus the GitHub bug form filled in."""
    job = next((j for j in JOBS if str(j.id) == (q.get("job") or [""])[0]), None)
    if job is None and not q.get("setup"):
        job = next((j for j in reversed(JOBS) if j.state == "failed"), None)
    setup = engine.SETUP.public() if q.get("setup") else None
    log = setup["log"] if setup else job.log if job else []
    problem = report.explain(log) or {"code": "SETUP-FAILED" if setup else "JOB-FAILED" if job else "", "hint": ""}
    st = engine.STATE
    models = ", ".join(f"{m['id'].split('/')[-1]} {'ready' if m['ready'] else 'missing'}" for m in engine.models.status())
    runtime = engine.runtimes.status(probe=False) if engine.WINDOWS else None
    summary = [f"Pianpian {VERSION}", f"engine: {'ok' if st['engine'] else 'not working' if st['engine'] is False else 'not checked'}"
               f"{'' if st['current'] in (None, True) else ', out of date'}", f"models: {models}",
               *([f"runtime: {runtime['label']} ({', '.join(k + ' ' + ('ready' if v['ready'] else 'missing') for k, v in runtime['tools'].items())})"]
                 if runtime else []),
               f"what failed: {'the setup' if setup else job.kind if job else 'nothing recorded'}"
               + (f" ({problem['code']})" if problem["code"] else ""), ""]
    details = report.redact("\n".join(summary + log[-80:]), CFG["library"])
    sysline = report.system()
    title = f"{problem['code'] or 'Problem'}: " + (problem["hint"].split(".")[0] if problem["hint"] else "something went wrong")
    return {**problem, "details": details, "system": sysline,
            "url": report.issue_url(report.REPO, title, problem["code"], details, sysline)}


UPDATE: dict = {}                                            # {"app": {version, url, notes, download}} when one is out


def downloader_job() -> "Job | None":
    cmd = updates.update_ytdlp_cmd()
    if not cmd:
        return None
    job = Job("Update the downloader (yt-dlp)", cmd, str(engine.data_dir()), engine.mirror_env())
    job.kind, job.on_done = "update", updates.mark_ytdlp_updated
    return enqueue(job)


def keep_up_to_date() -> None:
    """In the background: a new Pianpian (once a day), and the downloader (once a week)."""
    if os.environ.get("PIANPIAN_NO_UPDATE_CHECK"):            # tests, and anyone who'd rather not
        return
    while True:
        UPDATE["app"] = updates.check_app(VERSION)
        if engine.STATE["engine"] and updates.ytdlp_due() and not any(j.kind == "update" and j.state in ("queued", "running") for j in JOBS):
            try:
                downloader_job()
            except RuntimeError:                              # the setup is running: next round
                pass
        time.sleep(6 * 3600)


class LocalServer(ThreadingHTTPServer):
    """ThreadingHTTPServer without its reverse DNS lookup of the host (socket.getfqdn), which can hang for
    many seconds on slow networks before the window shows anything. It only ever listens on 127.0.0.1."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def start(port: int = 8770, library: Path | None = None) -> ThreadingHTTPServer:
    """Start the job worker and bind the server (not yet serving). launcher.py uses this too."""
    global CLOSING, WORKER
    CLOSING = engine.CLOSING = False
    if not LOG.handlers:                                      # one rotating log: at most 3 × 1 MB
        h = RotatingFileHandler(engine.logs_dir() / "server.log", maxBytes=1 << 20, backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        LOG.addHandler(h)
        LOG.setLevel(logging.INFO)
    LOG.info("Pianpian %s starting, engine %s", VERSION, engine.python())
    if library:
        CFG["library"] = Path(library).expanduser().resolve()
    CFG["library"].mkdir(parents=True, exist_ok=True)
    os.environ.update(engine.pipeline_env())                      # the pipeline's jobs find the models and dictionary there
    threading.Thread(target=lambda: (engine.check(), keep_up_to_date()), daemon=True).start()
    srv = LocalServer(("127.0.0.1", port), Handler)            # raises OSError if the port is taken
    WORKER = threading.Thread(target=worker, daemon=True)
    WORKER.start()
    return srv


def stop(srv: ThreadingHTTPServer) -> None:
    """Stop HTTP admission, the active process trees and the job worker."""
    global CLOSING
    with STARTING:
        CLOSING = True
    engine.stop_processes()
    QUEUE.put(None)
    srv.shutdown()
    srv.server_close()
    if WORKER:
        WORKER.join(timeout=10)


def main():
    if engine.WINDOWS:                                     # the console may not be UTF-8: never crash on a log line
        os.environ.setdefault("PYTHONUTF8", "1")
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--library", type=Path, default=CFG["library"], help="where videos live (default: the folder chosen in the setup, else ~/Movies/Pianpian)")
    ap.add_argument("--no-browser", action="store_true", help="don't open the app in a browser")
    a = ap.parse_args()
    srv = start(a.port, a.library)
    url = f"http://127.0.0.1:{a.port}/app.html"
    print(f"Pianpian → {url}\nlibrary: {CFG['library']}\nCtrl+C to stop.")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        stop(srv)


if __name__ == "__main__":
    main()
