"""Build Pianpian for Windows: dist/Pianpian (PyInstaller onedir), Pianpian-Windows.zip and the installer.

    python dev.py build                     # on Windows; needs uv and, for the installer, Inno Setup 6
    python tools/build_app_windows.py --no-installer

The same files as the Mac build (tools/build_app.py, whose run() and version() this reuses): the
window (launcher.py with pywebview), the server, the pages, the logo, the pipeline scripts, both locks,
uv.exe and a VERSION file. PyInstaller and pywebview run in a throwaway environment pinned below, as on
macOS, so this needs only Python 3.12 and uv, not the repository's .venv. The engine, the GPU runtimes and the models are NOT inside: the first run
installs them into %LOCALAPPDATA%\\Pianpian, exactly like the macOS build.

The installer (tools/windows/pianpian.iss, Inno Setup 6) is per-user and needs no admin rights.
It does not fetch the WebView2 runtime: the evergreen bootstrapper link always serves the newest
build, so a pinned SHA-256 would go stale. The requirement is documented instead (Windows 11
includes WebView2). PyInstaller writes nothing to the repository root (--workpath/--specpath
go under build/).
"""
import argparse
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

from build_app import ICON as LOGO, PIPELINE_SKIP, PYINSTALLER, PYWEBVIEW, ROOT, run, version

DIST, BUILD = ROOT / "dist", ROOT / "build"
STAGE = BUILD / "windows"
ICON = ROOT / "design" / "icons" / "Pianpian.ico"   # built into Pianpian.exe and Setup.exe; pywebview takes the window icon from the exe
ISS = ROOT / "tools" / "windows" / "pianpian.iss"
SETUP = DIST / "Pianpian-Windows-Setup.exe"
# PYINSTALLER, PYWEBVIEW (tools/build_app.py): the green windows.yml run of 7 Nov 2026 logged PyInstaller 6.22.3 and
# hooks-contrib 2026.9; pywebview's version is not printed there: 6.2.1 is what the same resolution gives on 7 Nov 2026
DATAS = [("app.html", "."), ("setup.html", "."), ("assets", "assets"), (str(LOGO), "design/icons"), ("LICENSE", ".")]


def uv_exe() -> Path:
    for p in (shutil.which("uv"), ROOT / ".venv" / "Scripts" / "uv.exe"):
        if p and Path(p).is_file():
            return Path(p)
    sys.exit("uv.exe was not found (pip install uv, or run python dev.py engine first)")


def pyinstaller(debug_console: bool) -> None:
    """dist/Pianpian: the onedir build. The stage keeps the files the app reads at run time, laid out
    as in the repository; uv.exe goes in so a machine without Python can still install the engine."""
    shutil.rmtree(STAGE, ignore_errors=True)
    stage = STAGE / "stage"
    shutil.copytree(ROOT / "pipeline", stage / "pipeline", ignore=PIPELINE_SKIP)
    (stage / "VERSION").write_text(version() + "\n", encoding="utf-8")
    datas = DATAS + [(str(stage / "pipeline"), "pipeline"), (str(stage / "VERSION"), ".")]
    # pipeline/ (links, models, …) is not on PyInstaller's path: it ships as data, and engine.py puts it on sys.path
    args = ["--noconfirm", "--clean", "--onedir", "--name", "Pianpian", "--icon", ICON,
            "--distpath", DIST, "--workpath", BUILD / "pyi-win", "--specpath", BUILD,
            "--hidden-import", "webview.platforms.edgechromium"]
    if not debug_console:
        args.append("--windowed")
    for src, dest in datas:
        args += ["--add-data", f"{(ROOT / src) if not Path(src).is_absolute() else src};{dest}"]
    uv = uv_exe()
    args += ["--add-binary", f"{uv};."]
    run(uv, "run", "--isolated", "--no-project", "--python", "3.12", "--with", PYINSTALLER, "--with", PYWEBVIEW,
        "pyinstaller", *args, ROOT / "launcher.py", cwd=ROOT)


def zip_app() -> Path:
    out = DIST / "Pianpian-Windows.zip"
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((DIST / "Pianpian").rglob("*")):
            z.write(p, Path("Pianpian") / p.relative_to(DIST / "Pianpian"))
    return out


def installer() -> Path | None:
    """dist/Pianpian-Windows-Setup.exe, when Inno Setup 6 is installed (the GitHub windows runners have it)."""
    iscc = (shutil.which("iscc") or shutil.which("ISCC")
            or next((str(p) for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
                                      Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
                                      Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe") if p.is_file()), None))
    if not iscc:
        print("Inno Setup 6 was not found: dist/Pianpian and the zip only (winget install JRSoftware.InnoSetup)", flush=True)
        return None
    run(iscc, f"/DMyAppVersion={version()}", f"/DMySourceDir={DIST / 'Pianpian'}", f"/DMyOutputDir={DIST}",
        f"/DMyIcon={ICON}", ISS)
    return SETUP


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-installer", action="store_true", help="PyInstaller and the zip only")
    ap.add_argument("--debug-console", action="store_true", help="keep a console window for logs while testing")
    a = ap.parse_args()
    if sys.platform != "win32":
        sys.exit("the Windows build must run on Windows")
    t0 = time.time()
    DIST.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)
    SETUP.unlink(missing_ok=True)       # an older installer must not pass for this run's
    pyinstaller(a.debug_console)
    built = [DIST / "Pianpian" / "Pianpian.exe", zip_app()]
    if not a.no_installer:
        built.append(installer())
    for p in filter(None, built):
        print(f"built {p.relative_to(ROOT)} ({p.stat().st_size / 1e6:.1f} MB)", flush=True)
    print(f"done in {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
