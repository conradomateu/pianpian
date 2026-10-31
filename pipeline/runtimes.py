"""The pinned Windows binaries: whisper.cpp (speech) and llama.cpp (translation), and how to pick them.

    python pipeline/runtimes.py status              # JSON: this machine's backends, tools, sizes
    python pipeline/runtimes.py ensure              # download both tools (progress on stdout)
    python pipeline/runtimes.py ensure whisper      # one tool

Windows only (x64; the engine Python and the models lock are x86_64 too), but importable anywhere:
nothing here runs at import time. The archives come from the official ggml-org releases and every one
is checked against the SHA-256 written here; the running app never trusts the network. The download
itself goes through models.download(). Backends:
  cuda    NVIDIA GPU (the CUDA 12.4 builds, tested with driver 591.74)
  vulkan  any Vulkan GPU (AMD, Intel, or NVIDIA when CUDA is not chosen)
  cpu     no usable GPU, or PIANPIAN_ACCEL=cpu (also: vulkan / cuda to force one)
whisper.cpp has no Vulkan Windows asset in its official release yet, so a Vulkan-only machine uses
the CPU build for speech and the Vulkan build for translation. That gap is deliberate and visible in
`status`; a Vulkan whisper.cpp build can be added here once one is pinned.

GitHub release downloads are the weak link from mainland China. PIANPIAN_GITHUB_MIRROR is an opt-in
prefix (e.g. a proxy you trust: https://example.com/https://github.com/…); there is no default,
because a third-party proxy would see the download whenever GitHub fails. The SHA-256 pins keep the
bytes safe either way.
"""
import functools
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import models

RELEASES = {"whisper": "b5454", "llama": "b11851"}
EXES = {"whisper": ("whisper-cli.exe", "main.exe"), "llama": ("llama-server.exe",)}
BASE = "https://github.com/ggml-org/{repo}/releases/download/{tag}/{name}"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)      # the probes run inside the windowed app


def asset(repo: str, name: str, size: int, sha256: str) -> dict:
    tag = RELEASES[repo]
    return {"name": name, "size": size, "sha256": sha256,
            "url": BASE.format(repo="whisper.cpp" if repo == "whisper" else "llama.cpp", tag=tag, name=name)}


# Every archive below was read from the official release asset list (size and GitHub's own SHA-256 digest).
ASSETS = {
    ("whisper", "cpu"): [
        asset("whisper", "whisper-bin-x64.zip", 8_928_640, "6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb")],
    ("whisper", "cuda"): [
        asset("whisper", "whisper-bin-win-cuda-12.4.0-x64.zip", 684_913_404,
              "afef0b881c500958921c3f5523b50e59ee2ec9b6f5cbd25b324c51ed308a957a")],
    ("llama", "cpu"): [
        asset("llama", "llama-b11851-bin-win-cpu-x64.zip", 24_172_821,
              "b248c7f6ade121831dea2b7b6e809f997fbadf74cbd2941a697bc405be78fec1")],
    ("llama", "vulkan"): [
        asset("llama", "llama-b11851-bin-win-vulkan-x64.zip", 36_970_920,
              "36dcb7b6d2f3236c6f49762659a6eaf1c4832be947a42c9480123a0ff99a7468")],
    ("llama", "cuda"): [
        asset("llama", "llama-b11851-bin-win-cuda-12.4-x64.zip", 272_429_838,
              "5a94110a5cfa2e65ab4bf5c53f57bd674e573c33b3beaedc0a8b238f9d1a3cc1"),
        asset("llama", "cudart-llama-bin-win-cuda-12.4-x64.zip", 391_443_627,
              "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6")],
}


def cache() -> Path:
    """Where the runtime folders live: $PIANPIAN_RUNTIME (the app sets it to <data>/runtime), else the
    command-line folder next to the models', like models.cache()."""
    return Path(os.environ.get("PIANPIAN_RUNTIME") or Path.home() / ".cache" / "pianpian" / "runtime")


@functools.lru_cache(maxsize=1)
def nvidia() -> bool:
    exe = shutil.which("nvidia-smi") or str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe")
    try:
        return Path(exe).is_file() and subprocess.run([exe, "-L"], capture_output=True, timeout=15,
                                                      creationflags=NO_WINDOW).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@functools.lru_cache(maxsize=1)
