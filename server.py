#!/usr/bin/env python3
"""Pianpian local server. Python standard library only.

    python3 server.py                 # http://127.0.0.1:8770 · library ~/Movies/mandarin · opens the browser
    python3 server.py --no-browser --library ~/Movies/other

Serves the pages in this folder and the videos in the library, and runs pipeline/study.py
(one job at a time) so the app can download a link, make subtitles and rebuild a video.
Everything it knows about a video lives in that video's folder (see PLAN.md), so the app and
the command line always agree. Listens on 127.0.0.1 only.
"""
import argparse
import json
import logging
import mimetypes
import os
import queue
import re
import socketserver
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import engine  # noqa: E402  (next to this file: the engine's Python, the settings, the first-run setup)
import report  # noqa: E402  (problem hints and reports)
import updates  # noqa: E402  (a new app version, a fresh downloader)

HERE = Path(__file__).resolve().parent
LOG = logging.getLogger("pianpian")
SCRIPT = HERE / "pipeline" / "study.py"
# browsers yt-dlp can borrow a Bilibili login from, as macOS apps
BROWSERS = {"safari": "Safari", "chrome": "Google Chrome", "brave": "Brave Browser", "firefox": "Firefox",
            "edge": "Microsoft Edge", "chromium": "Chromium", "opera": "Opera", "vivaldi": "Vivaldi"}
VIDEO_EXT = (".mp4", ".m4v", ".mkv", ".webm", ".mov")
SAFE_ID = re.compile(r"^[^/\\\x00]+$")                  # one name inside the library: no slashes
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
            "mtime": max((p.stat().st_mtime for p in entry.iterdir()), default=entry.stat().st_mtime)}


def library() -> list:
    lib = CFG["library"]
    lib.mkdir(parents=True, exist_ok=True)
    folders = [p for p in lib.iterdir() if p.is_dir() and not p.name.startswith(".")]
    done = {p.name[:-len("_study")] for p in folders if p.name.endswith("_study")}
    files = [p for p in lib.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT and p.stem not in done]
    return sorted((describe(p) for p in folders + files), key=lambda v: -v["mtime"])


def entry_path(vid_id: str) -> Path:
    if not SAFE_ID.match(vid_id) or vid_id.startswith("."):
        raise ValueError("bad id")
    p = CFG["library"] / vid_id
    if not p.exists():
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


