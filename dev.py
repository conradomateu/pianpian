#!/usr/bin/env python3
"""Pianpian's task runner: the same commands on your Mac and in CI.

    python3 dev.py check      # lint + test: what CI runs on every push
    python3 dev.py lint       # ruff (real mistakes only) + node --check on the JavaScript
    python3 dev.py test       # pytest (tests/)
    python3 dev.py serve      # the app at http://127.0.0.1:8770
    python3 dev.py app        # build Pianpian.app into ~/Applications (macOS)

Standard library only. Tools run through `uv run --group dev` (pyproject.toml). From China, set
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple first.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(*cmd: str) -> None:
    print("$", " ".join(cmd), flush=True)
    if subprocess.run(cmd, cwd=ROOT).returncode:
        sys.exit(1)


def lint() -> None:
    run("uv", "run", "--group", "dev", "ruff", "check", ".")
    if shutil.which("node"):
        for js in sorted((ROOT / "assets").glob("*.js")):
            run("node", "--check", str(js.relative_to(ROOT)))
    else:
        print("node not found: JavaScript syntax not checked")


def test() -> None:
    run("uv", "run", "--group", "dev", "pytest", "-q")


TASKS = {
    "lint": lint,
    "test": test,
    "check": lambda: (lint(), test()),
    "serve": lambda: run(sys.executable, "server.py"),
    "app": lambda: run("sh", "tools/make_app.sh"),
}

if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else ""
    if task not in TASKS:
        sys.exit(__doc__)
    TASKS[task]()
