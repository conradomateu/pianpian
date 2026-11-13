"""Optional, offline CPU/CUDA comparison using only already verified local models and runtimes.

The Mandarin sample is the first 30 seconds of our own demo/library/pianpian-day/source.mp4,
resampled to 16 kHz mono PCM on 13 Nov 2026. It adds 960 KB; no audio dependency is needed here.
Whisper b5454 diagnostics: src/whisper.cpp (whisper_backend_init_gpu, whisper_print_timings).
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

SAMPLE = Path(__file__).with_name("benchmark-mandarin.wav")
SAMPLE_SECONDS = 30
TOOL_TIMEOUT = 600


def _available(tool: str) -> tuple[Path | None, Path | None, str]:
    exe = runtimes.exe(tool, "cuda")
    if not exe:
        return None, None, "The pinned CUDA runtime is not installed. This test downloads nothing."
    if tool == "llama":
        exe = exe.with_name("llama-bench.exe")
        if not exe.is_file():
            return None, None, "The installed runtime has no llama-bench executable."
    repo = models.default("transcribe" if tool == "whisper" else "translate")
    filenames = [f["name"] for f in models.lock().get(repo, {}).get("files", []) if f["name"].endswith((".bin", ".gguf"))]
    folder = models.local_path(repo)
    model = folder / filenames[0] if folder and len(filenames) == 1 else None
    if not model or not model.is_file():
        return None, None, "The pinned model is not installed. This test downloads nothing."
    if tool == "whisper" and not SAMPLE.is_file():
        return None, None, "The bundled Mandarin sample is missing."
    return exe.resolve(), model.resolve(), ""


def readiness() -> dict:
    """No process, hardware probe, network call or download."""
    return {"tools": [{"tool": tool, "status": "unavailable" if (reason := _available(tool)[2]) else "ready",
                       "reason": reason} for tool in ("whisper", "llama")]}


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
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("The runtime returned an invalid timing.")
    return number


def _whisper_times(log: str) -> tuple[float, float]:
    timings = {name: float(value) / 1000 for name, value in
               re.findall(r"whisper_print_timings:\s+(load|total) time\s*=\s*([\d.]+) ms", log)}
    if set(timings) != {"load", "total"} or not math.isfinite(timings["load"]):
        raise ValueError("Whisper did not report valid model-loading and total times.")
    return _positive(timings["total"] - timings["load"]), timings["load"]


def _whisper_gpu(log: str) -> bool:
    # A compiled CUDA backend or detected GPU is insufficient: require allocated CUDA model weights too.
    return bool(re.search(r"whisper_backend_init_gpu: using CUDA\d* backend", log)
                and re.search(r"whisper_model_load:\s+CUDA\d* total size\s*=\s*[1-9][\d.]* MB", log)
                and not re.search(r"failed to initialize .* backend|no GPU found", log))


def _whisper(exe: Path, model: Path, work: Path, deadline: float) -> dict:
    measurements, loads = {}, {}
    for mode in ("cpu", "gpu"):
        base = work / f"whisper-{mode}"
        output = base.with_suffix(".json")
        output.unlink(missing_ok=True)
        cmd = [str(exe), "-m", str(model), "-f", str(SAMPLE), "-l", "zh", "-ojf", "-of", str(base), "-mc", "0",
               "-t", str(max(2, (os.cpu_count() or 4) // 2))]
        if mode == "cpu":
            cmd += ["-ng"]
        result = _run(cmd, work, f"whisper-{mode}", deadline)
        transcript = json.loads(output.read_text(encoding="utf-8"))
        segments = transcript.get("transcription") if isinstance(transcript, dict) else None
        if not isinstance(segments, list) or not any(isinstance(s, dict) and isinstance(s.get("text"), str)
                                                    and s["text"].strip() for s in segments):
            raise ValueError("Whisper produced no transcript for the bundled sample.")
        log = result.stderr
        if mode == "gpu" and not _whisper_gpu(log):
            return {"status": "unconfirmed", "reason": "Whisper ran, but its logs did not confirm CUDA inference. No speedup is reported."}
        if mode == "cpu" and re.search(r"whisper_backend_init_gpu: using CUDA", log):
            return {"status": "unconfirmed", "reason": "Whisper did not confirm a CPU-only baseline."}
        measurements[mode], loads[mode] = _whisper_times(log)
    return _comparison(measurements, "30 seconds of the bundled Mandarin demo; runtime time minus model loading",
                       "Rough speech-only time for 10 minutes, extrapolated from 30 seconds; excludes model loading, translation and OCR",
                       600 / SAMPLE_SECONDS, load_seconds=loads)


def _llama_time(text: str) -> float:
    rows = json.loads(text)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Hy-MT2's benchmark returned unreadable timing results.")
    # Combined pp256+tg32 retains prompt context while generating; startup and warmup are excluded by llama-bench.
    rows = [r for r in rows if r.get("n_prompt") == 256 and r.get("n_gen") == 32]
    if len(rows) != 1:
        raise ValueError("llama-bench did not return the expected 256-input/32-output-token test.")
    if "avg_ns" not in rows[0]:
        raise ValueError("Hy-MT2's benchmark did not report its processing time.")
    return _positive(rows[0]["avg_ns"]) / 1e9


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
            return {"status": "unconfirmed", "reason": "Hy-MT2 ran, but its logs did not confirm CUDA layer offload. No speedup is reported."}
        if mode == "cpu" and re.search(r"offloaded [1-9]\d*/\d+ layers to GPU", result.stderr):
            return {"status": "unconfirmed", "reason": "Hy-MT2 did not confirm a CPU-only baseline."}
        measurements[mode] = _llama_time(result.stdout)
    return _comparison(measurements, "Hy-MT2 synthetic token benchmark: 256 input + 32 output tokens, mean of two warm runs; not translation accuracy",
                       "Rough token-processing time for 100 subtitles of 256 input + 32 output tokens each; excludes loading and app overhead",
                       100)


def _comparison(times: dict, workload: str, estimate: str, factor: float, **extra) -> dict:
    return {"status": "measured", "reason": "Measured locally in this session; other videos and subtitle lengths can differ.",
            "cpu_seconds": times["cpu"], "gpu_seconds": times["gpu"], "speedup": times["cpu"] / times["gpu"],
            "workload": workload, "estimate": {"label": estimate, "cpu_seconds": times["cpu"] * factor,
                                               "gpu_seconds": times["gpu"] * factor}, **extra}


def benchmark(work_dir: Path) -> dict:
    """At most 600 seconds per tool; no ensure(), fallback downloads or persistent accelerator choice."""
    work = work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    results = []
    for tool, measure in (("whisper", _whisper), ("llama", _llama)):
        exe, model, reason = _available(tool)
        if reason:
            result = {"status": "unavailable", "reason": reason}
        else:
            try:
                result = measure(exe, model, work, time.monotonic() + TOOL_TIMEOUT)
            except subprocess.TimeoutExpired:
                result = {"status": "failed", "reason": "The comparison exceeded the 10-minute limit for this tool."}
            except (OSError, ValueError, KeyError, TypeError) as exc:
                result = {"status": "failed", "reason": str(exc)}
        results.append({"tool": tool, **result})
    return {"tools": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    print("@benchmark " + json.dumps(benchmark(args.work_dir)), flush=True)
