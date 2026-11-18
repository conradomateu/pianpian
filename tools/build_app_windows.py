"""Build Pianpian for Windows: dist/Pianpian (PyInstaller onedir), Pianpian-Windows.zip and the installer.

    python dev.py build                     # needs uv, CMake, MSVC C++ tools and, for the installer, Inno Setup 6
    python tools/build_app_windows.py --no-installer

The same files as the Mac build (tools/build_app.py, whose run() and version() this reuses): the
window (launcher.py with pywebview), the server, the pages, the logo, the pipeline scripts, both locks,
the native CPU speech helper with its notices, uv.exe and a VERSION file. PyInstaller and pywebview run in a throwaway environment pinned below, as on
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
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import windows_crt

from build_app import ICON as LOGO, PIPELINE_SKIP, PYINSTALLER, PYWEBVIEW, ROOT, run, speech_payload, alignment_payload, version

DIST, BUILD = ROOT / "dist", ROOT / "build"
STAGE = BUILD / "windows"
ICON = ROOT / "design" / "icons" / "Pianpian.ico"   # built into Pianpian.exe and Setup.exe; pywebview takes the window icon from the exe
ISS = ROOT / "tools" / "windows" / "pianpian.iss"
SETUP = DIST / "Pianpian-Windows-Setup.exe"
UNINSTALLER = BUILD / "windows-uninstaller"
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
    speech, speech_data = speech_payload(STAGE / "speech", windows=True)
    alignment, alignment_data = alignment_payload(STAGE / "alignment", windows=True)
    crt = windows_crt.collect(STAGE / "crt")
    (stage / "VERSION").write_text(version() + "\n", encoding="utf-8")
    datas = DATAS + [(str(stage / "pipeline"), "pipeline"), (str(stage / "VERSION"), "."), *speech_data, *alignment_data,
                     *[(str(p), "pipeline/bin") for p in crt if p.suffix != ".dll"]]
    resource = STAGE / "version.txt"
    ver = version()
    numbers = tuple(map(int, ver.split("."))) + (0,)
    resource.write_text(
        f"VSVersionInfo(ffi=FixedFileInfo(filevers={numbers!r}, prodvers={numbers!r}, "
        "mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)), "
        "kids=[StringFileInfo([StringTable('040904B0', ["
        f"StringStruct('ProductName', 'Pianpian'), StringStruct('ProductVersion', {ver!r}), "
        f"StringStruct('FileVersion', {ver!r}), StringStruct('FileDescription', 'Pianpian'), "
        "StringStruct('OriginalFilename', 'Pianpian.exe')])]), "
        "VarFileInfo([VarStruct('Translation', [1033, 1200])])])", encoding="utf-8")
    # pipeline/ (links, models, …) is not on PyInstaller's path: it ships as data, and engine.py puts it on sys.path
    args = ["--noconfirm", "--clean", "--noupx", "--onedir", "--name", "Pianpian", "--icon", ICON,
            "--version-file", resource, "--distpath", DIST, "--workpath", BUILD / "pyi-win", "--specpath", BUILD,
            "--hidden-import", "webview.platforms.edgechromium", "--hidden-import", "ctypes"]
    if not debug_console:
        args.append("--windowed")
    for src, dest in datas:
        args += ["--add-data", f"{(ROOT / src) if not Path(src).is_absolute() else src};{dest}"]
    uv = uv_exe()
    args += ["--add-binary", f"{uv};.", "--add-binary", f"{speech};pipeline/bin", "--add-binary", f"{alignment};pipeline/bin"]
    args += ["--add-binary", f"{speech.with_name('pianpian-sensevoice-avx2.exe')};pipeline/bin"]
    for path in crt:
        if path.suffix == ".dll":
            args += ["--add-binary", f"{path};pipeline/bin"]
    run(uv, "run", "--isolated", "--no-project", "--python", "3.12", "--with", PYINSTALLER, "--with", PYWEBVIEW,
        "pyinstaller", *args, ROOT / "launcher.py", cwd=ROOT)
    for path in [*crt, speech, speech.with_name("pianpian-sensevoice-avx2.exe")]:
        packaged = DIST / "Pianpian" / "_internal" / "pipeline" / "bin" / path.name
        if not packaged.is_file() or packaged.read_bytes() != path.read_bytes():
            raise RuntimeError(f"Packaged native runtime differs from its verified build source: {path.name}")
    run(DIST / "Pianpian" / "_internal" / "pipeline" / "bin" / "pianpian-sensevoice.exe", "--help")
    run(DIST / "Pianpian" / "_internal" / "pipeline" / "bin" / "pianpian-align.exe", "--help")


def zip_app() -> Path:
    out = DIST / "Pianpian-Windows.zip"
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((DIST / "Pianpian").rglob("*")):
            z.write(p, Path("Pianpian") / p.relative_to(DIST / "Pianpian"))
    return out


def installer(*, signed_uninstaller: bool = False, prepare: bool = False) -> Path:
    """dist/Pianpian-Windows-Setup.exe; a normal build fails rather than silently omitting it."""
    iscc = (shutil.which("iscc") or shutil.which("ISCC")
            or next((str(p) for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
                                      Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
                                      Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe") if p.is_file()), None))
    if not iscc:
        raise RuntimeError("Inno Setup 6 is required for the installer (winget install JRSoftware.InnoSetup), or use --no-installer")
    args = [iscc, f"/DMyAppVersion={version()}", f"/DMySourceDir={DIST / 'Pianpian'}", f"/DMyOutputDir={DIST}",
            f"/DMyIcon={ICON}"]
    if signed_uninstaller or prepare:
        args.append(f"/DMySignedUninstallerDir={UNINSTALLER}")
    if prepare:
        shutil.rmtree(UNINSTALLER, ignore_errors=True)
        UNINSTALLER.mkdir(parents=True)
        # Inno's documented external-signing mode stops here until its generated PE is signed.
        result = subprocess.run([*map(str, args), str(ISS)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        files = list(UNINSTALLER.glob("uninst-*.e*"))
        if result.returncode == 0 or len(files) != 1 or "please attach your digital signature" not in result.stdout:
            raise RuntimeError(f"Inno did not stop at the expected uninstaller-signing boundary:\n{result.stdout}")
        return files[0]
    run(*args, ISS)
    return SETUP


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-installer", action="store_true", help="PyInstaller and the zip only")
    ap.add_argument("--debug-console", action="store_true", help="keep a console window for logs while testing")
    ap.add_argument("--prepare-signing", action="store_true", help="build app and stage Inno uninstaller for SignPath")
    ap.add_argument("--package-signed", action="store_true", help="package an already verified app and signed uninstaller")
    a = ap.parse_args()
    if a.prepare_signing and (a.package_signed or a.no_installer) or a.package_signed and a.no_installer:
        ap.error("signing stages cannot be combined with each other or --no-installer")
    if sys.platform != "win32":
        sys.exit("the Windows build must run on Windows")
    t0 = time.time()
    DIST.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)
    SETUP.unlink(missing_ok=True)       # an older installer must not pass for this run's
    if not a.package_signed:
        pyinstaller(a.debug_console)
    if a.prepare_signing:
        installer(prepare=True)
        return
    built = [DIST / "Pianpian" / "Pianpian.exe", zip_app()]
    if not a.no_installer:
        built.append(installer(signed_uninstaller=True) if a.package_signed else installer())
    for p in filter(None, built):
        print(f"built {p.relative_to(ROOT)} ({p.stat().st_size / 1e6:.1f} MB)", flush=True)
    print(f"done in {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
