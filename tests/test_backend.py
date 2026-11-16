"""The engine contract (pipeline/backend.py) and the parts around it that every backend shares.

The real engines (PLaMo, SenseVoice, llama.cpp) can't run in CI, so these tests fake them: what they
pin is the shape of what a backend hands to the rest of the pipeline. A new backend adds its cases here
and checks its output with assert_transcribe_output.
"""
import importlib
import inspect
import io
import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "pipeline")]
import backend  # noqa: E402
import backend_native  # noqa: E402
import plamo  # noqa: E402
import models  # noqa: E402
import srt_tool  # noqa: E402
import translate_srt  # noqa: E402


def assert_transcribe_output(srt: Path, words_json: Path) -> None:
    """What transcribe() must leave: the two files and nothing else, an .srt srt_tool reads, and word times."""
    assert sorted(p.name for p in srt.parent.iterdir() if p.name not in ("audio.wav",)) == sorted([srt.name, words_json.name])
    assert srt_tool.read_srt(srt)
    times = srt_tool.char_times(words_json)
    assert times and all(isinstance(c, str) and 0 <= s <= e for c, s, e in times)


def test_the_promised_signatures():
    # what the review of PR #11 promised the Windows backend; a change here is a change of contract
    def params(f):
        return list(inspect.signature(f).parameters)
    assert params(models.download) == ["urls", "target", "size", "sha256", "label"]
    assert params(models.default) == ["task"]
    impl = backend.impl()
    assert params(impl.transcribe) == ["audio", "model_dir", "srt", "words_json"]
    assert params(impl.translator) == ["model_dir"]
    assert params(impl.align) == ["zh_srt", "en_srt"]


def test_both_backends_share_translation_and_support_word_links():
    assert backend_native.translator is plamo.translator
    assert callable(backend_native.align)


