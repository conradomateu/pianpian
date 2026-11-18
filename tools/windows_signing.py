"""SignPath's exact allowlist and byte-preservation checks; no credentials or signing keys here."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from build_app import ROOT

APP = ROOT / "dist/Pianpian"
WORK = ROOT / "scratch/windows-signing"
OWN = (
    "Pianpian.exe",
    "_internal/pipeline/bin/pianpian-align.exe",
    "_internal/pipeline/bin/pianpian-sensevoice.exe",
    "_internal/pipeline/bin/pianpian-sensevoice-avx2.exe",
)


def hashes(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def uninstaller() -> Path:
    files = list((ROOT / "build/windows-uninstaller").glob("uninst-*.e*"))
    if len(files) != 1:
        raise RuntimeError("Expected exactly one Inno uninstaller")
    return files[0]


def prepare() -> None:
    snapshot = hashes(APP)
    missing = set(OWN) - snapshot.keys()
    unknown = [p for p in snapshot if Path(p).name.lower().startswith("pianpian")
               and p.lower().endswith((".exe", ".dll", ".pyd")) and p not in OWN]
    if missing or unknown:
        raise RuntimeError(f"Update the signing allowlist: missing={missing}, unknown={unknown}")
    shutil.rmtree(WORK, ignore_errors=True)
    payload = WORK / "unsigned"
    payload.mkdir(parents=True)
    for relative in OWN:
        shutil.copyfile(APP / relative, payload / Path(relative).name)
    shutil.copyfile(uninstaller(), payload / "uninstaller.exe")
    (WORK / "before.json").write_text(json.dumps(snapshot), encoding="utf-8")


def apply() -> None:
    signed = WORK / "signed"
    expected = {Path(p).name for p in OWN} | {"uninstaller.exe"}
    if set(hashes(signed)) != expected:
        raise RuntimeError("Signed response does not match the executable allowlist")
    for relative in OWN:
        shutil.copyfile(signed / Path(relative).name, APP / relative)
    shutil.copyfile(signed / "uninstaller.exe", uninstaller())
    preserve()


def preserve() -> None:
    before = json.loads((WORK / "before.json").read_text(encoding="utf-8"))
    after = hashes(APP)
    if before.keys() != after.keys() or any(after[p] != h for p, h in before.items() if p not in OWN):
        raise RuntimeError("Signing changed files outside Pianpian's allowlist (including third-party signatures)")


def verify_package(installed: Path | None = None) -> None:
    preserve()
    expected = hashes(APP)
    with zipfile.ZipFile(ROOT / "dist/Pianpian-Windows.zip") as archive:
        entries = [i for i in archive.infolist() if not i.is_dir()]
        actual = {i.filename: hashlib.sha256(archive.read(i)).hexdigest() for i in entries}
        if len(entries) != len(actual) or actual != {f"Pianpian/{p}": h for p, h in expected.items()}:
            raise RuntimeError("ZIP does not contain exactly the signed app")
    if installed is not None:
        actual = hashes(installed)
        if any(actual.get(p) != h for p, h in expected.items()):
            raise RuntimeError("Installer did not preserve the signed app and third-party files")
        extras = actual.keys() - expected.keys()
        if extras - {"unins000.exe", "unins000.dat", "unins000.msg"} or "unins000.exe" not in extras:
            raise RuntimeError("Unexpected installed files or missing uninstaller")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "apply", "verify"])
    parser.add_argument("--installed", type=Path)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare()
    elif args.stage == "apply":
        apply()
    else:
        verify_package(args.installed)
