"""Build the website into _site/: the landing page, and the app itself as a live demo.

    python3 tools/build_site.py            # then: python3 -m http.server -d _site 8000

The demo is app.html?demo running on demo/library/ (made by tools/demo/make_demo.py). Its API
answers are written here by server.py's own functions, so the demo shows what the app shows.
The version and the download link come from the repository, so every release rebuilds the site
(.github/workflows/site.yml). Standard library only.
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_site"
REPO = "bytemines/pianpian"
sys.path.insert(0, str(ROOT))


def version() -> str:
    try:
        return json.loads((ROOT / ".release-please-manifest.json").read_text())["."]
    except (OSError, KeyError, ValueError):
        return re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)[1]


def demo_api(dest: Path, ver: str) -> None:
    import server
    server.CFG["library"] = ROOT / "demo" / "library"
    videos = server.library()
    for v in videos:
        v.pop("mtime", None)
        p = server.entry_path(v["id"])
        info = {**v, "lines": server.read(p / "zh.lines.txt"), "english": server.read(p / "en.lines.txt")}
        (dest / "videos").mkdir(parents=True, exist_ok=True)
        (dest / "videos" / f"{v['id']}.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    (dest / "videos.json").write_text(json.dumps(videos, ensure_ascii=False), encoding="utf-8")
    (dest / "status.json").write_text(json.dumps({"ok": True, "version": ver, "library": "demo", "engine": True,
                                                   "browsers": [], "busy": False}), encoding="utf-8")


def main() -> None:
    ver = version()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for name in ("app.html",):
        shutil.copy2(ROOT / name, OUT / name)
    shutil.copytree(ROOT / "assets", OUT / "assets")
    (OUT / "design" / "icons").mkdir(parents=True)
    for icon in ("19-pianpian-mono.svg", "20-pianpian-watermelon.svg"):     # the published logos only
        shutil.copy2(ROOT / "design" / "icons" / icon, OUT / "design" / "icons" / icon)
    shutil.copytree(ROOT / "demo" / "library", OUT / "demo" / "library", ignore=shutil.ignore_patterns(".*"))
    demo_api(OUT / "demo" / "api", ver)
    for f in (ROOT / "site").iterdir():                  # the landing page and whatever sits next to it (CNAME, images)
        if f.is_dir():
            shutil.copytree(f, OUT / f.name)
        elif f.is_file():
            text = f.read_text(encoding="utf-8") if f.suffix in (".html", ".txt", ".xml", ".json") else None
            if text is None:
                shutil.copy2(f, OUT / f.name)
            else:
                (OUT / f.name).write_text(text.replace("{{VERSION}}", ver).replace("{{REPO}}", REPO), encoding="utf-8")
    (OUT / ".nojekyll").touch()                           # serve the files as they are
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"_site/: version {ver}, {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