def test_mac_align_runs_align_srt(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(backend_native.subprocess, "run", lambda cmd, check: calls.append(cmd))
    backend_native.align(tmp_path / "zh.srt", tmp_path / "zh.en.srt")
    assert calls[0][1].endswith("align_srt.py") and calls[0][2:] == [str(tmp_path / "zh.srt"), str(tmp_path / "zh.en.srt")]


def test_this_platform_selects_its_backend():
    assert backend.impl().__name__ == "backend_native"


@pytest.mark.parametrize("platform, helper", [("darwin", "pianpian-sensevoice"), ("win32", "pianpian-sensevoice.exe")])
def test_both_backends_preserve_the_shared_speech_contract(monkeypatch, tmp_path, platform, helper):
    monkeypatch.setattr(backend, "NAME", platform)
    module = backend_native
    calls = []

    def transcribe(audio, model, srt, words, executable):
        calls.append((audio, model, executable))
        srt.write_text("1\n00:00:00,000 --> 00:00:01,500\n你好\n", encoding="utf-8")
        words.write_text(json.dumps({"segments": [{"start": 0.0, "end": 1.5, "text": "你好",
                        "words": [{"word": "你", "start": 0.0, "end": 0.7}, {"word": "好", "start": 0.8, "end": 1.5}]}]}))

    monkeypatch.setattr(module.sensevoice, "transcribe", transcribe)
    monkeypatch.setattr(plamo.runtimes, "ensure", lambda *a, **kw: pytest.fail("speech tried downloading a runtime"))
    monkeypatch.setenv("PIANPIAN_ACCEL", "cuda")
    srt, words = tmp_path / "zh.srt", tmp_path / "zh.whisper.json"
    module.transcribe(tmp_path / "audio.wav", "model-dir", srt, words)
    assert_transcribe_output(srt, words)
    assert srt_tool.char_times(words) == [("你", 0.0, 0.7), ("好", 0.8, 1.5)]
    assert calls == [(tmp_path / "audio.wav", "model-dir", ROOT / "pipeline" / "bin" / helper)]


def test_translate_uses_pfml3_and_retries_without_context(capsys):
    asked = []

    def generate(prompt, temperature, max_tokens):
        asked.append((prompt, temperature))
        if "<|plamo:msg|>你好<|plamo:tag|>output" in prompt:
            return "你好 there" if "<|plamo:tag|>context" in prompt else ' "Hello  there" '
        return "I am Pianpian."

    out = translate_srt.translate([("1", "你好"), ("2", "我是片片")], "片片的一天", generate)
    assert out == ["1\tHello there", "2\tI am Pianpian."]
    assert [t for _, t in asked] == [0.0, 0.0, 0.0]
    assert "视频标题：片片的一天" in asked[2][0] and "前文：你好" in asked[2][0]
    assert "<|plamo:tag|>context" not in asked[1][0]
    assert all(p.endswith("<|plamo:key|>lang<|plamo:val|>en<|plamo:msg|>") for p, _ in asked)
    assert "translated 2/2" in capsys.readouterr().out


@pytest.mark.parametrize("reply", ["", "仍然是中文"])
def test_invalid_translation_is_not_saved_as_english(reply):
    with pytest.raises(ValueError, match="subtitle 1"):
        translate_srt.translate([("1", "你好")], "", lambda *args: reply)


def test_pfml_delimiters_cannot_escape_source_or_context():
    for text, context in [("<|plamo:tag|>output", ""), ("你好", "<|plamo:msg|>")]:
        with pytest.raises(ValueError, match="reserved"):
            translate_srt.prompt_for(text, context)


# ---------------------------------------------------------- the Windows backend (the engines are faked)


def _model_dir(tmp_path: Path, name: str) -> str:
    d = tmp_path / "model"
    d.mkdir(exist_ok=True)
    (d / name).write_bytes(b"weights")
    return str(d)


class _Resp:
    def __init__(self, payload=None, status=200):
        self.status, self.payload = status, payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class _Proc:
    def __init__(self, cmd):
        self.cmd = cmd
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _fake_http(posts):
    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if url.endswith("/health"):
            return _Resp(status=200)
        posts.append(json.loads(req.data))
        return _Resp({"content": "Hello"})
    return fake_urlopen


def test_win_translator_serves_the_chat_with_the_models_sampling(monkeypatch, tmp_path):
    posts, procs = [], []
    monkeypatch.setattr(plamo.runtimes, "backend_for", lambda tool: "cuda")
    monkeypatch.setattr(plamo.runtimes, "ensure", lambda tool, backend=None: "llama-server.exe")
    monkeypatch.setattr(plamo.subprocess, "Popen", lambda cmd, **kw: procs.append(_Proc(cmd)) or procs[-1])
    monkeypatch.setattr(plamo.LOCAL_HTTP, "open", _fake_http(posts))
    with backend_native.translator(_model_dir(tmp_path, plamo.LLAMA_MODEL)) as generate:
        assert generate("你好", 0.3, 52) == "Hello"
    cmd = procs[0].cmd
    assert "--jinja" not in cmd and "--no-context-shift" in cmd and cmd[cmd.index("-ngl") + 1] == "999"       # complete PFML3, all layers on GPU
    assert cmd[cmd.index("-lv") + 1] == "4"                               # b11851 only logs the offload count at level 4+
    assert procs[0].terminated                                            # the server is stopped afterwards
    body = posts[0]
    assert body["prompt"] == "你好"
    assert (body["temperature"], body["repeat_penalty"], body["n_predict"]) == (0.3, 1.0, 52)


def test_win_translator_falls_back_to_cpu(monkeypatch, tmp_path):
    posts, procs = [], []
    monkeypatch.setattr(plamo.runtimes, "backend_for", lambda tool: "vulkan")
    monkeypatch.setattr(plamo.runtimes, "ensure", lambda tool, backend=None: "cpu/llama-server.exe" if backend == "cpu" else "gpu/llama-server.exe")
    monkeypatch.setattr(plamo.subprocess, "Popen", lambda cmd, **kw: procs.append(_Proc(cmd)) or procs[-1])
    ready = iter([False, True])                                           # the Vulkan build never answers /health
    monkeypatch.setattr(plamo, "_wait_ready", lambda proc, port: next(ready))
    monkeypatch.setattr(plamo.LOCAL_HTTP, "open", _fake_http(posts))
    with backend_native.translator(_model_dir(tmp_path, plamo.LLAMA_MODEL)) as generate:
        assert generate("你好", 0.0, 10) == "Hello"
    assert procs[0].cmd[procs[0].cmd.index("-ngl") + 1] == "999"
    assert procs[1].cmd[procs[1].cmd.index("-ngl") + 1] == "0" and procs[1].cmd[0] == "cpu/llama-server.exe"


def test_win_translator_retries_a_gpu_launch_error(monkeypatch, tmp_path):
    calls, procs = [], []

    def start(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            raise OSError(193, "not a valid Win32 application")
        procs.append(_Proc(cmd))
        return procs[-1]

    monkeypatch.setattr(plamo.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(plamo.runtimes, "backend_for", lambda tool: "cuda")
    monkeypatch.setattr(plamo.runtimes, "ensure", lambda tool, backend=None: "cpu.exe" if backend == "cpu" else "gpu.exe")
    monkeypatch.setattr(plamo.subprocess, "Popen", start)
    monkeypatch.setattr(plamo.LOCAL_HTTP, "open", _fake_http([]))
    with backend_native.translator(_model_dir(tmp_path, plamo.LLAMA_MODEL)) as generate:
        assert generate("你好", 0.0, 10) == "Hello"
    assert [cmd[0] for cmd in calls] == ["gpu.exe", "cpu.exe"]
    assert procs[0].terminated and not list(tmp_path.glob("*.log"))


@pytest.mark.parametrize("failure", ["launch", "health"])
def test_win_translator_cleans_up_when_cpu_retry_fails(monkeypatch, tmp_path, failure):
    procs = []

    def start(cmd, **kw):
        if cmd[0] == "cpu.exe" and failure == "launch":
            raise OSError("CPU launch failed")
        procs.append(_Proc(cmd))
        return procs[-1]

    monkeypatch.setattr(plamo.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(plamo.runtimes, "backend_for", lambda tool: "cuda")
    monkeypatch.setattr(plamo.runtimes, "ensure", lambda tool, backend=None: "cpu.exe" if backend == "cpu" else "gpu.exe")
    monkeypatch.setattr(plamo.subprocess, "Popen", start)
    monkeypatch.setattr(plamo, "_wait_ready", lambda proc, port: False)
    with pytest.raises(OSError if failure == "launch" else SystemExit):
        with backend_native.translator(_model_dir(tmp_path, plamo.LLAMA_MODEL)):
            pytest.fail("a failed server must not yield a translator")
    assert procs and all(p.terminated for p in procs)
    assert not list(tmp_path.glob("*.log"))


def test_win_translator_prints_the_server_log_when_it_dies_mid_run(monkeypatch, tmp_path, capsys):
    # [simulated on macOS] the server answers /health, then drops the connection: its log tail reaches the job log
    def start(cmd, stdout, **kw):
        stdout.write("ggml_cuda: CUDA error: the launch timed out and was terminated\n")
        stdout.flush()
        return _Proc(cmd)

    def dead(req, timeout=None):
        if getattr(req, "full_url", req).endswith("/health"):
            return _Resp(status=200)
        raise ConnectionResetError("Remote end closed connection without response")

    monkeypatch.setattr(plamo.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(plamo.runtimes, "backend_for", lambda tool: "cuda")
    monkeypatch.setattr(plamo.runtimes, "ensure", lambda tool, backend=None: "gpu.exe")
    monkeypatch.setattr(plamo.subprocess, "Popen", start)
    monkeypatch.setattr(plamo.LOCAL_HTTP, "open", dead)
    with pytest.raises(OSError):
        with backend_native.translator(_model_dir(tmp_path, plamo.LLAMA_MODEL)) as generate:
            generate("你好", 0.0, 10)
    out = capsys.readouterr().out
    assert "llama-server stopped answering" in out and "the launch timed out" in out
    assert not list(tmp_path.glob("*.log"))


def test_win_translator_retains_the_offloaded_layer_count(monkeypatch, tmp_path, capsys):
    def start(cmd, stdout, **kw):
        stdout.write("ggml_cuda_init: found 1 CUDA device\nllama_model_load: offloaded 33/33 layers to GPU\n")
        stdout.flush()
        return _Proc(cmd)

    monkeypatch.setattr(plamo.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(plamo.runtimes, "backend_for", lambda tool: "cuda")
    monkeypatch.setattr(plamo.runtimes, "ensure", lambda tool, backend=None: "gpu.exe")
    monkeypatch.setattr(plamo.subprocess, "Popen", start)
    monkeypatch.setattr(plamo.LOCAL_HTTP, "open", _fake_http([]))
    with backend_native.translator(_model_dir(tmp_path, plamo.LLAMA_MODEL)):
        pass
    assert "offloaded 33/33 layers to GPU" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.log"))


@pytest.mark.parametrize("redirect", [False, True])
def test_win_translator_keeps_http_local_with_a_proxy_configured(monkeypatch, tmp_path, redirect):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(("GET", self.path, None))
            self.send_response(200 if self.path == "/health" else 502)
            self.end_headers()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(("POST", self.path, body))
            self.send_response(302 if redirect else 200)
            if redirect:
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/escaped")
            self.end_headers()
            self.wfile.write(b'{"content":"Hello"}')

        def log_message(self, *args):
            pass

    # The same server acts as a rejecting proxy: proxied requests use absolute URLs.
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            for name in ("http_proxy", "HTTP_PROXY"):
                monkeypatch.setenv(name, base)
            for name in ("no_proxy", "NO_PROXY"):
                monkeypatch.setenv(name, "example.invalid")
            monkeypatch.setattr(urllib.request, "_opener", None)
            importlib.reload(plamo)                  # construct its client with the proxy already configured
            proc = _Proc([])
            monkeypatch.setattr(plamo.tempfile, "gettempdir", lambda: str(tmp_path))
            monkeypatch.setattr(plamo.runtimes, "backend_for", lambda tool: "cpu")
            monkeypatch.setattr(plamo.runtimes, "ensure", lambda tool, backend=None: "unused.exe")
            monkeypatch.setattr(plamo, "_free_port", lambda: server.server_port)
            monkeypatch.setattr(plamo, "_start_server", lambda *args: proc)
            monkeypatch.setattr(plamo.time, "sleep", lambda _: pytest.fail("healthy local server was not reached directly"))
            with backend_native.translator(_model_dir(tmp_path, plamo.LLAMA_MODEL)) as generate:
                if redirect:
                    with pytest.raises(HTTPError) as error:
                        generate("你好", 0.3, 52)
                    assert error.value.code == 302
                else:
                    assert generate("你好", 0.3, 52) == "Hello"
            assert proc.terminated and not list(tmp_path.glob("*.log"))
            assert [(method, path) for method, path, _ in seen] == [("GET", "/health"), ("POST", "/completion")]
            assert seen[1][2]["prompt"] == "你好"
            # The model downloader still uses the configured proxy, not the local-only client.
            with pytest.raises(HTTPError) as error:
                models.urlopen(base + "/download", timeout=2)
            assert error.value.code == 502 and seen[-1][:2] == ("GET", base + "/download")
        finally:
            server.shutdown()
            thread.join()
            monkeypatch.undo()
            importlib.reload(plamo)


def test_catalog_and_lock_follow_the_platform(monkeypatch, tmp_path):
    lockfile = tmp_path / "models.lock.json"
    lockfile.write_text(json.dumps({"platforms": {"darwin": {"a/mac": {"files": []}}, "win32": {"b/win": {"files": []}}}}))
    try:
        monkeypatch.setattr(backend, "NAME", "win32")
        importlib.reload(models)
        monkeypatch.setattr(models, "LOCKFILE", lockfile)
        win = {m["id"] for m in models.ROWS if m["platform"] == "win32"}
        assert {m["id"] for m in models.CATALOG} == win      # the Mac rows are not offered on Windows
        assert set(models.lock()) == {"b/win"}
        assert models.default("transcribe") == "FunAudioLLM/SenseVoiceSmall-GGUF"
        monkeypatch.setattr(models, "CATALOG", [])
        with pytest.raises(LookupError):
            models.default("transcribe")
        monkeypatch.setattr(models, "CATALOG", [{"id": "b/win", "platform": "win32", "task": "transcribe"}])
        assert models.default("transcribe") == "b/win"
    finally:
        monkeypatch.undo()
        importlib.reload(models)
    assert {m["id"] for m in models.CATALOG} == {m["id"] for m in models.ROWS if m["platform"] == backend.NAME}
    for task in ("transcribe", "translate"):
        assert models.default(task) == next(m["id"] for m in models.CATALOG if m["task"] == task)


def test_current_models_use_the_same_compact_pins_on_both_platforms():
    platforms = json.loads(models.LOCKFILE.read_text(encoding="utf-8"))["platforms"]
    repo = "pfnet/plamo-3-translate-0.8b-GGUF"
    assert platforms["darwin"] == platforms["win32"]
    for platform, lock in platforms.items():
        assert set(lock) == {"FunAudioLLM/SenseVoiceSmall-GGUF", repo}
        assert {f["name"] for f in lock["FunAudioLLM/SenseVoiceSmall-GGUF"]["files"]} == {"sensevoice-small-q8.gguf", "fsmn-vad.gguf"}
        assert lock[repo]["files"] == [{"name": "plamo-3-translate-0.8b-Q3_K_M.gguf", "size": 486385856,
                                       "sha256": "6c64dd53a367966ec00a7335ff34bb77ad5a893b6fbc7bf9ae51f7241e0dbfbe", "modelscope": False}]
        assert sum(f["size"] for entry in lock.values() for f in entry["files"]) == 742314688
        row = next(m for m in models.ROWS if m["platform"] == platform and m["task"] == "translate")
        assert row["id"] == repo and "Hy-MT2" in row["replaces"]


def test_model_cache_requires_the_current_complete_files_and_revision(monkeypatch, tmp_path):
    entry = {"huggingface": "new-revision", "files": [{"name": "weights.bin", "size": 3, "sha256": "aa"}]}
    monkeypatch.setattr(models, "lock", lambda: {"a/model": entry})
    monkeypatch.setattr(models, "LEGACY", tmp_path / "legacy")
    monkeypatch.setenv("PIANPIAN_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    folder = models.cache() / "a__model"
    folder.mkdir(parents=True)
    done = folder / ".complete"

    done.write_text(models.lock_id(entry))                    # current marker, but the weight is missing
    assert models.local_path("a/model") is None
    (folder / "weights.bin").write_bytes(b"new")
    done.write_text("old-fingerprint")                       # same-sized files do not make an old install current
    assert models.local_path("a/model") is None
    done.write_text(models.lock_id(entry))
    assert models.local_path("a/model") == folder

    snapshots = tmp_path / "hub/models--a--model/snapshots"
    for revision in ("old-revision", "new-revision"):
        snap = snapshots / revision
        snap.mkdir(parents=True)
        (snap / "weights.bin").write_bytes(b"new")
    assert models.hf_cached("a/model", entry) == snapshots / "new-revision"


@pytest.mark.parametrize("replaces", ["a/fp16", ["a/fp16", "a/older-q8"]])
def test_renamed_model_cleanup_waits_for_its_replacement(monkeypatch, tmp_path, replaces):
    monkeypatch.setenv("PIANPIAN_MODELS", str(tmp_path / "models"))
    monkeypatch.setattr(models, "CATALOG", [{"id": "a/q8", "replaces": replaces}])
    old = models.cache() / "a__fp16"
    old.mkdir(parents=True)
    (old / "weights.safetensors").write_bytes(b"fp16")
    monkeypatch.setattr(models, "local_path", lambda repo: None)
    assert models.unused() == []
    assert [Path(m["path"]) for m in models.unused(include_pending=True)] == [old]
    assert models.remove_unused() == 0 and old.exists()
    monkeypatch.setattr(models, "local_path", lambda repo: models.cache() / "a__q8")
    assert [Path(m["path"]) for m in models.unused()] == [old]
    assert models.remove_unused() == 4 and not old.exists()


def test_make_lock_pins_every_platform(monkeypatch, tmp_path):
    lockfile = tmp_path / "models.lock.json"
    lockfile.write_text(json.dumps({"platforms": {"win32": {"b/win": {"files": []}}}}))
    names = {"FunAudioLLM/SenseVoiceSmall-GGUF": "sensevoice-small-q8.gguf", "FunAudioLLM/fsmn-vad-GGUF": "fsmn-vad.gguf",
             "pfnet/plamo-3-translate-0.8b-GGUF": "plamo-3-translate-0.8b-Q3_K_M.gguf"}

    def fake(url, timeout):
        name = next((n for repo, n in names.items() if repo in url), "config.json")
        if "modelscope" in url:
            body = {"Data": {"Files": [{"Type": "blob", "Path": name, "Size": 2, "Sha256": "aa", "Revision": "r1"}]}}
        else:
            body = {"sha": "vad-rev" if name == "fsmn-vad.gguf" else "h1",
                    "siblings": [{"rfilename": name, "size": 2, "lfs": {"sha256": "aa"}}]}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(models, "LOCKFILE", lockfile)
    monkeypatch.setattr(models, "urlopen", fake)
    out = models.make_lock()["platforms"]
    assert set(out) == {"darwin", "win32"} and "b/win" not in out["win32"]
    for m in models.ROWS:
        entry = out[m["platform"]][m["id"]]
        assert entry["huggingface"] == "h1"
        assert entry["files"] and entry["files"][0]["modelscope"] == (False if m.get("hf_only") else "r1")
        assert entry.get("modelscope_repo") == m.get("modelscope_repo")
        if m.get("companions"):
            assert entry["files"][1] == {"name": "fsmn-vad.gguf", "size": 2, "sha256": "aa", "modelscope": False,
                                          "repo": "FunAudioLLM/fsmn-vad-GGUF", "huggingface": "vad-rev"}


def test_windows_models_try_modelscope_before_hugging_face():
    entry = {"huggingface": "hf-rev", "modelscope_repo": "OllmOne/whisper.cpp",
             "files": [{"name": "ggml-large-v3-turbo.bin", "modelscope": "ms-rev"}]}
    urls = models.sources("ggerganov/whisper.cpp", entry, entry["files"][0])
    assert urls == [
        "https://www.modelscope.cn/models/OllmOne/whisper.cpp/resolve/ms-rev/ggml-large-v3-turbo.bin",
        "https://www.modelscope.cn/models/OllmOne/whisper.cpp/resolve/master/ggml-large-v3-turbo.bin",
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/hf-rev/ggml-large-v3-turbo.bin",
        "https://hf-mirror.com/ggerganov/whisper.cpp/resolve/hf-rev/ggml-large-v3-turbo.bin",
    ]
    windows = json.loads(models.LOCKFILE.read_text(encoding="utf-8"))["platforms"]["win32"]
    translation = windows["pfnet/plamo-3-translate-0.8b-GGUF"]
    assert all(f["modelscope"] is False for f in translation["files"])
    assert all("modelscope" in f for entry in windows.values() for f in entry["files"])
    repo = "FunAudioLLM/SenseVoiceSmall-GGUF"
    speech = windows[repo]
    assert speech["files"][0]["name"] == "sensevoice-small-q8.gguf"
    assert all(f["modelscope"] is False for f in speech["files"])
    assert all("modelscope.cn" not in url for f in speech["files"] for url in models.sources(repo, speech, f))
    vad = speech["files"][1]
    assert models.sources(repo, speech, vad) == [
        f"https://huggingface.co/{vad['repo']}/resolve/{vad['huggingface']}/fsmn-vad.gguf",
        f"https://hf-mirror.com/{vad['repo']}/resolve/{vad['huggingface']}/fsmn-vad.gguf"]


def test_lock_falls_back_when_the_mirror_lacks_the_selected_quantization(monkeypatch):
    row = {"id": "ggerganov/whisper.cpp", "platform": "win32"}
    pinned = {"name": "ggml-large-v3-turbo-q8_0.bin", "size": 2, "sha256": "aa"}
    monkeypatch.setattr(models, "ROWS", [row])
    monkeypatch.setattr(models, "hf_files", lambda m: ("hf-rev", [pinned]))
    monkeypatch.setattr(models, "ms_files", lambda m: [])
    entry = models.make_lock()["platforms"]["win32"][row["id"]]
    assert entry == {"huggingface": "hf-rev", "files": [{**pinned, "modelscope": False}]}


def test_setup_model_sizes_use_the_pinned_files(monkeypatch):
    monkeypatch.setattr(models, "CATALOG", [{"id": "a/model", "size": 100}])
    monkeypatch.setattr(models, "lock", lambda: {"a/model": {"files": [{"size": 2}, {"size": 3}]}})
    monkeypatch.setattr(models, "local_path", lambda repo: None)
    assert models.status()[0]["size"] == 5


def test_companion_download_shares_cache_and_must_pass_hash_before_completion(monkeypatch, tmp_path):
    import hashlib

    repo = "speech/model"
    entry = {"huggingface": "speech-rev", "files": [
        {"name": "speech.gguf", "size": 3, "sha256": hashlib.sha256(b"asr").hexdigest(), "modelscope": False},
        {"name": "vad.gguf", "size": 3, "sha256": hashlib.sha256(b"vad").hexdigest(), "modelscope": False,
         "repo": "speech/vad", "huggingface": "vad-rev"}]}
    monkeypatch.setattr(models, "lock", lambda: {repo: entry})
    monkeypatch.setattr(models, "LEGACY", tmp_path / "legacy")
    monkeypatch.setenv("PIANPIAN_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    valid = False
    urls = []

    def fetch(url, target, size, label):
        urls.append(url)
        target.write_bytes(b"asr" if target.name == "speech.gguf" else b"vad" if valid else b"bad")

    monkeypatch.setattr(models, "fetch", fetch)
    with pytest.raises(SystemExit, match="could not download vad.gguf"):
        models.ensure(repo)
    folder = models.cache() / models.folder_name(repo)
    assert (folder / "speech.gguf").read_bytes() == b"asr"
    assert not (folder / ".complete").exists() and not (folder / "vad.gguf").exists()
    assert all("speech/vad/resolve/vad-rev/" in url for url in urls if url.endswith("vad.gguf"))
    valid = True
    assert models.ensure(repo) == str(folder)
    assert (folder / "vad.gguf").read_bytes() == b"vad"
    assert (folder / ".complete").read_text().strip() == models.lock_id(entry)
    assert models.local_path(repo) == folder


def test_fetch_starts_over_when_the_part_file_is_too_long(monkeypatch, tmp_path):
    # seen 31 Oct 2026: two app instances appended to one .part, which grew past the pinned size and
    # every resume then failed with HTTP 416 — the file must be restarted, not resumed
    from urllib.error import HTTPError
    data = b"x" * 100
    seen = []

    def fake(req, timeout):
        seen.append(dict(req.headers))
        if "Range" in req.headers:
            raise HTTPError(req.full_url, 416, "Range Not Satisfiable", {}, None)
        return io.BytesIO(data)

    monkeypatch.setattr(models, "urlopen", fake)
    target = tmp_path / "f.bin"
    (tmp_path / "f.bin.part").write_bytes(b"y" * 150)          # longer than the pinned 100 bytes
    models.fetch("https://example.com/f.bin", target, 100, "test")
    assert target.read_bytes() == data and seen == [{}]        # restarted, without a Range header

    target.unlink()
    (tmp_path / "f.bin.part").write_bytes(data)                # fetched whole, never renamed
    models.fetch("https://example.com/f.bin", target, 100, "test")
    assert target.read_bytes() == data and seen == [{}]        # no request at all


def test_download_restarts_after_416_and_still_checks_the_hash(monkeypatch, tmp_path, capsys):
    from urllib.error import HTTPError
    good, bad = b"pinned bytes", b"other bytes!"
    seen = []

    def fake(req, timeout):
        seen.append(dict(req.headers))
        if "Range" in req.headers:
            raise HTTPError(req.full_url, 416, "Range Not Satisfiable", {}, None)
        return io.BytesIO(bad if len(seen) == 2 else good)

    monkeypatch.setattr(models, "urlopen", fake)
    target = tmp_path / "f.bin"
    target.with_suffix(".bin.part").write_bytes(good[:3])
    models.download(["https://example.com/f.bin"], target, len(good), models.hashlib.sha256(good).hexdigest(), "test")
    assert seen == [{"Range": "bytes=3-"}, {}, {}]
    assert target.read_bytes() == good and "checksum does not match" in capsys.readouterr().out


def test_download_skips_a_source_with_the_wrong_bytes(monkeypatch, tmp_path, capsys):
    good, bad = b"pinned bytes", b"other bytes!"
    fetched = []
    monkeypatch.setattr(models, "fetch", lambda url, target, size, label: fetched.append(url) or target.write_bytes(good if "good" in url else bad))
    target = tmp_path / "f.bin"
    pin = models.hashlib.sha256(good).hexdigest()

    models.download(["https://bad.example/f.bin", "https://good.example/f.bin"], target, len(good), pin, "test")
    assert target.read_bytes() == good and "checksum does not match" in capsys.readouterr().out

    fetched.clear()
    models.download(["https://good.example/f.bin"], target, len(good), pin, "test")
    assert fetched == []                                  # already complete: nothing is fetched

    target.unlink()
    models.download(["https://bad.example/f.bin"], target, len(bad), None, "test")
    assert target.read_bytes() == bad                     # no pinned hash: the size decides

    target.unlink()
    with pytest.raises(OSError):
        models.download(["https://bad.example/f.bin"], target, len(good), pin, "test")
    assert not target.exists()
