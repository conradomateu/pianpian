"""Pianpian's engine: the Python environment that runs the pipeline, the models, and the first-run setup.

The app itself is small. What it needs to make subtitles is installed on first run, after asking:
  1. Python 3.12 and the pipeline's packages, pinned with hashes in pipeline/requirements.txt
     (`python3 dev.py lock`), into <data>/engine with uv;
  2. the models you pick (pipeline/models.py), into <data>/models.
<data> is ~/Library/Application Support/Pianpian unless you choose another folder. Downloads come from
PyPI and python.org's builds, or from mirrors in mainland China when those are slow to reach.
Settings live in ~/Library/Application Support/Pianpian/config.json. Standard library only.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
FROZEN = getattr(sys, "frozen", False)                       # running inside Pianpian.app (tools/build_app.py)
if FROZEN:
    # Python writes .pyc files next to the scripts it imports. Inside the app that changes a signed bundle after it was
    # installed: `codesign --verify` fails from then on (measured: valid after build, invalid after one run, valid again
    # without the __pycache__ folders). The variable is inherited by the pipeline's own Python processes.
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
# $PIANPIAN_HOME moves everything (settings, engine, models): for tests, or a second install
SUPPORT = Path(os.environ.get("PIANPIAN_HOME") or Path.home() / "Library" / "Application Support" / "Pianpian")
CONFIG = SUPPORT / "config.json"
REQS = HERE / "pipeline" / "requirements.txt"
MODELS_PY = HERE / "pipeline" / "models.py"
CHECK = "import yt_dlp, pypinyin, jieba, zhconv, mlx_whisper, mlx_lm"
ENGINE_MB = 650                                              # Python + packages on disk
# each source and its mirror in mainland China, with a file both serve to time them by
PY_BUILD = "20251014/cpython-3.12.12+20251014-aarch64-apple-darwin-install_only_stripped.tar.gz"
SOURCES = {
    "UV_PYTHON_INSTALL_MIRROR": ("https://github.com/astral-sh/python-build-standalone/releases/download/" + PY_BUILD,
                                 "https://registry.npmmirror.com/-/binary/python-build-standalone/" + PY_BUILD,
                                 "https://registry.npmmirror.com/-/binary/python-build-standalone/"),
    "UV_DEFAULT_INDEX": ("https://pypi.org/simple/numpy/", "https://pypi.tuna.tsinghua.edu.cn/simple/numpy/",
                         "https://pypi.tuna.tsinghua.edu.cn/simple"),
}

sys.path.insert(0, str(HERE / "pipeline"))
import models  # noqa: E402


# ---------------------------------------------------------------- settings
def config() -> dict:
    try:
        saved = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    old = Path.home() / "Movies" / "mandarin"                # the library of the command-line days, if there is one
    return {"library": saved.get("library") or str(old if old.exists() else Path.home() / "Movies" / "Pianpian"),
            "data": saved.get("data") or str(SUPPORT), **{k: v for k, v in saved.items() if k not in ("library", "data")}}


def save_config(**changes) -> dict:
    cfg = {**config(), **{k: v for k, v in changes.items() if v is not None}}
    SUPPORT.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    return cfg


def logs_dir() -> Path:
    """macOS keeps app logs in ~/Library/Logs; with $PIANPIAN_HOME they stay next to everything else."""
    d = SUPPORT / "logs" if os.environ.get("PIANPIAN_HOME") else Path.home() / "Library" / "Logs" / "Pianpian"
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_dir() -> Path:
    return Path(config()["data"]).expanduser()


def models_dir() -> Path:
    return Path(os.environ.get("PIANPIAN_MODELS") or data_dir() / "models")


def cache_dir() -> Path:
    """The dictionary and other small downloads."""
    return Path(os.environ.get("PIANPIAN_CACHE") or data_dir() / "cache")


def pipeline_env() -> dict:
    """Where the pipeline finds the models and the dictionary: set for every job and setup step."""
    return {"PIANPIAN_MODELS": str(models_dir()), "PIANPIAN_CACHE": str(cache_dir())}


def engine_dir() -> Path:
    return data_dir() / "engine"


def python() -> str:
    """The Python that runs the pipeline: $PIANPIAN_PYTHON, the installed engine, the repository's
    .venv (`python3 dev.py engine`), else the one running this."""
    if os.environ.get("PIANPIAN_PYTHON"):
        return os.environ["PIANPIAN_PYTHON"]
    for p in (engine_dir() / "bin" / "python", HERE / ".venv" / "bin" / "python"):
        if p.exists():
            return str(p)
    # inside the packaged app, sys.executable is the app itself: running it would open a second window
    return str(engine_dir() / "bin" / "python") if FROZEN else sys.executable


def uv() -> str | None:
    """uv: the one inside the app, else one on this Mac."""
    for p in (os.environ.get("PIANPIAN_UV"), Path(getattr(sys, "_MEIPASS", HERE)) / "uv", HERE / "bin" / "uv"):
        if p and Path(p).is_file() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which("uv")


def ffmpeg() -> str | None:
    """Homebrew's ffmpeg, else the one in the engine (imageio-ffmpeg)."""
    if exe := shutil.which("ffmpeg"):
        return exe
    lib = Path(python()).parent.parent / "lib"
    return next((str(f) for f in sorted(lib.glob("python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*")) if os.access(f, os.X_OK)), None)


