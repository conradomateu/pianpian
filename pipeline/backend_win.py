"""The Windows engines: whisper.cpp for speech, llama.cpp for translation, RapidOCR for burned-in text.

The contract is in backend.py. The pinned binaries come from runtimes.py (CUDA, Vulkan or CPU, picked
per tool). If a GPU build won't start or crashes, the step is retried once with the CPU build, so a
bad driver never strands the job.

whisper.cpp's JSON offsets are milliseconds; its tokens become "words" here. For Chinese a token is
usually one or two characters, and srt_tool.py spreads each token's time over its characters.
PIANPIAN_LLAMA_DEVICE (e.g. "Vulkan0" on a hybrid laptop) picks the llama.cpp device: untested, for
trying things out. Tested on Windows 11 25H2 (build 26200), whisper.cpp b5454 and llama.cpp b11851,
RTX 4060 Laptop, driver 591.74 (27 Oct 2026); the RapidOCR path has not been run on Windows yet.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen

import runtimes
import srt_tool

WHISPER_MODEL = "ggml-large-v3-turbo.bin"
LLAMA_MODEL = "Hy-MT2-1.8B-Q4_K_M.gguf"


def _segments(data: dict) -> list[dict]:
    """whisper.cpp's -ojf JSON as [{start, end, text, words}], times in seconds."""
    out = []
    for seg in data.get("transcription") or []:
        start, end = seg["offsets"]["from"] / 1000, seg["offsets"]["to"] / 1000
        words = []
        for tok in seg.get("tokens") or []:
            word = (tok.get("text") or "").strip()
            if not word or word.startswith("[_"):               # [_BEG_], [_TT_…]: control tokens, not speech
                continue
            off = tok.get("offsets") or {}
            words.append({"word": word, "start": round(off.get("from", 0) / 1000, 2),
                          "end": round(off.get("to", 0) / 1000, 2)})
        text = (seg.get("text") or "").strip()
        if text:
            out.append({"start": start, "end": end, "text": text, "words": words})
    return out


