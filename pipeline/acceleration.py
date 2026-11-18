"""Optional, offline CPU/CUDA comparison using only already verified local models and runtimes.

SenseVoice speech uses the bundled CPU helper and is not part of this GPU comparison.
llama b11851: tools/llama-bench/llama-bench.cpp and src/llama-model.cpp (actual layer offload).
Windows execution is not tested on this Mac; the command/diagnostic contracts have simulated tests.
"""
import argparse
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

import models
import runtimes

TOOL_TIMEOUT = 600


def _available() -> tuple[Path | None, Path | None, str]:
    exe = runtimes.exe("llama", "cuda")
    if not exe:
        return None, None, "The pinned CUDA runtime is not installed. This test downloads nothing."
    exe = exe.with_name("llama-bench.exe")
    if not exe.is_file():
        return None, None, "The installed runtime has no llama-bench executable."
    repo = models.default("translate")
    filenames = [f["name"] for f in models.lock().get(repo, {}).get("files", []) if f["name"].endswith(".gguf")]
    folder = models.local_path(repo)
    model = folder / filenames[0] if folder and len(filenames) == 1 else None
    if not model or not model.is_file():
        return None, None, "The pinned model is not installed. This test downloads nothing."
    return exe.resolve(), model.resolve(), ""


def readiness() -> dict:
    """No process, hardware probe, network call or download."""
    reason = _available()[2]
    return {"tools": [{"tool": "llama", "status": "unavailable" if reason else "ready", "reason": reason}]}


def _run(cmd: list[str], work: Path, name: str, deadline: float) -> subprocess.CompletedProcess:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(cmd, TOOL_TIMEOUT)
    result = subprocess.run(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=remaining, creationflags=runtimes.NO_WINDOW)
    (work / f"{name}.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode:
        raise ValueError(f"{name} exited with code {result.returncode}; no speed claim was made.")
    return result


def _positive(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("The runtime returned an invalid timing.")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("The runtime returned an invalid timing.")
    return number


def _llama_time(text: str) -> float:
    rows = json.loads(text)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("PLaMo Q3's benchmark returned unreadable timing results.")
    # Combined pp256+tg32 retains prompt context while generating; startup and warmup are excluded by llama-bench.
    rows = [r for r in rows if r.get("n_prompt") == 256 and r.get("n_gen") == 32]
    if len(rows) != 1:
        raise ValueError("llama-bench did not return the expected 256-input/32-output-token test.")
    if "avg_ns" not in rows[0]:
        raise ValueError("PLaMo Q3's benchmark did not report its processing time.")
    return _positive(_positive(rows[0]["avg_ns"]) / 1e9)


def _llama_gpu(log: str) -> bool:
    return bool(re.search(r"offloaded [1-9]\d*/\d+ layers to GPU", log)
                and re.search(r"CUDA\d+ model buffer size\s*=\s*[1-9][\d.]* MiB", log))


def _llama(exe: Path, model: Path, work: Path, deadline: float) -> dict:
    measurements = {}
    for mode in ("cpu", "gpu"):
        cmd = [str(exe), "-m", str(model), "--offline", "-p", "0", "-n", "0", "-pg", "256,32",
               "-r", "2", "-o", "json", "-v", "-t", str(max(2, (os.cpu_count() or 4) // 2)),
               "-ngl", "0" if mode == "cpu" else "999"]
        if mode == "cpu":
            cmd += ["-dev", "none", "-nkvo", "1", "-nopo", "1"]
        elif os.environ.get("PIANPIAN_LLAMA_DEVICE"):
            cmd += ["-dev", os.environ["PIANPIAN_LLAMA_DEVICE"]]
        result = _run(cmd, work, f"llama-{mode}", deadline)
        if mode == "gpu" and not _llama_gpu(result.stderr):
            return {"status": "unconfirmed", "reason": "PLaMo Q3 ran, but its logs did not confirm CUDA layer offload. No speedup is reported."}
        if mode == "cpu" and re.search(r"offloaded [1-9]\d*/\d+ layers to GPU", result.stderr):
            return {"status": "unconfirmed", "reason": "PLaMo Q3 did not confirm a CPU-only baseline."}
        measurements[mode] = _llama_time(result.stdout)
    return _comparison(measurements, "PLaMo Q3 synthetic token benchmark: 256 input + 32 output tokens, mean of two warm runs; not translation accuracy",
                       "Rough token-processing time for 100 subtitles of 256 input + 32 output tokens each; excludes loading and app overhead",
                       100)


def _comparison(times: dict, workload: str, estimate: str, factor: float) -> dict:
    return {"status": "measured", "reason": "Measured locally in this session; other videos and subtitle lengths can differ.",
            "cpu_seconds": times["cpu"], "gpu_seconds": times["gpu"], "speedup": times["cpu"] / times["gpu"],
            "workload": workload, "estimate": {"label": estimate, "cpu_seconds": times["cpu"] * factor,
                                               "gpu_seconds": times["gpu"] * factor}}


def benchmark(work_dir: Path) -> dict:
    """At most 600 seconds; no ensure(), fallback downloads or persistent accelerator choice."""
    work = work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    exe, model, reason = _available()
    if reason:
        result = {"status": "unavailable", "reason": reason}
    else:
        try:
            result = _llama(exe, model, work, time.monotonic() + TOOL_TIMEOUT)
        except subprocess.TimeoutExpired:
            result = {"status": "failed", "reason": "The translation comparison exceeded the 10-minute limit."}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result = {"status": "failed", "reason": str(exc)}
    return {"tools": [{"tool": "llama", **result}]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    print("@benchmark " + json.dumps(benchmark(args.work_dir)), flush=True)
