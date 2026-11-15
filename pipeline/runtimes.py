"""The pinned llama.cpp translation binaries for macOS and Windows.

    python pipeline/runtimes.py status              # JSON: this machine's backends, tools, sizes
    python pipeline/runtimes.py ensure              # download translation tools (progress on stdout)
    python pipeline/runtimes.py ensure llama        # translation runtime

macOS Apple Silicon uses one CPU/Metal archive; Windows x64 has CPU and optional GPU archives.
Nothing here runs at import time. The archives come from the official ggml-org releases and every one
is checked against the SHA-256 written here; the running app never trusts the network. The download
itself goes through models.download(). Backends:
  cuda    NVIDIA GPU (CUDA 12.4 builds; the current integration is not tested on Windows)
  vulkan  any Vulkan GPU (AMD, Intel, or NVIDIA when CUDA is not chosen)
  cpu     Windows default; optional GPU acceleration is an explicit setup choice
  metal   macOS default; CPU fallback reuses the same archive
The app passes its saved choice to every job as PIANPIAN_ACCEL (engine.pipeline_env()),
so a job neither waits for the probes nor picks another build than the setup downloaded.
SenseVoice speech runs in the CPU helper bundled with the app. It is independent of these
translation runtimes and never downloads CUDA.
Each tool lives in <runtime>/<tool>-<backend>, whose .complete names the release and the archives' SHA-256:
a folder from another pin is not "ready", and the new build is unpacked beside it and swapped in whole.

GitHub release downloads are the weak link from mainland China. PIANPIAN_GITHUB_MIRROR is an opt-in
prefix (e.g. a proxy you trust: https://example.com/https://github.com/…); there is no default,
because a third-party proxy would see the download whenever GitHub fails. The SHA-256 pins keep the
bytes safe either way.
"""
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import backend as platform_backend
import models

CRT_DIR = Path(__file__).resolve().parent / "bin"
CRT_NAMES = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")

RELEASES = {"llama": "b11851"}
EXES = {"llama": ("llama-server.exe",)}
BASE = "https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{name}"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)      # the probes run inside the windowed app
probe_run = subprocess.run                                  # engine.py substitutes its tracked runner; the CLI keeps this one


def asset(repo: str, name: str, size: int, sha256: str) -> dict:
    tag = RELEASES[repo]
    return {"name": name, "size": size, "sha256": sha256,
            "url": BASE.format(tag=tag, name=name)}


