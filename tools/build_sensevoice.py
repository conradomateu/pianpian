"""Build the pinned native ASR for release packaging, never on users' computers.

Only the CPU sources are fetched (SHA256 verified). No model, Python ML runtime,
CUDA toolkit, or GPU runtime is downloaded by this builder.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "tools" / "native" / "sensevoice"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply_patch(source: str, patch: str) -> str:
    """Apply our single-file unified diff, rejecting every mismatched context line."""
    original = source.splitlines(keepends=True)
    lines = patch.splitlines(keepends=True)
    output = []
    position = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(("--- ", "+++ ")):
            index += 1
            continue
        match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n", line)
        if not match:
            raise ValueError("Invalid native runtime patch hunk")
        start = int(match[1]) - 1
        if start < position or start > len(original):
            raise ValueError("Native runtime patch is out of order")
        output.extend(original[position:start])
        position = start
        consumed = added = 0
        index += 1
        while index < len(lines) and not lines[index].startswith("@@ "):
            entry = lines[index]
            if entry[:1] in (" ", "-"):
                if position >= len(original) or original[position] != entry[1:]:
                    raise ValueError(f"Native runtime patch context mismatch at line {position + 1}")
                position += 1
                consumed += 1
            if entry[:1] in (" ", "+"):
                output.append(entry[1:])
                added += 1
            if entry[:1] not in (" ", "+", "-"):
                raise ValueError("Invalid native runtime patch line")
            index += 1
        if consumed != int(match[2] or 1) or added != int(match[4] or 1):
            raise ValueError("Native runtime patch hunk length mismatch")
    output.extend(original[position:])
    return "".join(output)


def _fetch(entry: dict, upstream: Path) -> None:
    relative = PurePosixPath(entry["local"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid native source cache path")
    target = upstream.joinpath(*relative.parts)
    if target.is_file() and digest(target.read_bytes()) == entry["sha256"]:
        return
    url = f"https://raw.githubusercontent.com/{entry['repo']}/{entry['commit']}/{entry['path']}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(entry["size"] + 1)
            if len(data) != entry["size"] or digest(data) != entry["sha256"]:
                raise ValueError(f"Native source checksum mismatch: {entry['path']}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".download")
            temporary.write_bytes(data)
            temporary.replace(target)
            return
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(1)


def _write_changed(path: Path, data: bytes) -> None:
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def build(output: Path, *, cache_dir: Path | None = None, jobs: int = 2) -> Path:
    """Return the executable; also write notices and provenance beside it."""
    if not shutil.which("cmake"):
        raise RuntimeError("Building SenseVoice requires CMake >= 3.21 and a C++17 compiler")
    if jobs < 1:
        raise ValueError("Build jobs must be positive")
    output = Path(output).resolve()
    cache = Path(cache_dir or ROOT / "scratch" / "build" / "sensevoice").resolve()
    upstream, build_dir = cache / "upstream", cache / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    lock = json.loads((NATIVE / "sources.lock.json").read_text(encoding="utf-8"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda entry: _fetch(entry, upstream), lock["files"]))
    original = upstream / "funasr" / "sensevoice" / "funasr-sensevoice" / "funasr-sensevoice.cpp"
    modified = apply_patch(original.read_text(encoding="utf-8"), (NATIVE / "runtime.patch").read_text(encoding="utf-8"))
    _write_changed(build_dir / "funasr-sensevoice.cpp", modified.encode("utf-8"))
    subprocess.run(["cmake", "-S", str(NATIVE), "-B", str(build_dir),
                    f"-DUPSTREAM={upstream}", f"-DPYTHON_FOR_BUILD={sys.executable}",
                    "-DGIT_EXE=OFF", f"-DGGML_BUILD_COMMIT={lock['llama_commit']}",
                    "-DCMAKE_BUILD_TYPE=Release"], check=True)
    subprocess.run(["cmake", "--build", str(build_dir), "--config", "Release",
                    "--target", "pianpian-sensevoice", "sensevoice-timestamps-test",
                    "--parallel", str(jobs)], check=True)
    subprocess.run(["ctest", "--test-dir", str(build_dir), "-C", "Release", "--output-on-failure"], check=True)
    executable = build_dir / "bin" / ("pianpian-sensevoice.exe" if os.name == "nt" else "pianpian-sensevoice")
    subprocess.run([str(executable), "--help"], check=True, capture_output=True)
    version = subprocess.check_output([str(executable), "--version"], text=True).strip()
    macos_minimum = None
    if sys.platform == "darwin":
        load_commands = subprocess.check_output(["otool", "-l", str(executable)], text=True)
        minimum = re.search(r"cmd LC_BUILD_VERSION\s+cmdsize \d+\s+platform \d+\s+minos ([\d.]+)", load_commands)
        if not minimum or tuple(int(n) for n in minimum[1].split(".")[:2]) > (14, 0):
            raise RuntimeError("SenseVoice executable exceeds Pianpian's macOS 14 minimum")
        macos_minimum = minimum[1]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".new")
    shutil.copy2(executable, temporary)
    temporary.replace(output)
    miniaudio = (upstream / "funasr" / "funasr-common" / "miniaudio.h").read_text(encoding="utf-8")
    miniaudio_license = miniaudio[miniaudio.rindex("This software is available as a choice"):]
    notices = ("Pianpian SenseVoice native runtime\n"
               "Modified for structured JSON and CTC-estimated word timing. Neural weights are separate.\n\n"
               f"FunASR {lock['funasr_commit']}\n" + (upstream / "funasr" / "LICENSE").read_text(encoding="utf-8") + "\n\n"
               f"ggml/llama.cpp {lock['llama_commit']}\n" + (upstream / "llama" / "LICENSE").read_text(encoding="utf-8") + "\n\n"
               "miniaudio (included by FunASR)\n" + miniaudio_license)
    (output.parent / "sensevoice-NOTICES.txt").write_text(notices, encoding="utf-8")
    manifest = {"version": version, "executable_sha256": digest(output.read_bytes()),
                "executable_bytes": output.stat().st_size, "funasr_commit": lock["funasr_commit"],
                "llama_commit": lock["llama_commit"], "cpu_only": True,
                "macos_minimum": macos_minimum,
                "sources_sha256": digest((NATIVE / "sources.lock.json").read_bytes()),
                "adapter_sha256": {name: digest((NATIVE / name).read_bytes()) for name in
                                   ("runtime.patch", "timestamps.h", "CMakeLists.txt", "timestamps_test.cpp", "windows.manifest")}}
    (output.parent / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "pipeline" / "bin" /
                        ("pianpian-sensevoice.exe" if os.name == "nt" else "pianpian-sensevoice"))
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    print(build(args.output, cache_dir=args.cache, jobs=args.jobs))
