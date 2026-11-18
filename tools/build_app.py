"""Build Pianpian.app, the one people download: dist/Pianpian.app, Pianpian-macOS.dmg and Pianpian-macOS.zip.

    python3 dev.py build          # needs macOS on Apple Silicon, uv, and Xcode's command-line tools (swiftc)
    python3 dev.py build-signed   # Developer ID + notarization; credentials in the pianpian-notary Keychain profile

The window (launcher.py with pywebview) is frozen with PyInstaller, with the server, the pages, the
pipeline scripts, both locks, the compiled OCR helper, uv and the version inside. The engine and the
models are not: the app installs them on first run (engine.py, setup.html), which keeps the download
small. The default build signs ad hoc; --signed uses Developer ID and Apple's notary service instead.
Without Developer ID and notarization, users must approve the app in System Settings → Privacy & Security.
The DMG (window and arrow: tools/dmg/) is what people open and drag to Applications; the zip is what the app's
updater and package managers will take. The GitHub release workflow runs this and attaches both to each release.
"""
import argparse
import json
import os
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
ENTITLEMENTS = ROOT / "tools" / "mac" / "entitlements.plist"
PIPELINE_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "*.sh", "bin")
EXCLUDE = ["tkinter", "unittest", "pydoc_data", "lib2to3", "test", "idlelib", "ensurepip", "distutils"]


def run(*cmd, **kw):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    try:
        return subprocess.run([str(c) for c in cmd], check=True, **kw)
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout, file=sys.stderr)
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        raise


def signing_identity() -> str:
    result = run("security", "find-identity", "-v", "-p", "codesigning", capture_output=True, text=True)
    identities = dict(re.findall(r'\b([A-Fa-f0-9]{40})\s+"(Developer ID Application:[^"]+)"', result.stdout))
    requested = os.environ.get("PIANPIAN_SIGNING_IDENTITY", "")
    if requested:
        identities = {key: name for key, name in identities.items() if requested in (key, name)}
    if len(identities) != 1:
        sys.exit("Need one valid Developer ID Application identity in Keychain. Create it in Xcode > Settings > Apple Accounts > "
                 "Manage Certificates, or select its full name/SHA-1 with PIANPIAN_SIGNING_IDENTITY if you have several.")
    return next(iter(identities))


def notarize(archive: Path, target: Path, profile: str) -> None:
    result = run("xcrun", "notarytool", "submit", archive, "--keychain-profile", profile,
                 "--wait", "--output-format", "json", capture_output=True, text=True)
    status = json.loads(result.stdout)
    print(f"Notarization: {status.get('status')} · {status.get('id')}", flush=True)
    if status.get("status") != "Accepted":
        if status.get("id"):
            run("xcrun", "notarytool", "log", status["id"], "--keychain-profile", profile)
        sys.exit("Apple has not accepted this build. Do not distribute it; see the notarization log above.")
    run("xcrun", "stapler", "staple", target)
    run("xcrun", "stapler", "validate", target)


def make_zip(path: Path) -> None:
    path.unlink(missing_ok=True)
    run("ditto", "-c", "-k", "--keepParent", APP, path)


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


DMGBUILD = "dmgbuild==1.6.7"                                       # pure Python: lays out the window itself, no Finder or screen needed


def make_dmg() -> Path:
    """dist/Pianpian-macOS.dmg: the app and a shortcut to Applications, on the picture from tools/dmg/."""
    dmg = DIST / "Pianpian-macOS.dmg"
    dmg.unlink(missing_ok=True)
    run("uv", "run", "--isolated", "--no-project", "--python", "3.12", "--with", DMGBUILD, "dmgbuild",
        "-s", ROOT / "tools" / "dmg" / "settings.py", "-D", f"app={APP}", "-D", f"icon={APP / 'Contents' / 'Resources' / 'AppIcon.icns'}",
        "Pianpian", dmg, cwd=ROOT)
    return dmg


def main(signed: bool = False) -> None:
    if sys.platform != "darwin":
        sys.exit("Pianpian.app is built on macOS")
    ver = version()
    uv = shutil.which("uv")
    if not uv:
        sys.exit("needs uv (brew install uv)")
    identity = signing_identity() if signed else "-"
    profile = os.environ.get("PIANPIAN_NOTARY_PROFILE", "pianpian-notary")
    if signed:
        # Check credentials before removing a previous build; passwords stay in Keychain.
        run("xcrun", "notarytool", "history", "--keychain-profile", profile, stdout=subprocess.DEVNULL)
    shutil.rmtree(APP, ignore_errors=True)
    BUILD.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=BUILD) as t:
        tmp = Path(t)
        icns = icon(tmp)
        # the files the app reads at run time, laid out as in the repository
        stage = tmp / "stage"
        shutil.copytree(ROOT / "pipeline", stage / "pipeline", ignore=PIPELINE_SKIP)
        (stage / "pipeline" / "bin").mkdir()
        run("swiftc", "-O", "-target", "arm64-apple-macosx14.0", ROOT / "pipeline" / "ocr_frames.swift", "-o", stage / "pipeline" / "bin" / "ocr_frames")
        (stage / "VERSION").write_text(ver + "\n")
        datas = [("app.html", "."), ("setup.html", "."), ("assets", "assets"), (str(ICON), "design/icons"),
                 (str(stage / "pipeline"), "pipeline"), (str(stage / "VERSION"), ".")]
        args = ["--noconfirm", "--clean", "--windowed", "--name", "Pianpian", "--icon", icns,
                "--osx-bundle-identifier", "app.pianpian", "--distpath", DIST, "--workpath", BUILD / "pyi", "--specpath", BUILD]
        if signed:
            args += ["--codesign-identity", identity, "--osx-entitlements-file", ENTITLEMENTS]
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
    if signed:
        # PyInstaller signs the nested code. Re-seal only the app after changing Info.plist.
        run("codesign", "--force", "--sign", identity, "--options", "runtime", "--timestamp", "--entitlements", ENTITLEMENTS, APP)
    else:
        run("codesign", "--force", "--deep", "--sign", "-", APP)
    run("codesign", "--verify", "--deep", "--strict", APP)          # fail here, not on someone's Mac
    if signed:
        submission = BUILD / "Pianpian-notarization.zip"
        make_zip(submission)
        notarize(submission, APP, profile)
        run("spctl", "--assess", "--type", "execute", "--verbose=2", APP)
    zip_path = DIST / "Pianpian-macOS.zip"
    make_zip(zip_path)                                           # include the stapled app, not the submission copy
    dmg = make_dmg()
    if signed:
        run("codesign", "--force", "--sign", identity, "--timestamp", dmg)
        notarize(dmg, dmg, profile)
        run("codesign", "--verify", "--strict", dmg)
        run("spctl", "--assess", "--type", "open", "--context", "context:primary-signature", "--verbose=2", dmg)
    size = sum(f.stat().st_size for f in APP.rglob("*") if f.is_file())
    print(f"\n{APP.relative_to(ROOT)}: {size / 1e6:.0f} MB · {dmg.relative_to(ROOT)}: {dmg.stat().st_size / 1e6:.0f} MB · "
          f"{zip_path.relative_to(ROOT)}: {zip_path.stat().st_size / 1e6:.0f} MB · v{ver}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signed", action="store_true", help="require Developer ID signing and Apple notarization")
    main(parser.parse_args().signed)
