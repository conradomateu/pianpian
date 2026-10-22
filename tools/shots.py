"""Screenshots of the app for the README and the website, taken from the demo: site/shots/*.png.

    python3 dev.py shots

Builds _site/ (tools/build_site.py), serves it on a free port, and drives headless Chrome (or
Brave) over its DevTools pipe: open the demo at a moment, wait until the video shows that frame,
optionally hover a word or open a menu, then capture. Standard library only. Run it again after
changing the look.
"""
import base64
import functools
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "shots"
BROWSERS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium"]
W, H = 1440, 680
# name: (seconds into the demo, colour scheme, what to do before the capture)
SHOTS = {
    "app-dark": (13.2, "dark", None),
    "app-light": (24.6, "light", None),
    "word": (13.2, "dark", ("hover", '#player .w[data-w]:nth-of-type(5)')),
    "grammar": (13.2, "light", ("open", "Grammar")),
}
# resolves once the video has painted the frame at time T (or after 3 s, whatever happens)
READY = """new Promise(done => {
  const end = Date.now() + 8000, go = () => {
    const v = window.player && player.video;
    if (v && v.readyState >= 2 && Math.abs(v.currentTime - T) < 0.05 && !v.seeking) {
      const t = setTimeout(done, 3000);
      v.requestVideoFrameCallback ? v.requestVideoFrameCallback(() => { clearTimeout(t); setTimeout(done, 400); }) : setTimeout(done, 600);
      if (v.paused) v.currentTime = T + 0.001;           // a seek makes sure a new frame is presented
    } else if (Date.now() < end) setTimeout(go, 100); else done();
  }; go();
})"""


class Chrome:
    """Just enough of the DevTools protocol over --remote-debugging-pipe (fd 3 in, fd 4 out)."""

    def __init__(self, exe: str, profile: str):
        to_r, to_w = os.pipe()
        self.from_r, from_w = os.pipe()
        args = [exe, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={profile}", "--hide-scrollbars", "--mute-audio",
                "--no-first-run", f"--window-size={W},{H}", "--force-device-scale-factor=2", "about:blank"]
        # the pipes come in as stdin/stdout; sh moves them to fds 3 and 4, where Chrome looks for them
        self.proc = subprocess.Popen(["sh", "-c", 'exec "$@" 3<&0 4>&1 </dev/null >/dev/null 2>&1', "sh", *args], stdin=to_r, stdout=from_w)
        os.close(to_r)
        os.close(from_w)
        self.to_w = to_w
        self.out, self.buf, self.n, self.session = os.fdopen(self.to_w, "wb"), b"", 0, None

    def call(self, method: str, **params):
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params, **({"sessionId": self.session} if self.session else {})}
        self.out.write(json.dumps(msg).encode() + b"\0")
        self.out.flush()
        while True:
            while b"\0" not in self.buf:
                chunk = os.read(self.from_r, 1 << 20)
                if not chunk:
                    raise RuntimeError("Chrome closed the pipe")
                self.buf += chunk
            raw, self.buf = self.buf.split(b"\0", 1)
            reply = json.loads(raw)
            if reply.get("id") == self.n:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})

    def js(self, expr: str):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value")

    def close(self):
        self.proc.terminate()
        self.proc.wait()


def main() -> None:
    exe = next((b for b in BROWSERS if Path(b).exists()), None)
    if not exe:
        sys.exit("needs Chrome, Brave or Chromium")
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_site.py")], check=True)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT / "_site")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:           # a fresh profile: default settings, nothing of yours
        c = Chrome(exe, profile)
        try:
            page = next(t for t in c.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
            c.session = c.call("Target.attachToTarget", targetId=page["targetId"], flatten=True)["sessionId"]
            c.call("Page.enable")
            for name, (t, scheme, action) in SHOTS.items():
                c.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
                c.call("Page.navigate", url=f"http://127.0.0.1:{srv.server_port}/app.html?demo#v=pianpian-day&t={t}")
                c.js("new Promise(r => setTimeout(r, 300))")
                c.call("Page.reload", ignoreCache=False)        # the hash alone would not reload the page
                c.js("new Promise(r => (document.readyState === 'complete' ? r() : addEventListener('load', r)))")
                c.js(READY.replace("T", str(t)))
                if action and action[0] == "hover":
                    box = c.js(f"(() => {{ const r = document.querySelector('{action[1]}').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()")
                    c.call("Input.dispatchMouseEvent", type="mouseMoved", x=box[0], y=box[1])
                elif action and action[0] == "open":
                    c.js(f"[...document.querySelectorAll('details.dd > summary')].find(s => s.textContent.trim() === '{action[1]}').click()")
                c.js("new Promise(r => setTimeout(r, 500))")      # menus and cards fade in
                png = c.call("Page.captureScreenshot", format="png")["data"]
                (OUT / f"{name}.png").write_bytes(base64.b64decode(png))
                print(f"site/shots/{name}.png", flush=True)
        finally:
            c.close()
            srv.shutdown()


if __name__ == "__main__":
    main()