def requirements_id() -> str:
    try:
        return hashlib.sha256(REQS.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


# ---------------------------------------------------------------- is it ready?
STATE = {"engine": None, "current": None}                    # None until checked


def check() -> dict:
    """Can the engine's Python run the pipeline, and was it installed from today's requirements?"""
    py = python()
    try:
        ok = subprocess.run([py, "-c", CHECK], capture_output=True, timeout=120).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    stamp = Path(py).parent.parent / ".pianpian-requirements"
    # an engine made by hand (the repository's .venv) is kept up to date by its owner
    STATE.update(engine=ok, current=(not stamp.exists() and ok) or (stamp.exists() and stamp.read_text().strip() == requirements_id()))
    return dict(STATE)


def free_bytes(path: Path) -> int:
    p = Path(path).expanduser()
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


# ---------------------------------------------------------------- the setup
class Setup:
    """Installs the engine and the models in a thread; the page polls public()."""

    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.steps: list[dict] = []
        self.log = deque(maxlen=400)
        self.state, self.error = "idle", ""

    def public(self) -> dict:
        with self.lock:
            return {"state": self.state, "error": self.error, "steps": [dict(s) for s in self.steps], "log": list(self.log)[-60:]}

    def plan(self) -> dict:
        """What the setup would do, for the page to show before anything is downloaded."""
        cfg, st = config(), (STATE if STATE["engine"] is not None else check())
        os.environ.setdefault("PIANPIAN_MODELS", str(models_dir()))
        catalog = models.status()
        chosen = cfg.get("models")                          # what was picked last time; a model left out is not asked for again
        missing = [m for m in catalog if not m["ready"] and (chosen is None or m["id"] in chosen)]
        os.environ["PIANPIAN_MODELS"] = str(models_dir())
        return {"config": cfg, "engine": st, "uv": bool(uv()), "engineMB": ENGINE_MB, "models": catalog, "old": models.unused(),
                "free": free_bytes(Path(cfg["data"])), "needed": not st["engine"] or not st["current"] or bool(missing)}

    def start(self, library: str | None, data: str | None, want: list[str], cleanup: bool = False) -> None:
        with self.lock:
            if self.state == "running":
                raise RuntimeError("the setup is already running")
            save_config(library=library, data=data, models=want)
            self.state, self.error = "running", ""
            self.steps = [{"id": "engine", "label": "Engine: Python and the pipeline's tools", "state": "waiting", "done": 0, "total": 0}]
            self.steps += [{"id": m["id"], "label": m["about"], "state": "waiting", "done": 0, "total": m.get("size") or 0}
                           for m in models.status() if m["id"] in want]
            self.log.clear()
        self.cleanup = cleanup
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # -- internals
    def _say(self, line: str) -> None:
        with self.lock:
            self.log.append(line.rstrip())

    def _step(self, sid: str, **kw) -> None:
        with self.lock:
            next(s for s in self.steps if s["id"] == sid).update(kw)

    def _exec(self, cmd: list[str], env: dict, sid: str) -> None:
        self._say("$ " + " ".join(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd)))
        p = subprocess.Popen(cmd, env={**os.environ, **env}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in p.stdout:
            if line.startswith("@progress "):
                try:
                    d = json.loads(line[10:])
                    with self.lock:
                        s = next(s for s in self.steps if s["id"] == sid)
                        s["files"] = {**s.get("files", {}), d["file"]: d["done"]}
                        s["done"] = sum(s["files"].values())
                except (ValueError, KeyError, StopIteration):
                    pass
                continue
            self._say(line)
        if p.wait():
            raise RuntimeError(f"{Path(cmd[0]).name} stopped (exit {p.returncode}); see the log")

    def _run(self) -> None:
        try:
            self._say("checking which download sources are fastest from here")
            net = mirror_env()
            for k, v in net.items():
                self._say(f"  using the mirror {v}")
            env = {**net, "UV_PYTHON_INSTALL_DIR": str(data_dir() / "python"), "UV_NO_CACHE": "1", "UV_PYTHON_PREFERENCE": "only-managed",
                   "UV_HTTP_TIMEOUT": "60"}
            if not (STATE["engine"] and STATE["current"]):
                exe = uv()
                if not exe:
                    raise RuntimeError("uv was not found (it comes inside Pianpian.app; for the source version: brew install uv)")
                self._step("engine", state="running")
                eng = engine_dir()
                if not (eng / "bin" / "python").exists():
                    self._exec([exe, "venv", "--python", "3.12", str(eng)], env, "engine")
                # sync, not install: the engine ends up exactly as pinned, packages no longer listed are removed
                self._exec([exe, "pip", "sync", "--python", str(eng / "bin" / "python"), str(REQS)], env, "engine")
                (eng / ".pianpian-requirements").write_text(requirements_id() + "\n")
                self._say("fetching the dictionary (CC-CEDICT)")
                self._exec([str(eng / "bin" / "python"), "-c", "import sys; sys.path.insert(0, sys.argv[1]); import srt_tool; srt_tool.ensure_cedict()",
                            str(HERE / "pipeline")], {"PYTHONWARNINGS": "ignore::SyntaxWarning", **pipeline_env()}, "engine")
            self._say("checking the engine (the first start prepares its packages: about a minute)")
            check()
            self._step("engine", state="done")
            for s in self.steps[1:]:
                self._step(s["id"], state="running")
                self._exec([python(), str(MODELS_PY), "ensure", s["id"]], pipeline_env(), s["id"])
                self._step(s["id"], state="done", done=s["total"])
            if getattr(self, "cleanup", False):
                os.environ["PIANPIAN_MODELS"] = str(models_dir())
                self._say(f"deleted old models: {models.remove_unused() / 1e9:.1f} GB freed")
            with self.lock:
                self.state = "done"
        except Exception as e:                                # shown on the page, with the log
            with self.lock:
                self.state, self.error = "failed", str(e)
                for s in self.steps:
                    if s["state"] == "running":
                        s["state"] = "failed"


def speed(url: str, size: int = 400_000, seconds: float = 5.0) -> float:
    """Bytes per second for the first `size` bytes of url, 0 if it fails (gives up after `seconds`)."""
    t, got = time.monotonic(), 0
    try:
        with urlopen(Request(url, headers={"Range": f"bytes=0-{size - 1}"}), timeout=seconds) as r:
            while got < size and time.monotonic() - t < seconds:
                chunk = r.read(65536)
                if not chunk:
                    break
                got += len(chunk)
    except OSError:
        return 0.0
    return got / max(time.monotonic() - t, 1e-3)


def mirrors() -> dict:
    """uv settings for the sources that are much faster through their mirror (both timed at once)."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as pool:
        timed = {k: (pool.submit(speed, a), pool.submit(speed, b), m) for k, (a, b, m) in SOURCES.items()}
        return {k: m for k, (a, b, m) in timed.items() if b.result() > 2 * a.result()}


_MIRRORS: dict = {}


def mirror_env() -> dict:
    """mirrors(), timed once per run (the setup and the downloader update both use it)."""
    if "env" not in _MIRRORS:
        _MIRRORS["env"] = mirrors()
    return _MIRRORS["env"]


SETUP = Setup()
