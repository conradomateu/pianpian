#!/usr/bin/env python3
"""Pianpian's task runner: the same commands on macOS, Windows and in CI.

    python dev.py engine      # the pipeline's environment (.venv, group "runtime"): server.py finds it
    python dev.py version     # the next release's version and why: patch, minor or major, from the commits since the last one
    python dev.py lock        # pin the engine's packages (both platforms) and the models (pipeline/models.lock.json)
    python dev.py check       # lint + test: what CI runs on every push
    python dev.py lint        # ruff (real mistakes only) + node --check on the JavaScript
    python dev.py test        # pytest (tests/)
    python dev.py serve       # the app at http://127.0.0.1:8770
    python dev.py app         # a dev app that runs this checkout (macOS: ~/Applications; Windows: launcher.py)
    python dev.py build       # the real Pianpian.app and Pianpian-macOS.zip in dist/ (what releases ship)
    python dev.py site        # the website into _site/ (landing page + live demo)
    python dev.py preview     # build it and serve it at http://127.0.0.1:8765
    python dev.py shots       # README and website screenshots from the demo (needs Chrome or Brave)

Standard library only. Tools run through uv (pyproject.toml); uv is found on PATH or in .venv. From
China, set UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple first.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"
UV = (shutil.which("uv.exe" if WINDOWS else "uv")
      or str(ROOT / ".venv" / ("Scripts/uv.exe" if WINDOWS else "bin/uv")))


def run(*cmd: str) -> None:
    print("$", " ".join(cmd), flush=True)
    if subprocess.run(cmd, cwd=ROOT).returncode:
        sys.exit(1)


def lint() -> None:
    run(UV, "run", "--group", "dev", "ruff", "check", ".")
    if shutil.which("node"):
        for js in sorted((ROOT / "assets").glob("*.js")):
            run("node", "--check", str(js.relative_to(ROOT)))
    else:
        print("node not found: JavaScript syntax not checked")


def test() -> None:
    run(UV, "run", "--group", "dev", "pytest", "-q")


def lock() -> None:
    """Pin the engine's packages with hashes for both platforms (uv resolves x86_64-pc-windows-msvc from
    any machine; not tried from a Mac yet), then every model file of every platform in
    pipeline/models.lock.json. The hashes hold whether the packages come from PyPI or a mirror."""
    for platform, name, note in (("aarch64-apple-darwin", "requirements.txt", ""),
                                 ("x86_64-pc-windows-msvc", "requirements-windows.txt", " for Windows x64")):
        out = ROOT / "pipeline" / name
        run(UV, "pip", "compile", "pyproject.toml", "--group", "runtime", "--python-version", "3.12", "--python-platform", platform,
            "--generate-hashes", "--no-annotate", "--no-header", "-q", "-o", str(out.relative_to(ROOT)))
        out.write_text("# The engine's packages" + note + ", pinned with hashes. Made by `python dev.py lock` from pyproject.toml (group \"runtime\").\n"
                       + out.read_text(encoding="utf-8"), encoding="utf-8")
    run(sys.executable, "pipeline/models.py", "lock")          # and every model file, pinned on both sites


def app() -> None:
    if WINDOWS:
        run(UV, "run", "--group", "runtime", "--group", "desktop", sys.executable, "launcher.py")
    else:
        run("sh", "tools/make_app.sh")


TASKS = {
    "lint": lint,
    "test": test,
    "check": lambda: (lint(), test()),
    "engine": lambda: run(UV, "sync", "--group", "runtime", *(["--group", "desktop"] if WINDOWS else [])),
    "lock": lock,
    "version": lambda: run(sys.executable, "tools/next_version.py"),
    "serve": lambda: run(sys.executable, "server.py"),
    "app": app,
    "build": lambda: run(sys.executable, "tools/build_app.py"),
    "site": lambda: run(sys.executable, "tools/build_site.py"),
    "preview": lambda: run(sys.executable, "tools/build_site.py", "--serve"),
    "shots": lambda: run(sys.executable, "tools/shots.py"),
}

if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else ""
    if task not in TASKS:
        sys.exit(__doc__)
    TASKS[task]()