def vulkan() -> bool:
    """A usable Vulkan device. The loader (vulkan-1.dll) alone proves nothing — it ships with Windows —
    so without vulkaninfo to list a device this says no, and the machine gets the CPU builds."""
    exe = shutil.which("vulkaninfo")
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    if not exe and (root / "System32" / "vulkaninfo.exe").is_file():
        exe = str(root / "System32" / "vulkaninfo.exe")
    if not exe:
        return False
    try:
        out = subprocess.run([exe, "--summary"], capture_output=True, text=True, timeout=20,
                             creationflags=NO_WINDOW).stdout
        return "deviceName" in out
    except (OSError, subprocess.TimeoutExpired):
        return False


def backend_for(tool: str) -> str:
    """The build to use for one tool: the requested backend, else CUDA on NVIDIA, then Vulkan, then CPU."""
    want = os.environ.get("PIANPIAN_ACCEL", "").lower()
    if want in ("cpu", "vulkan", "cuda"):
        return want if (tool, want) in ASSETS else "cpu"
    if nvidia() and (tool, "cuda") in ASSETS:
        return "cuda"
    if vulkan() and (tool, "vulkan") in ASSETS:
        return "vulkan"
    return "cpu"


def assets(tool: str, backend: str) -> list[dict]:
    return ASSETS.get((tool, backend), [])


def folder(tool: str, backend: str) -> Path:
    return cache() / f"{tool}-{backend}"


def exe(tool: str, backend: str | None = None) -> Path | None:
    backend = backend or backend_for(tool)
    d = folder(tool, backend)
    if not (d / ".complete").exists():
        return None
    for name in EXES[tool]:
        hits = sorted(d.rglob(name), key=lambda p: len(p.parts))
        if hits:
            return hits[0]
    return None


def status() -> dict:
    """What this machine would run, and whether it is installed."""
    tools = {}
    total = 0
    ready = True
    for tool in ("whisper", "llama"):
        b = backend_for(tool)
        ok = exe(tool, b) is not None
        tools[tool] = {"backend": b, "ready": ok, "exe": str(exe(tool, b)) if ok else None}
        total += sum(a["size"] for a in assets(tool, b))
        ready = ready and ok
    labels = {"cuda": "CUDA (NVIDIA GPU)", "vulkan": "Vulkan GPU", "cpu": "CPU"}
    wb, lb = tools["whisper"]["backend"], tools["llama"]["backend"]
    label = (f"whisper.cpp + llama.cpp: {labels.get(wb, wb)}" if wb == lb
             else f"whisper.cpp: {labels.get(wb, wb)}; llama.cpp: {labels.get(lb, lb)}")
    return {"backend": lb, "label": label, "size": total, "ready": ready, "tools": tools}


def extract(archive: Path, dest: Path) -> None:
    """Unpack in place. ZipFile.extractall strips absolute names and '..' members itself."""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(dest)


def _install(tool: str, backend: str) -> str:
    dest = folder(tool, backend)
    dest.mkdir(parents=True, exist_ok=True)
    for a in assets(tool, backend):
        target = dest / a["name"]
        mirror = os.environ.get("PIANPIAN_GITHUB_MIRROR", "").rstrip("/")
        urls = [a["url"], *([f"{mirror}/{a['url']}"] if mirror else [])]
        try:
            models.download(urls, target, a["size"], a["sha256"], tool)
        except OSError as e:
            raise OSError(f"could not download the GPU runtime ({a['name']}): {e}; it resumes, try again") from e
        extract(target, dest)
        target.unlink(missing_ok=True)
    (dest / ".complete").write_text(json.dumps({"tool": tool, "backend": backend}) + "\n", encoding="utf-8")
    found = exe(tool, backend)
    if not found:
        raise RuntimeError(f"{tool} ({backend}) was unpacked but {EXES[tool][0]} is missing")
    return str(found)


def ensure(tool: str) -> str:
    """Download and unpack one tool and return its executable; backend_for() picks the build."""
    backend = backend_for(tool)
    have = exe(tool, backend)
    return have and str(have) or _install(tool, backend)


def ensure_cpu(tool: str) -> str:
    """The CPU build: the fallback when a GPU build won't start (backend_win.py)."""
    have = exe(tool, "cpu")
    return have and str(have) or _install(tool, "cpu")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(status(), indent=1))
    elif cmd == "ensure":
        which = sys.argv[2:] or ["whisper", "llama"]
        for tool in which:
            print(ensure(tool), flush=True)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