def worker():
    while True:
        job = QUEUE.get()
        job.state, job.started = "running", time.time()
        job.add("$ " + " ".join(str(c) for c in job.cmd))
        try:
            p = subprocess.Popen(job.cmd, cwd=job.cwd, env={**os.environ, **job.env},
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            while chunk := p.stdout.read1(4096):
                job.add(chunk.decode("utf-8", "replace"))
            job.code = p.wait()
            job.state = "done" if job.code == 0 else "failed"
        except Exception as e:                                # missing tool, permissions…
            job.add(f"error: {e}")
            job.state = "failed"
        job.ended = time.time()
        if job.state == "done" and job.on_done:
            job.on_done()
        LOG.info("job %s %s: %s (%.0f s)", job.id, job.kind, job.state, job.ended - job.started)
        if job.state == "failed":                             # the whole log of a failure, for a report later
            LOG.info("job %s log:\n%s", job.id, "\n".join(job.log[-200:]))


def enqueue(job: Job) -> Job:
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

    # ---- helpers
    def send_json(self, obj, status=200, cors=False):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cors:                                              # only /api/status: lets a page opened from disk see the server
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
        except (BrokenPipeError, ConnectionResetError):       # the browser cancels ranges all the time
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
                return self.send_json({"ok": True, "version": VERSION, "library": str(CFG["library"]), "engine": engine.STATE["engine"], "current": engine.STATE["current"],
                                       "browsers": installed_browsers(), "busy": busy, "update": UPDATE.get("app")}, cors=True)
            if path == "/api/videos":
                return self.send_json(library())
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
            if m := re.fullmatch(r"/library/([^/]+)/thumb\.jpg", path):
                return self.thumb(entry_path(m[1]))
            if m := re.fullmatch(r"/library/([^/]+)(?:/([^/]+))?", path):
                p = entry_path(m[1])
                f = p / m[2] if m[2] else p
                if f.is_file() and not f.name.startswith(".") and f.parent in (p, CFG["library"]):
                    return self.send_file(f)
                return self.fail(404, "not found")
            # the app's own page and assets
            # checked by name, not by resolving links: inside Pianpian.app the files are links into Contents/Resources
            rel = path.lstrip("/") or "app.html"
            parts = Path(rel).parts
            f = HERE.joinpath(*parts) if parts else HERE / "app.html"
            if parts and not any(part in ("..", "") or part.startswith(".") or "\\" in part for part in parts) and f.is_file() \
                    and f.suffix in (".html", ".css", ".js", ".svg", ".png", ".md"):
                return self.send_file(f)
            self.fail(404, "not found")
        except (ValueError, FileNotFoundError) as e:
            self.fail(404, str(e))

    def thumb(self, p: Path):
        if p.is_file():
            return self.fail(404, "no thumbnail for a loose file")
        out = p / "thumb.jpg"
        if not out.exists() and (src := video_in(p)):
            subprocess.run([engine.ffmpeg() or "ffmpeg", "-loglevel", "error", "-y", "-ss", "4", "-i", str(src), "-frames:v", "1",
                            "-vf", "scale=480:-2", str(out)], timeout=30)
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
        if not name or name.startswith(".") or Path(name).suffix.lower() not in VIDEO_EXT:
            return self.fail(400, "drop a video file (" + ", ".join(VIDEO_EXT) + ")")
        if not size:
            return self.fail(400, "empty file")
        lib = CFG["library"]
        target, n = lib / name, 2
        while target.exists() or (lib / (target.stem + "_study")).exists():   # never overwrite: "name (2).mp4"
            target, n = lib / f"{Path(name).stem} ({n}){Path(name).suffix}", n + 1
        part = lib / f".{target.name}.part"
        try:
            with part.open("wb") as f:
                left = size
                while left > 0 and (buf := self.rfile.read(min(1 << 20, left))):
                    f.write(buf)
                    left -= len(buf)
            if left:
                raise ConnectionError("upload stopped early")
            part.rename(target)
        except (OSError, ConnectionError) as e:
            part.unlink(missing_ok=True)
            return self.fail(500, f"could not copy the video into the library: {e}")
        job = rebuild_job(target.name, translate=q.get("translate") == "1")
        job.kind = "add"                                      # like a new link: the app opens it when it is done
        return self.send_json(job.public())

    # ---- POST (needs X-Kit: other sites cannot send that header without a preflight we never grant)
    def do_POST(self):
        if self.headers.get("X-Kit") != "1":
            return self.fail(403, "missing X-Kit header")
        path = urlparse(self.path).path
        try:
            data = self.body()
            if path == "/api/add":
                url = str(data.get("url", "")).strip()
                if not re.match(r"^https?://\S+$", url):
                    return self.fail(400, "paste a full http(s) link")
                browser = str(data.get("browser") or "")
                if browser and browser not in BROWSERS:
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
                try:
                    engine.SETUP.start(library, folder, [str(m) for m in data.get("models") or []], cleanup=bool(data.get("cleanup")))
                except RuntimeError as e:
                    return self.fail(409, str(e))
                CFG["library"] = Path(engine.config()["library"]).expanduser()
                CFG["library"].mkdir(parents=True, exist_ok=True)
                os.environ["PIANPIAN_MODELS"] = str(engine.models_dir())
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
                subprocess.Popen(["open", str(entry_path(m[1]))])
                return self.send_json({"ok": True})
            self.fail(404, "not found")
        except (ValueError, FileNotFoundError) as e:
            self.fail(404, str(e))
        except json.JSONDecodeError:
            self.fail(400, "bad JSON")


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
    summary = [f"Pianpian {VERSION}", f"engine: {'ok' if st['engine'] else 'not working' if st['engine'] is False else 'not checked'}"
               f"{'' if st['current'] in (None, True) else ', out of date'}", f"models: {models}",
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
            downloader_job()
        time.sleep(6 * 3600)


def installed_browsers() -> list[str]:
    """The browsers on this Mac that yt-dlp can borrow a Bilibili login from (Safari is always there)."""
    apps = [Path("/Applications"), Path.home() / "Applications"]
    return [k for k, name in BROWSERS.items() if k == "safari" or any((a / f"{name}.app").exists() for a in apps)]


class LocalServer(ThreadingHTTPServer):
    """ThreadingHTTPServer without its reverse DNS lookup of the host (socket.getfqdn), which can hang for
    many seconds on slow networks before the window shows anything. It only ever listens on 127.0.0.1."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def start(port: int = 8770, library: Path | None = None) -> ThreadingHTTPServer:
    """Start the job worker and bind the server (not yet serving). launcher.py uses this too."""
    if not LOG.handlers:                                      # one rotating log: at most 3 × 1 MB
        h = RotatingFileHandler(engine.logs_dir() / "server.log", maxBytes=1 << 20, backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        LOG.addHandler(h)
        LOG.setLevel(logging.INFO)
    LOG.info("Pianpian %s starting, engine %s", VERSION, engine.python())
    if library:
        CFG["library"] = Path(library).expanduser().resolve()
    CFG["library"].mkdir(parents=True, exist_ok=True)
    os.environ["PIANPIAN_MODELS"] = str(engine.models_dir())      # the pipeline's jobs find the models there
    threading.Thread(target=lambda: (engine.check(), keep_up_to_date()), daemon=True).start()
    srv = LocalServer(("127.0.0.1", port), Handler)            # raises OSError if the port is taken
    threading.Thread(target=worker, daemon=True).start()
    return srv


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--library", type=Path, default=CFG["library"], help="where videos live (default ~/Movies/mandarin)")
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


if __name__ == "__main__":
    main()
