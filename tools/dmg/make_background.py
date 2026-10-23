"""Render tools/dmg/background.svg into tools/dmg/background.tiff: the picture behind the icons in the DMG window.

    python3 tools/dmg/make_background.py

A TIFF with a normal and a Retina (@2x) picture, which is what Finder wants. Needs Chrome, Brave or Chromium for
the drawing and macOS's tiffutil. The result is committed, so building a release needs neither.
"""
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BROWSERS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium"]


def main() -> None:
    exe = next((b for b in BROWSERS if Path(b).exists()), None)
    if not exe:
        raise SystemExit("needs Chrome, Brave or Chromium")
    with tempfile.TemporaryDirectory() as t:
        for scale, name in ((1, "bg.png"), (2, "bg@2x.png")):
            subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--force-device-scale-factor={scale}",
                            "--window-size=660,400", f"--screenshot={Path(t) / name}", (HERE / "background.svg").as_uri()],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["tiffutil", "-cathidpicheck", f"{t}/bg.png", f"{t}/bg@2x.png", "-out", str(HERE / "background.tiff")], check=True)


if __name__ == "__main__":
    main()
