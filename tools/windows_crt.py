"""Collect Microsoft's app-local x64 CRT from Visual Studio, never PATH or System32."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

NAMES = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")
DOCS = "https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files"
LICENSES = "https://visualstudio.microsoft.com/license-terms/"


def source() -> Path:
    override = os.environ.get("PIANPIAN_VC_REDIST_DIR")
    if override:
        candidates = [Path(override)]
    else:
        vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
        if not vswhere.is_file():
            raise RuntimeError("Visual Studio x64 CRT redistributables not found; install MSVC or set PIANPIAN_VC_REDIST_DIR to its x64 Microsoft.VC*.CRT folder")
        installs = subprocess.check_output([str(vswhere), "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).splitlines()
        candidates = [p for install in installs for p in (Path(install) / "VC/Redist/MSVC").glob("*/x64/Microsoft.VC*.CRT")]
        candidates.sort(key=lambda p: tuple(int(n) for n in p.parents[1].name.split(".") if n.isdigit()), reverse=True)
    for folder in candidates:
        if all((folder / name).is_file() for name in NAMES):
            return folder
    raise RuntimeError("Missing MSVC x64 app-local CRT files: " + ", ".join(NAMES) + "; set PIANPIAN_VC_REDIST_DIR to the Visual Studio redistributable folder")


def collect(output: Path) -> list[Path]:
    folder = source().resolve()
    payload = {}
    for name in NAMES:
        content = (folder / name).read_bytes()
        offset = struct.unpack_from("<I", content, 0x3C)[0] if len(content) >= 64 else 0
        if content[:2] != b"MZ" or content[offset:offset + 6] != b"PE\x00\x00\x64\x86":
            raise RuntimeError(f"Expected a Windows x64 PE redistributable: {folder / name}")
        payload[name] = content
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"vendor": "Microsoft", "source": str(folder), "documentation": DOCS, "license_terms": LICENSES, "files": {}}
    for name, content in payload.items():
        (output / name).write_bytes(content)
        manifest["files"][name] = {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
    # Preserve an original distribution notice when supplied by this Visual Studio installation.
    originals = [p / "Redist.txt" for p in (folder, *folder.parents[:6])]
    notice = next((p for p in originals if p.is_file()), None)
    extra = []
    if notice:
        target = output / "msvc-Redist.txt"
        shutil.copyfile(notice, target)
        extra.append(target)
    (output / "msvc-NOTICES.txt").write_text("Microsoft Visual C++ Runtime (x64)\nVendor: Microsoft Corporation\nApp-local redistributables supplied by the build's Visual Studio installation.\nOfficial redistribution documentation: " + DOCS + "\nMicrosoft license terms: " + LICENSES + "\nFile hashes and build source: msvc-manifest.json\n", encoding="utf-8")
    (output / "msvc-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return [*(output / name for name in NAMES), output / "msvc-NOTICES.txt", output / "msvc-manifest.json", *extra]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    collect(parser.parse_args().output)
