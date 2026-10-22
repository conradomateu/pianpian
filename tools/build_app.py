"""Build Pianpian.app, the one people download: dist/Pianpian.app and dist/Pianpian-macOS.zip.

    python3 dev.py build          # needs macOS on Apple Silicon, uv, and Xcode's command-line tools (swiftc)

The window (launcher.py with pywebview) is frozen with PyInstaller, with the server, the pages, the
pipeline scripts, both locks, the compiled OCR helper, uv and the version inside. The engine and the
models are not: the app installs them on first run (engine.py, setup.html), which keeps the download
small. The bundle is signed ad hoc, which Apple Silicon needs to run it at all; without a paid Developer
ID, macOS asks once before opening it (System Settings → Privacy & Security → Open Anyway).
The GitHub release workflow runs this and attaches the zip to each release.
"""
import json
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST, BUILD = ROOT / "dist", ROOT / "build"
APP = DIST / "Pianpian.app"
ICON = ROOT / "design" / "icons" / "20-pianpian-watermelon.svg"
PIPELINE_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "*.sh", "bin")
EXCLUDE = ["tkinter", "unittest", "pydoc_data", "lib2to3", "test", "idlelib", "ensurepip", "distutils"]


def run(*cmd, **kw):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def version() -> str:
    try:
        return json.loads((ROOT / ".release-please-manifest.json").read_text())["."]
    except (OSError, KeyError, ValueError):
        return re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)[1]


def icon(tmp: Path) -> Path:
    """AppIcon.icns from the SVG logo, with what macOS has (tools/svg2png.swift and iconutil)."""
    run("swiftc", "-O", ROOT / "tools" / "svg2png.swift", "-o", tmp / "svg2png")
    iconset = tmp / "AppIcon.iconset"
    iconset.mkdir()
    for s in (16, 32, 128, 256, 512):
        run(tmp / "svg2png", ICON, iconset / f"icon_{s}x{s}.png", s, stdout=subprocess.DEVNULL)
        run(tmp / "svg2png", ICON, iconset / f"icon_{s}x{s}@2x.png", s * 2, stdout=subprocess.DEVNULL)
    run("iconutil", "-c", "icns", iconset, "-o", tmp / "AppIcon.icns")
    return tmp / "AppIcon.icns"


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("Pianpian.app is built on macOS")
    ver = version()
    uv = shutil.which("uv")
    if not uv:
        sys.exit("needs uv (brew install uv)")
    shutil.rmtree(APP, ignore_errors=True)
    BUILD.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        icns = icon(tmp)
        # the files the app reads at run time, laid out as in the repository
        stage = tmp / "stage"
        shutil.copytree(ROOT / "pipeline", stage / "pipeline", ignore=PIPELINE_SKIP)
        (stage / "pipeline" / "bin").mkdir()
        run("swiftc", "-O", ROOT / "pipeline" / "ocr_frames.swift", "-o", stage / "pipeline" / "bin" / "ocr_frames")
        (stage / "VERSION").write_text(ver + "\n")
        datas = [("app.html", "."), ("setup.html", "."), ("assets", "assets"), (str(ICON), "design/icons"),
                 (str(stage / "pipeline"), "pipeline"), (str(stage / "VERSION"), ".")]
        args = ["--noconfirm", "--clean", "--windowed", "--name", "Pianpian", "--icon", icns,
                "--osx-bundle-identifier", "app.pianpian", "--distpath", DIST, "--workpath", BUILD / "pyi", "--specpath", BUILD]
        for src, dest in datas:
            args += ["--add-data", f"{(ROOT / src) if not Path(src).is_absolute() else src}:{dest}"]
        args += ["--add-binary", f"{uv}:."]
        for mod in EXCLUDE:
            args += ["--exclude-module", mod]
        # a clean, throwaway environment with just what the window needs (the same pywebview as tools/make_app.sh)
        run("uv", "run", "--isolated", "--no-project", "--python", "3.12", "--with", "pyinstaller>=6.10", "--with", "pywebview>=6.2",
            "pyinstaller", *args, ROOT / "launcher.py", cwd=ROOT)
    shutil.rmtree(DIST / "Pianpian", ignore_errors=True)            # the onedir copy next to the .app
    plist = APP / "Contents" / "Info.plist"
    info = plistlib.loads(plist.read_bytes())
    info.update({"CFBundleDisplayName": "Pianpian", "CFBundleShortVersionString": ver, "CFBundleVersion": ver,
                 "LSMinimumSystemVersion": "14.0", "NSHighResolutionCapable": True, "LSApplicationCategoryType": "public.app-category.education",
                 "NSHumanReadableCopyright": "Pianpian 片片 · MIT licence"})
    plist.write_bytes(plistlib.dumps(info))
    run("codesign", "--force", "--deep", "--sign", "-", APP)       # ad hoc: required on Apple Silicon
    zip_path = DIST / "Pianpian-macOS.zip"
    zip_path.unlink(missing_ok=True)
    run("ditto", "-c", "-k", "--keepParent", APP, zip_path)       # ditto keeps the bundle's links and signature
    size = sum(f.stat().st_size for f in APP.rglob("*") if f.is_file())
    print(f"\n{APP.relative_to(ROOT)}: {size / 1e6:.0f} MB · {zip_path.relative_to(ROOT)}: {zip_path.stat().st_size / 1e6:.0f} MB · v{ver}")


if __name__ == "__main__":
    main()
