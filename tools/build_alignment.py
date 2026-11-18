"""Build the tiny word-link helper against pinned llama.cpp headers, with no second runtime or model."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from build_sensevoice import _fetch, digest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "tools" / "native" / "alignment"
sys.path.insert(0, str(ROOT / "pipeline"))
import runtimes  # noqa: E402 (the native struct ABI must match the shipped runtime pin)


def check_runtime_pin(lock: dict) -> None:
    if lock["release"] != runtimes.RELEASES["llama"]:
        raise RuntimeError("Alignment headers and translation runtime have different ABI releases; update and verify them together")


def build(output: Path, *, cache_dir: Path | None = None, jobs: int = 2) -> Path:
    if not shutil.which("cmake"):
        raise RuntimeError("Building word links requires CMake >= 3.21 and a C++17 compiler")
    if jobs < 1:
        raise ValueError("Build jobs must be positive")
    output = Path(output).resolve()
    cache = Path(cache_dir or ROOT / "scratch" / "build" / "alignment").resolve()
    headers, build_dir = cache / "headers", cache / "build"
    lock = json.loads((NATIVE / "sources.lock.json").read_text(encoding="utf-8"))
    check_runtime_pin(lock)
    entries = [{**item, "local": item["name"], "repo": "ggml-org/llama.cpp", "commit": lock["commit"]} for item in lock["files"]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        list(pool.map(lambda entry: _fetch(entry, headers), entries))
    subprocess.run(["cmake", "-S", str(NATIVE), "-B", str(build_dir), f"-DHEADERS={headers}", "-DCMAKE_BUILD_TYPE=Release"], check=True)
    subprocess.run(["cmake", "--build", str(build_dir), "--config", "Release", "--parallel", str(jobs)], check=True)
    subprocess.run(["ctest", "--test-dir", str(build_dir), "-C", "Release", "--output-on-failure"], check=True)
    executable = build_dir / "bin" / ("pianpian-align.exe" if os.name == "nt" else "pianpian-align")
    subprocess.run([str(executable), "--help"], check=True, capture_output=True)
    macos_minimum = None
    if sys.platform == "darwin":
        commands = subprocess.check_output(["otool", "-l", str(executable)], text=True)
        minimum = re.search(r"cmd LC_BUILD_VERSION\s+cmdsize \d+\s+platform \d+\s+minos ([\d.]+)", commands)
        if not minimum or tuple(int(n) for n in minimum[1].split(".")[:2]) > (14, 0):
            raise RuntimeError("Word-link executable exceeds Pianpian's macOS 14 minimum")
        macos_minimum = minimum[1]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".new")
    shutil.copy2(executable, temporary)
    temporary.replace(output)
    (output.parent / "alignment-NOTICES.txt").write_text(
        f"Pianpian middle-layer word links: llama.cpp {lock['release']} headers ({lock['commit']}).\n\n"
        + (headers / "LICENSE").read_text(encoding="utf-8"), encoding="utf-8")
    manifest = {"llama_release": lock["release"], "llama_commit": lock["commit"], "cpu_only": True,
                "executable_sha256": digest(output.read_bytes()), "executable_bytes": output.stat().st_size,
                "macos_minimum": macos_minimum, "sources_sha256": digest((NATIVE / "sources.lock.json").read_bytes()),
                "adapter_sha256": {name: digest((NATIVE / name).read_bytes()) for name in ("main.cpp", "CMakeLists.txt", "windows.manifest", "protocol_test.cpp")}}
    (output.parent / "alignment-build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "pipeline" / "bin" / ("pianpian-align.exe" if os.name == "nt" else "pianpian-align"))
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    print(build(args.output, cache_dir=args.cache, jobs=args.jobs))
