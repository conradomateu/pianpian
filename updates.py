"""Staying up to date: a new Pianpian, and a fresh downloader.

- The app: GitHub's latest release is checked at most once a day, in the background. A newer version
  shows a notice with its notes and the download; nothing is installed without you.
- yt-dlp: video sites change every few weeks, so it gets updated on its own, outside the pinned
  requirements, at most once a week (and on demand from the app when a download fails because the site
  changed). The next engine sync puts the pinned version back; the weekly check brings it forward again.
- The engine and the models follow the app: a release that changes pipeline/requirements.txt or
  pipeline/models.lock.json sends you to the setup page (engine.py, models.py).

The last answers are kept in <data>/updates.json, so a slow or blocked network costs one try a day.
Standard library only.
"""
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

import engine
import report

DAY = 24 * 3600
STATE_FILE = lambda: engine.SUPPORT / "updates.json"            # noqa: E731  (follows $PIANPIAN_HOME)
LOCK = threading.Lock()


def _load() -> dict:
    try:
        return json.loads(STATE_FILE().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    STATE_FILE().parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE().write_text(json.dumps(state, indent=1), encoding="utf-8")


def clean_version(tag: str) -> str:
    """The number inside a release tag: 'v0.2.0' and 'pianpian-v0.2.0' (release-please names tags after the
    package) both give '0.2.0'. A tag without one stays as it is."""
    m = re.search(r"\d+\.\d+\.\d+", tag or "")
    return m[0] if m else (tag or "")


def version_tuple(v: str) -> tuple:
    """'0.12.1' -> (0, 12, 1); anything that isn't a version sorts first."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else (-1,)


def newer(latest: str, current: str) -> bool:
    return current != "dev" and version_tuple(latest) > version_tuple(current)


def check_app(current: str, force: bool = False) -> dict | None:
    """The latest release, if it is newer than `current`: {version, url, notes, download}. Asks GitHub once a day."""
    with LOCK:
        state = _load()
        if force or time.time() - state.get("appChecked", 0) > DAY:
            try:
                req = Request(f"https://api.github.com/repos/{report.REPO}/releases/latest", headers={"Accept": "application/vnd.github+json"})
                rel = json.load(urlopen(req, timeout=10))
                asset = next((a["browser_download_url"] for a in rel.get("assets", []) if a["name"].endswith("-macOS.zip")), None)
                state["app"] = {"version": clean_version(rel["tag_name"]), "url": rel["html_url"], "download": asset,
                                "notes": "\n".join((rel.get("body") or "").splitlines()[:12])}
            except (OSError, ValueError, KeyError):
                pass                                          # offline, rate-limited or no release yet: try again tomorrow
            state["appChecked"] = time.time()
            _save(state)
        app = state.get("app")
    return app if app and newer(app["version"], current) else None


def ytdlp_due() -> bool:
    """A week since the downloader was last updated, and the engine is the app's own (not a developer's .venv)."""
    installed = Path(engine.python()).is_relative_to(engine.data_dir())
    return installed and time.time() - _load().get("ytdlpUpdated", 0) > 7 * DAY


def update_ytdlp_cmd() -> list[str] | None:
    """The command that updates yt-dlp inside the engine, or None without uv."""
    exe = engine.uv()
    return [exe, "pip", "install", "--python", engine.python(), "--upgrade", "yt-dlp"] if exe else None


def mark_ytdlp_updated() -> None:
    with LOCK:
        state = _load()
        state["ytdlpUpdated"] = time.time()
        _save(state)


def ytdlp_version() -> str:
    try:
        return subprocess.run([engine.python(), "-c", "import yt_dlp.version as v; print(v.__version__)"],
                              capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""