# Every archive below was read from the official release asset list (size and GitHub's own SHA-256 digest).
ASSETS = {
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
MAC_ASSET = asset("llama", "llama-b11851-bin-macos-arm64.tar.gz", 16_244_820,
                  "eb0a16c62e4d7529610dbd17c913615ba26ed86b32e9c638be1e3b4fccb18771")


def available_backends() -> tuple[str, ...]:
    return ("cpu", "cuda", "vulkan") if platform_backend.NAME == "win32" else ("metal", "cpu")


def default_backend() -> str:
    return available_backends()[0]


def binary_names(tool: str) -> tuple[str, ...]:
    return EXES[tool] if platform_backend.NAME == "win32" else ("llama-server",)


def _stored_backend(backend: str) -> str:
    # Metal and CPU are switches on the same macOS executable, so they share one verified install.
    return "metal" if platform_backend.NAME == "darwin" and backend in ("cpu", "metal") else backend


def cache() -> Path:
    """Where the runtime folders live: $PIANPIAN_RUNTIME (the app sets it to <data>/runtime), else the
    command-line folder next to the models', like models.cache()."""
    return Path(os.environ.get("PIANPIAN_RUNTIME") or Path.home() / ".cache" / "pianpian" / "runtime")


@functools.lru_cache(maxsize=1)
def nvidia() -> bool:
    exe = shutil.which("nvidia-smi") or str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe")
    try:
        if not Path(exe).is_file():
            return False
        out = probe_run([exe, "--query-gpu=driver_version", "--format=csv,noheader"],
                        capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        # Conservative CUDA 12.4 GA driver floor, not a claim that inference will work on every GPU.
        # https://docs.nvidia.com/cuda/archive/12.4.0/cuda-toolkit-release-notes/index.html
        versions = [tuple(int(n) for n in line.strip().split(".")) for line in out.stdout.splitlines() if line.strip()]
        return out.returncode == 0 and bool(versions) and all(v >= (551, 61) for v in versions)
    except (OSError, ValueError, subprocess.TimeoutExpired):
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


def cuda_driver() -> bool:
    """Initialize the installed NVIDIA driver, without requiring or installing the CUDA Toolkit."""
    import ctypes
    try:
        driver = ctypes.WinDLL("nvcuda.dll")
        driver.cuInit.argtypes, driver.cuInit.restype = [ctypes.c_uint], ctypes.c_int
        driver.cuDeviceGetCount.argtypes, driver.cuDeviceGetCount.restype = [ctypes.POINTER(ctypes.c_int)], ctypes.c_int
        count = ctypes.c_int()
        return driver.cuInit(0) == 0 and driver.cuDeviceGetCount(ctypes.byref(count)) == 0 and count.value > 0
    except (AttributeError, OSError):
        return False


def detect() -> dict:
    """Read-only checks: driver, cached runtimes and optional device enumeration; never selects CUDA."""
    if platform_backend.NAME != "win32":
        return {"backend": "metal", "message": "SenseVoice uses CPU. PLaMo translation uses Apple Metal with CPU fallback; CUDA is not needed."}
    if nvidia():
        driver = cuda_driver()
        installed = {tool: bool(exe(tool, "cuda")) for tool in EXES}
        device = False
        if driver and installed["llama"]:
            try:
                # b11851 loads its backends before listing devices; --help does not prove GPU support.
                result = probe_run([str(exe("llama", "cuda")), "--list-devices"], capture_output=True,
                                   text=True, timeout=15, creationflags=NO_WINDOW)
                device = result.returncode == 0 and bool(re.search(r"^\s*CUDA\d+:", result.stdout, re.M))
            except (OSError, subprocess.TimeoutExpired):
                pass
        message = "Compatible NVIDIA driver detected. "
        message += "CUDA driver initialized successfully. " if driver else "CUDA driver initialization was not confirmed. "
        message += ("Pianpian CUDA translation tools are already installed. " if installed["llama"]
                    else "Pianpian CUDA translation tools are not installed. ")
        if device:
            message += "The translation engine can see a CUDA device. "
        message += ("Translation speed and model execution need the optional local test. "
                    "SenseVoice speech stays on CPU. Your acceleration choice has not changed.")
        return {"backend": "cuda", "message": message, "cuda": {"driverReady": driver, "installed": installed, "deviceVisible": device},
                "benchmarkAvailable": driver and installed["llama"]}
    if vulkan():
        return {"backend": "vulkan", "message": "Vulkan device detected. Translation can use it; SenseVoice speech stays on CPU. Inference is not tested yet."}
    return {"backend": "cpu", "message": "No compatible GPU was confirmed. Translation and SenseVoice speech work on CPU without CUDA. Vulkan detection needs vulkaninfo."}


def backend_for(tool: str) -> str:
    """Use the saved choice or platform default; never probe hardware or trigger GPU downloads."""
    want = os.environ.get("PIANPIAN_ACCEL", default_backend()).lower()
    return want if want in available_backends() else default_backend()


def assets(tool: str, backend: str) -> list[dict]:
    if platform_backend.NAME == "darwin":
        return [MAC_ASSET] if tool == "llama" and backend in available_backends() else []
    return ASSETS.get((tool, backend), [])


def folder(tool: str, backend: str) -> Path:
    return cache() / f"{tool}-{_stored_backend(backend)}"


def stamp(tool: str, backend: str) -> dict:
    """What .complete says about a folder unpacked from today's pins."""
    return {"tool": tool, "backend": _stored_backend(backend), "release": RELEASES[tool], "sha256": [a["sha256"] for a in assets(tool, backend)]}


def _find(d: Path, tool: str) -> Path | None:
    for name in binary_names(tool):
        hits = sorted(d.rglob(name), key=lambda p: len(p.parts))
        if hits:
            return hits[0]
    return None


def _archive_exe(tool: str, backend: str | None = None) -> Path | None:
    """The installed executable, only if its folder was unpacked from today's pins."""
    backend = backend or backend_for(tool)
    d = folder(tool, backend)
    try:
        if json.loads((d / ".complete").read_text(encoding="utf-8")) != stamp(tool, backend):
            return None
    except (OSError, ValueError):
        return None
    return _find(d, tool)


def _crt_files() -> dict[str, bytes]:
    try:
        manifest = json.loads((CRT_DIR / "msvc-manifest.json").read_text(encoding="utf-8"))
        files = {name: (CRT_DIR / name).read_bytes() for name in CRT_NAMES}
        if any(hashlib.sha256(data).hexdigest() != manifest["files"][name]["sha256"] for name, data in files.items()):
            raise ValueError("hash mismatch")
        return files
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError("Bundled Microsoft x64 runtime is missing or damaged; reinstall Pianpian (source builds: python dev.py native)") from error


def _crt_ready(program: Path | None) -> bool:
    if program is None or platform_backend.NAME != "win32":
        return bool(program)
    try:
        return all((program.parent / name).read_bytes() == data for name, data in _crt_files().items())
    except (OSError, RuntimeError):
        return False


def _sync_crt(program: Path) -> None:
    if platform_backend.NAME != "win32":
        return
    for name, data in _crt_files().items():
        target = program.parent / name
        if target.is_file() and target.read_bytes() == data:
            continue
        temporary = target.with_suffix(".dll.part")
        temporary.write_bytes(data)
        temporary.replace(target)


def exe(tool: str, backend: str | None = None) -> Path | None:
    """A pinned runtime ready to execute, including its app-local Windows CRT."""
    program = _archive_exe(tool, backend)
    return program if _crt_ready(program) else None


def status(probe: bool = False, backend: str | None = None, which=None) -> dict:
    """Pinned archive bytes still missing for the chosen tools. Retains probe for older callers; no probes run."""
    want = (backend or os.environ.get("PIANPIAN_ACCEL") or default_backend()).lower()
    if want not in available_backends():
        want = default_backend()
    selected = EXES if which is None else which
    tools = {}
    for tool in selected:
        b = want
        installed = _archive_exe(tool, b)
        # CPU word links are mandatory even when translation uses an explicitly selected Windows GPU.
        needs_cpu = platform_backend.NAME == "win32" and b in ("cuda", "vulkan")
        cpu_installed = _archive_exe(tool, "cpu") if needs_cpu else None
        cpu_ready = not needs_cpu or _crt_ready(cpu_installed)
        cpu_size = 0 if not needs_cpu or cpu_installed else sum(a["size"] for a in assets(tool, "cpu"))
        tools[tool] = {"backend": b, "ready": _crt_ready(installed) and cpu_ready, "exe": str(installed) if installed else None,
                       "size": (0 if installed else sum(a["size"] for a in assets(tool, b))) + cpu_size,
                       "cpu_size": cpu_size}
    labels = {"cuda": "CUDA (NVIDIA GPU)", "vulkan": "Vulkan GPU", "cpu": "CPU", "metal": "Apple Metal"}
    label = "; ".join(f"{tool}.cpp: {labels[t['backend']]}" for tool, t in tools.items()) or "No model runtime selected"
    return {"backend": want, "label": label, "size": sum(t["size"] for t in tools.values()),
            "ready": all(t["ready"] for t in tools.values()), "tools": tools}


def extract(archive: Path, dest: Path) -> None:
    """Unpack the verified archive; tar data filtering rejects escaping paths and links."""
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(dest, filter="data")
    else:
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
            raise OSError(f"could not download the runtime ({a['name']}): {e}; it resumes, try again") from e
    for a in assets(tool, backend):
        extract(work / a["name"], new)
        (work / a["name"]).unlink()
    if not _find(new, tool):
        raise RuntimeError(f"{tool} ({backend}) was unpacked but {binary_names(tool)[0]} is missing")
    _sync_crt(_find(new, tool))
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
    backend="cpu" for the fallback when a GPU build won't start."""
    backend = backend or backend_for(tool)
    if tool not in EXES or backend not in available_backends():
        raise ValueError("unsupported translation runtime")
    if platform_backend.NAME == "win32":
        _crt_files()  # fail before a download if the app itself needs repair
    if platform_backend.NAME == "win32" and backend in ("cuda", "vulkan"):
        ensure(tool, "cpu")  # install word-link CPU support before setup can report ready
    have = _archive_exe(tool, backend)
    if have:
        _sync_crt(have)
        return str(have)
    return _install(tool, backend)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(status(), indent=1))
    elif cmd == "ensure":
        which = sys.argv[2:] or list(EXES)
        for tool in which:
            print(ensure(tool), flush=True)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
