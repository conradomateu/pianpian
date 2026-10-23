"""What version will the next release be, and why? Run it before you push:

    python3 dev.py version

It reads the commits since the last release and applies release-please's rules (the settings are in
release-please-config.json), so the answer is the version of the release pull request that will open.

    fix:  perf:  revert:           -> patch   0.1.0 -> 0.1.1
    feat:                          -> minor   0.1.0 -> 0.2.0
    feat!:  or  BREAKING CHANGE:   -> major   1.4.0 -> 2.0.0   (minor while the version starts with 0: bump-minor-pre-major)
    chore: docs: style: refactor: test: build: ci:    -> no release by themselves
    Release-As: 0.1.1  (a line at the end of any commit message)  -> exactly that version

The biggest change since the last release wins. Standard library only.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEAD = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<text>.+)$")
BREAKING = re.compile(r"^BREAKING[ -]CHANGE:", re.M)
FORCED = re.compile(r"^Release-As:\s*v?(\d+\.\d+\.\d+)\s*$", re.M | re.I)
LEVELS = {None: 0, "patch": 1, "minor": 2, "major": 3}


def classify(subject: str, body: str = "") -> str | None:
    """'major', 'minor', 'patch' or None (no release) for one commit message."""
    m = HEAD.match(subject)
    if not m:
        return None
    if m["bang"] or BREAKING.search(body):
        return "major"
    if m["type"] == "feat":
        return "minor"
    if m["type"] in ("fix", "perf", "revert"):
        return "patch"
    return None


def next_version(current: str, commits: list[tuple[str, str]], config: dict | None = None) -> tuple[str | None, str | None, str | None]:
    """(next version, bump, forced) for the commits since `current`. Version is None when nothing calls for a release."""
    config = config or {}
    forced = None
    for _subject, body in commits:
        if m := FORCED.search(body):
            forced = m[1]                                     # the latest one wins
    biggest = max((classify(s, b) for s, b in commits), key=LEVELS.get, default=None)
    if forced:
        return forced, biggest, forced
    if not biggest:
        return None, None, None
    major, minor, patch = (int(x) for x in current.split("."))
    pre = major == 0
    if biggest == "major" and pre and config.get("bump-minor-pre-major"):
        biggest = "minor"
    elif biggest == "minor" and pre and config.get("bump-patch-for-minor-pre-major"):
        biggest = "patch"
    if biggest == "major":
        return f"{major + 1}.0.0", biggest, None
    if biggest == "minor":
        return f"{major}.{minor + 1}.0", biggest, None
    return f"{major}.{minor}.{patch + 1}", biggest, None


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def main() -> None:
    cfg = json.loads((ROOT / "release-please-config.json").read_text())["packages"]["."]
    current = json.loads((ROOT / ".release-please-manifest.json").read_text())["."]
    last = git("log", "--grep=^chore(main): release ", "-1", "--format=%H").strip()
    raw = git("log", f"{last}..HEAD" if last else "HEAD", "--format=%h%x1f%s%x1f%b%x1e")
    commits = []
    for chunk in raw.split("\x1e"):
        if chunk.strip():
            sha, subject, body = (chunk.strip("\n").split("\x1f") + ["", ""])[:3]
            commits.append((sha.strip(), subject, body))
    print(f"Last release: {current}" + (f" ({last[:7]})" if last else ""))
    print(f"Commits since: {len(commits)}")
    for sha, subject, body in commits:
        kind = classify(subject, body)
        print(f"  {kind or '-':6} {sha} {subject[:90]}")
    version, bump, forced = next_version(current, [(s, b) for _, s, b in commits], cfg)
    print()
    if forced:
        print(f"Release-As says {forced}: that is the next version (the commits alone would be: {bump or 'no release'}).")
    elif version:
        print(f"The biggest change is a {bump}: the next version is {version}.")
        if bump == "minor" and current.startswith("0."):
            print(f"  To make it a patch ({current.rsplit('.', 1)[0]}.{int(current.split('.')[2]) + 1}) add a line 'Release-As: x.y.z' to a commit message, or use fix: instead of feat:.")
    else:
        print("Nothing here calls for a release (only chore:, docs:, style:, refactor:, test:, build: or ci: commits).")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"git failed: {e.stderr.strip()}")
