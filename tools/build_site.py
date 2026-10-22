"""Build the website into _site/: the landing page, and the app itself as a live demo.

    python3 tools/build_site.py            # _site/
    python3 tools/build_site.py --serve    # and serve it at http://127.0.0.1:8765 (with byte ranges, so video seeks)

The demo is app.html?demo running on demo/library/ (made by tools/demo/make_demo.py). Its API
answers are written here by server.py's own functions, so the demo shows what the app shows.
The version and the download link come from the repository, so every release rebuilds the site
(.github/workflows/site.yml). Standard library only.
"""
import functools
import html
import http.server
import io
import json
import re
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_site"
sys.path.insert(0, str(ROOT))
from report import REPO  # noqa: E402  (one place for the repository name)
sys.path.insert(0, str(ROOT / "tools" / "demo"))
from scenes import APPLE  # noqa: E402  (the same logo as on the demo video's button)


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


def testimonials() -> str:
    """The "What learners say" section from site/testimonials.json: [{quote, name, about, url?}], real ones only.
    An empty list leaves the section out."""
    try:
        items = json.loads((ROOT / "site" / "testimonials.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        items = []
    if not items:
        return ""
    cards = []
    for t in items:
        name = html.escape(t["name"])
        who = f'<a href="{html.escape(t["url"])}" rel="noopener">{name}</a>' if t.get("url") else name
        cards.append(f'      <figure class="quote"><p>{html.escape(t["quote"])}</p><footer><span class="av">{html.escape(t["name"][:1].upper())}</span>'
                     f'<span><b>{who}</b><br>{html.escape(t.get("about", ""))}</span></footer></figure>')
    return ('  <section id="people">\n    <h2 class="sec">What learners say</h2>\n    <div class="quotes">\n'
            + "\n".join(cards) + "\n    </div>\n  </section>\n")


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
        elif f.is_file() and f.name != "testimonials.json":
            text = f.read_text(encoding="utf-8") if f.suffix in (".html", ".txt", ".xml", ".json") else None
            if text is None:
                shutil.copy2(f, OUT / f.name)
            else:
                text = text.replace("{{VERSION}}", ver).replace("{{REPO}}", REPO).replace("{{APPLE}}", APPLE).replace("{{TESTIMONIALS}}", testimonials())
                (OUT / f.name).write_text(text, encoding="utf-8")
    (OUT / ".nojekyll").touch()                           # serve the files as they are
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"_site/: version {ver}, {size / 1e6:.1f} MB")


class RangedHandler(http.server.SimpleHTTPRequestHandler):
    """http.server with byte ranges (Chrome can't seek a video without them; GitHub Pages has them), and quiet."""

    def log_message(self, *a):
        pass

    def send_head(self):
        m = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        path = Path(self.translate_path(self.path))
        if not m or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        start, end = int(m[1]), min(int(m[2] or size - 1), size - 1)
        with path.open("rb") as f:
            f.seek(start)
            body = f.read(end - start + 1)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return io.BytesIO(body)


def server(port: int) -> http.server.ThreadingHTTPServer:
    """_site/ served on 127.0.0.1:port (0 = any free port), in a background thread."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(RangedHandler, directory=str(OUT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    main()
    if "--serve" in sys.argv:
        srv = server(8765)
        print("http://127.0.0.1:8765/  (Ctrl+C to stop)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            srv.shutdown()
