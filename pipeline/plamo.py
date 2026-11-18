"""Shared PLaMo Q3 inference through the pinned native llama.cpp runtime.

PFML3 prompts are sent verbatim; there is no Python ML dependency or previous model backend.
Local HTTP bypasses proxies and redirects. Explicit GPU startup failure retries CPU once.
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
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import runtimes

LLAMA_MODEL = "plamo-3-translate-0.8b-Q3_K_M.gguf"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Local inference must bypass system proxies and cannot follow redirects off-machine.
LOCAL_HTTP = build_opener(ProxyHandler({}), _NoRedirect())


def model_file(model_dir: str) -> Path:
    pinned = Path(model_dir) / LLAMA_MODEL
    if pinned.is_file():
        return pinned
    raise FileNotFoundError(f"{model_dir}: missing {LLAMA_MODEL}; complete model setup first")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(exe: str, model: Path, port: int, backend: str, log) -> subprocess.Popen:
    cmd = [exe, "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "-c", "4096",
           "--parallel", "1", "--no-context-shift",    # raw PFML3 prompts; fail rather than silently dropping context
           "-lv", "4"]                                # b11851 logs the offload lines only at level 4+ (default 3, checked 7 Nov 2026)
    if backend == "cpu":
        cmd += ["-ngl", "0", "-t", str(max(2, (os.cpu_count() or 4) // 2))]
    else:
        cmd += ["-ngl", "999"]
        if os.environ.get("PIANPIAN_LLAMA_DEVICE"):   # e.g. Vulkan0 on a hybrid laptop; untested
            cmd += ["--device", os.environ["PIANPIAN_LLAMA_DEVICE"]]
    print(f"loading {model.name} with llama.cpp ({backend})…", flush=True)
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, creationflags=runtimes.NO_WINDOW)


def _wait_ready(proc: subprocess.Popen, port: int) -> bool:
    for _ in range(600):                                   # a cold CUDA start can take minutes
        if proc.poll() is not None:
            return False
        try:
            with LOCAL_HTTP.open(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def _tail(log_path: Path, n: int = 30) -> str:
    return "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])


@contextmanager
def translator(model_dir: str):
    """PLaMo Q3 through llama-server, started once for the whole run; yields
    generate(prompt, temperature, max_tokens) -> reply text. A GPU build that won't start is
    retried once with the CPU build."""
    model = model_file(model_dir)
    port = _free_port()
    log_path = Path(tempfile.gettempdir()) / f"pianpian-llama-server-{port}.log"
    proc = None
    try:
        backend = runtimes.backend_for("llama")
        with log_path.open("w", encoding="utf-8") as log:
            exe = runtimes.ensure("llama")
            try:
                proc = _start_server(exe, model, port, backend, log)
            except OSError:
                if backend == "cpu":
                    raise
            if proc is None or not _wait_ready(proc, port):
                if proc is not None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    proc = None
                if backend == "cpu":
                    sys.exit(f"llama-server did not start:\n{_tail(log_path)}")
                print(f"the {backend} llama build did not start; trying the CPU build", flush=True)
                backend = "cpu"
                log.seek(0)
                log.truncate()
                proc = _start_server(runtimes.ensure("llama", "cpu"), model, port, backend, log)
                if not _wait_ready(proc, port):
                    sys.exit(f"llama-server did not start:\n{_tail(log_path)}")
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        notes = [x.strip() for x in lines if "offload" in x.lower()]
        if not notes:
            notes = [next((x.strip() for x in lines if "CUDA" in x or "Vulkan" in x), "")]
        for note in filter(None, notes):
            print(f"llama.cpp: {note}", flush=True)   # the only evidence the GPU is used

        def generate(prompt: str, temperature: float, max_tokens: int) -> str:
            body = json.dumps({"prompt": prompt, "temperature": temperature, "n_predict": max_tokens,
                               "repeat_penalty": 1.0, "seed": 0, "cache_prompt": True,
                               "stop": ["<|plamo:tag|>", "<|plamo:bos|>"], "stream": False}).encode("utf-8")
            req = Request(f"http://127.0.0.1:{port}/completion", data=body,
                          headers={"Content-Type": "application/json"})
            try:
                with LOCAL_HTTP.open(req, timeout=300) as r:
                    response = json.load(r)
                if response.get("stopped_limit") or response.get("truncated"):
                    raise ValueError("PLaMo reached its token limit; split this subtitle into shorter lines")
                text = response.get("content")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("PLaMo returned an empty or invalid translation")
                return text
            except OSError:                               # the server died mid-run (a driver reset, out of memory…)
                print(f"llama-server stopped answering (exit code {proc.poll()}); its last log lines:\n{_tail(log_path)}", flush=True)
                raise

        yield generate
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        log_path.unlink(missing_ok=True)
