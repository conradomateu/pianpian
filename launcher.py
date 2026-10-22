"""Pianpian in its own window (proof of concept for the desktop app).

    uv run --with pywebview launcher.py        # or double-click Pianpian.app, built by tools/make_app.sh

The local server runs inside this process, on 127.0.0.1 only, and the app opens in a native macOS
window (WebKit, through pywebview) instead of a browser tab. Closing the window quits everything.
The pipeline runs in the engine environment server.py finds (see ENGINE_PY there).
Log: ~/Library/Logs/Pianpian/launcher.log
"""
import logging
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
ICON = HERE / "design" / "icons" / "20-pianpian-watermelon.svg"
PORT = 8771          # not 8770, so it can run next to `python3 server.py`; fixed, so the page's saved settings persist

import engine  # noqa: E402  (stdlib only: the paths, including the logs folder)

LOG = engine.logs_dir()
logging.basicConfig(filename=LOG / "launcher.log", level=logging.INFO, format="%(asctime)s %(message)s")

try:                 # the name in the menu bar: "Pianpian", not "Python" (must happen before the window exists)
    from Foundation import NSBundle
    NSBundle.mainBundle().infoDictionary()["CFBundleName"] = "Pianpian"
except Exception:
    logging.exception("could not set the app name")

import webview       # noqa: E402  (after the name is set)
import server        # noqa: E402


def serve() -> str:
    try:
        srv = server.start(PORT)
    except OSError:  # the port is taken: any free one (the page's saved settings then start fresh)
        logging.info("port %s busy, using a free one", PORT)
        srv = server.start(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/app.html"
    logging.info("serving %s, library %s", url, server.CFG["library"])
    return url


def ready(window, url):
    """Runs once the window exists: WebKit settings and the Dock icon, then load the app and show it."""
    try:
        import time
        from AppKit import NSApplication, NSImage
        from webview.platforms.cocoa import BrowserView
        wv = None
        for _ in range(200):                     # the native view appears a moment after this callback starts
            wv = next((getattr(b, "webview", None) for b in BrowserView.instances.values()), None)
            if wv is not None:
                break
            time.sleep(0.05)
        # WebKit keeps the page's own fullscreen off inside apps; the player's ⛶ button needs it
        wv.configuration().preferences().setElementFullscreenEnabled_(True)
        icon = NSImage.alloc().initWithContentsOfFile_(str(ICON))
        if icon:
            NSApplication.sharedApplication().setApplicationIconImage_(icon)
    except Exception:
        logging.exception("macOS settings failed; the app still works, without page fullscreen")
    window.load_url(url)
    window.show()


class Api:
    """What the pages may ask of the window (window.pywebview.api in JavaScript)."""

    def pick_folder(self, start=""):
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        start = start if start and Path(start).expanduser().is_dir() else str(Path.home())
        picked = webview.windows[0].create_file_dialog(kind, directory=start)
        return picked[0] if picked else None


def main():
    url = serve()
    window = webview.create_window("Pianpian 片片", url="about:blank", width=1440, height=900, js_api=Api(),
                                   min_size=(900, 600), background_color="#14120F", hidden=True)
    webview.start(ready, (window, url))
    logging.info("window closed")


if __name__ == "__main__":
    main()