def _run_whisper(exe: str, model: Path, audio: Path, base: Path, backend: str) -> None:
    # -mc 0: no conditioning on the previous text, like the MLX path (--condition-on-previous-text False),
    # which avoids repetition loops on long audio; b5454 then also ignores --prompt, and srt_tool.py split
    # converts to Simplified with zhconv anyway. Punctuation without the prompt: to check (PR #11, item 7).
    cmd = [exe, "-m", str(model), "-f", str(audio), "-l", "zh", "-ojf", "-of", str(base), "-mc", "0"]
    if backend == "cpu":
        cmd += ["-ng", "-t", str(max(2, (os.cpu_count() or 4) // 2))]
    print(f"transcribing with whisper.cpp ({backend})", flush=True)
    subprocess.run(cmd, check=True)                   # not captured: its GPU line lands in the job log


def transcribe(audio: Path, model_dir: str, srt: Path, words_json: Path) -> None:
    """whisper.cpp on a 16 kHz mono wav: writes srt (one cue per segment) and words_json (segments with
    word times), and nothing else."""
    model = Path(model_dir) / WHISPER_MODEL
    if not model.is_file():
        sys.exit(f"{model_dir}: no {WHISPER_MODEL} (the pinned model file)")
    base = words_json.with_name(words_json.stem + ".cpp")     # a temporary name: whisper.cpp must not overwrite our output
    backend = runtimes.backend_for("whisper")
    try:
        _run_whisper(runtimes.ensure("whisper"), model, audio, base, backend)
    except (subprocess.CalledProcessError, OSError) as e:
        if backend == "cpu":
            raise
        print(f"the {backend} whisper build failed ({e}); trying the CPU build", flush=True)
        _run_whisper(runtimes.ensure_cpu("whisper"), model, audio, base, "cpu")
    produced = Path(str(base) + ".json")
    if not produced.exists():
        sys.exit(f"whisper.cpp wrote no {produced.name}")
    segments = _segments(json.loads(produced.read_text(encoding="utf-8")))
    produced.unlink()
    if not segments:
        sys.exit("whisper.cpp found no speech")
    cues = [(str(n), f"{srt_tool.stamp(s['start'])} --> {srt_tool.stamp(s['end'])}", s["text"])
            for n, s in enumerate(segments, 1)]
    srt_tool.write_srt(srt, cues)
    words_json.write_text(json.dumps({"segments": segments}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _gguf(model_dir: str) -> Path:
    pinned = Path(model_dir) / LLAMA_MODEL
    if pinned.is_file():
        return pinned
    hits = sorted(Path(model_dir).glob("*.gguf"))             # a model picked by MT_MODEL instead
    if len(hits) == 1:
        return hits[0]
    sys.exit(f"{model_dir}: no {LLAMA_MODEL}" + ("" if not hits else f" (found {len(hits)} .gguf files, want one)"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(exe: str, model: Path, port: int, backend: str, log) -> subprocess.Popen:
    cmd = [exe, "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "-c", "4096",
           "--parallel", "1", "--jinja"]               # --jinja: the server applies the GGUF's chat template (to check on a run)
    if backend == "cpu":
        cmd += ["-ngl", "0", "-t", str(max(2, (os.cpu_count() or 4) // 2))]
    else:
        cmd += ["-ngl", "999"]
        if os.environ.get("PIANPIAN_LLAMA_DEVICE"):   # e.g. Vulkan0 on a hybrid laptop; untested
            cmd += ["--device", os.environ["PIANPIAN_LLAMA_DEVICE"]]
    print(f"loading {model.name} with llama.cpp ({backend})…", flush=True)
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)


def _wait_ready(proc: subprocess.Popen, port: int) -> bool:
    for _ in range(600):                                   # a cold CUDA start can take minutes
        if proc.poll() is not None:
            return False
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


@contextmanager
def translator(model_dir: str):
    """Hy-MT2 as a GGUF through llama-server, started once for the whole run; yields
    generate(prompt, temperature, max_tokens) -> reply text. A GPU build that won't start is
    retried once with the CPU build."""
    model = _gguf(model_dir)
    port = _free_port()
    log_path = Path(tempfile.gettempdir()) / f"pianpian-llama-server-{port}.log"
    proc = None
    try:
        backend = runtimes.backend_for("llama")
        with log_path.open("w", encoding="utf-8") as log:
            proc = _start_server(runtimes.ensure("llama"), model, port, backend, log)
            if not _wait_ready(proc, port):
                proc.terminate()
                proc.wait(timeout=15)
                if backend == "cpu":
                    tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:])
                    sys.exit(f"llama-server did not start:\n{tail}")
                print(f"the {backend} llama build did not start; trying the CPU build", flush=True)
                backend = "cpu"
                proc = _start_server(runtimes.ensure_cpu("llama"), model, port, backend, log)
                if not _wait_ready(proc, port):
                    proc.terminate()
                    proc.wait(timeout=15)
                    tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:])
                    sys.exit(f"llama-server did not start:\n{tail}")
        note = next((x.strip() for x in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                     if "CUDA" in x or "Vulkan" in x or "offload" in x.lower()), "")
        if note:
            print(f"llama.cpp: {note}", flush=True)   # the only evidence the GPU is used

        def generate(prompt: str, temperature: float, max_tokens: int) -> str:
            # the MLX path's sampling values: the model card's top_p/top_k/penalty, our temperature
            body = json.dumps({"messages": [{"role": "user", "content": prompt}], "temperature": temperature,
                               "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05, "max_tokens": max_tokens,
                               "stream": False}).encode()
            req = Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
                          headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=300) as r:
                return json.load(r)["choices"][0]["message"]["content"]

        yield generate
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        log_path.unlink(missing_ok=True)


def ocr(frames_dir: str) -> str:
    """RapidOCR (ONNX Runtime, Chinese models included) over every frame: one 'name<TAB>text' line each."""
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    lines = []
    for path in sorted(Path(frames_dir).glob("*.png")):
        result, _ = engine(str(path))
        found = []
        for box, text, score in result or []:
            if score >= 0.5 and text.strip():
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                found.append((min(ys), min(xs), text.strip()))
        lines.append(f"{path.name}\t{' '.join(t for _, _, t in sorted(found))}")
    return "\n".join(lines)
