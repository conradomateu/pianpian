"""The pinned Windows binaries: whisper.cpp (speech) and llama.cpp (translation), and how to pick them.

    python pipeline/runtimes.py status              # JSON: this machine's backends, tools, sizes
    python pipeline/runtimes.py ensure              # download both tools (progress on stdout)
    python pipeline/runtimes.py ensure whisper      # one tool

Windows only (x64; the engine Python and the models lock are x86_64 too), but importable anywhere:
nothing here runs at import time. The archives come from the official ggml-org releases and every one
is checked against the SHA-256 written here; the running app never trusts the network. The download
itself goes through models.download(). Backends:
  cuda    NVIDIA GPU (the CUDA 12.4 builds; tested on 27 Oct 2026 with an RTX 4060 Laptop, driver 591.74)
  vulkan  any Vulkan GPU (AMD, Intel, or NVIDIA when CUDA is not chosen)
  cpu     no usable GPU, or PIANPIAN_ACCEL=cpu (also: vulkan / cuda to force one)
The app's setup probes once and passes its choice to every job as PIANPIAN_ACCEL (engine.pipeline_env()),
so a job neither waits for the probes nor picks another build than the setup downloaded.
whisper.cpp has no Vulkan Windows asset in its official release yet, so a Vulkan-only machine uses
the CPU build for speech and the Vulkan build for translation. That gap is deliberate and visible in
`status`; a Vulkan whisper.cpp build can be added here once one is pinned.
Each tool lives in <runtime>/<tool>-<backend>, whose .complete names the release and the archives' SHA-256:
a folder from another pin is not "ready", and the new build is unpacked beside it and swapped in whole.

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
probe_run = subprocess.run                                  # engine.py substitutes its tracked runner; the CLI keeps this one


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
        return Path(exe).is_file() and probe_run([exe, "-L"], capture_output=True, timeout=15,
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
        out = probe_run([exe, "--summary"], capture_output=True, text=True, timeout=20,
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


def stamp(tool: str, backend: str) -> dict:
    """What .complete says about a folder unpacked from today's pins."""
    return {"tool": tool, "backend": backend, "release": RELEASES[tool], "sha256": [a["sha256"] for a in assets(tool, backend)]}


def _find(d: Path, tool: str) -> Path | None:
    for name in EXES[tool]:
        hits = sorted(d.rglob(name), key=lambda p: len(p.parts))
        if hits:
            return hits[0]
    return None


def exe(tool: str, backend: str | None = None) -> Path | None:
    """The installed executable, only if its folder was unpacked from today's pins."""
    backend = backend or backend_for(tool)
    d = folder(tool, backend)
    try:
        if json.loads((d / ".complete").read_text(encoding="utf-8")) != stamp(tool, backend):
            return None
    except (OSError, ValueError):
        return None
    return _find(d, tool)


def status(probe: bool = True) -> dict:
    """What this machine would run; probe=False uses saved/installed backends without starting hardware tools."""
    tools = {}
    total = 0
    ready = True
    for tool in ("whisper", "llama"):
        if probe:
            b = backend_for(tool)
        else:
            want = os.environ.get("PIANPIAN_ACCEL", "").lower()
            b = want if (tool, want) in ASSETS else next(
                (candidate for candidate in ("cuda", "vulkan", "cpu") if (tool, candidate) in ASSETS and exe(tool, candidate)), "auto")
        ok = b != "auto" and exe(tool, b) is not None
        tools[tool] = {"backend": b, "ready": ok, "exe": str(exe(tool, b)) if ok else None}
        total += sum(a["size"] for a in assets(tool, b)) if b != "auto" else max(
            sum(a["size"] for a in choices) for backend, choices in ASSETS.items() if backend[0] == tool)
        ready = ready and ok
    labels = {"cuda": "CUDA (NVIDIA GPU)", "vulkan": "Vulkan GPU", "cpu": "CPU", "auto": "auto (GPU detected during setup)"}
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
    # the archives (resumable) and the unpacked files wait here until the whole build is in, so two releases'
    # DLLs never mix in one folder and a failed update leaves the old build where it was
    work = cache() / f"{dest.name}-{RELEASES[tool]}.part"
    for stale in cache().glob(f"{dest.name}-*.part"):        # a download for an older pin, never finished
        if stale != work:
            shutil.rmtree(stale, ignore_errors=True)
    new = work / "files"
    shutil.rmtree(new, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    mirror = os.environ.get("PIANPIAN_GITHUB_MIRROR", "").rstrip("/")
    for a in assets(tool, backend):
        urls = [a["url"], *([f"{mirror}/{a['url']}"] if mirror else [])]
        try:
            models.download(urls, work / a["name"], a["size"], a["sha256"], tool)
        except OSError as e:
            raise OSError(f"could not download the GPU runtime ({a['name']}): {e}; it resumes, try again") from e
    for a in assets(tool, backend):
        extract(work / a["name"], new)
        (work / a["name"]).unlink()
    if not _find(new, tool):
        raise RuntimeError(f"{tool} ({backend}) was unpacked but {EXES[tool][0]} is missing")
    (new / ".complete").write_text(json.dumps(stamp(tool, backend)) + "\n", encoding="utf-8")
    if dest.exists():                                       # the build of an older pin (or a broken one)
        try:
            shutil.rmtree(dest)
        except OSError as e:                                # Windows: a running llama-server holds its DLLs
            raise OSError(f"could not replace {dest} (is a job still running?): {e}") from e
    new.replace(dest)
    shutil.rmtree(work, ignore_errors=True)
    return str(exe(tool, backend))


def ensure(tool: str, backend: str | None = None) -> str:
    """Download and unpack one tool and return its executable: backend_for() picks the build, or pass
    backend="cpu" for the fallback when a GPU build won't start (backend_win.py)."""
    backend = backend or backend_for(tool)
    have = exe(tool, backend)
    return have and str(have) or _install(tool, backend)


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
