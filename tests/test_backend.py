"""The engine contract (pipeline/backend.py) and the parts around it that every backend shares.

The real engines (MLX, whisper.cpp, llama.cpp) can't run in CI, so these tests fake them: what they
pin is the shape of what a backend hands to the rest of the pipeline. A new backend adds its cases here
and checks its output with assert_transcribe_output and assert_ocr_lines.
"""
import importlib
import inspect
import io
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "pipeline")]
import backend  # noqa: E402
import backend_mac  # noqa: E402  (imports on any OS: the engines load inside the functions)
import backend_win  # noqa: E402  (same: runtimes and srt_tool are stdlib-only imports)
import models  # noqa: E402
import srt_tool  # noqa: E402
import translate_srt  # noqa: E402


def assert_transcribe_output(srt: Path, words_json: Path) -> None:
    """What transcribe() must leave: the two files and nothing else, an .srt srt_tool reads, and word times."""
    assert sorted(p.name for p in srt.parent.iterdir() if p.name not in ("audio.wav",)) == sorted([srt.name, words_json.name])
    assert srt_tool.read_srt(srt)
    times = srt_tool.char_times(words_json)
    assert times and all(isinstance(c, str) and 0 <= s <= e for c, s, e in times)


def assert_ocr_lines(text: str) -> None:
    """What ocr() must return: one "name<TAB>text" line per frame, in frame order."""
    names = [line.partition("\t")[0] for line in text.splitlines()]
    assert names and names == sorted(names) and all(line.count("\t") >= 1 for line in text.splitlines())


def test_the_promised_signatures():
    # what the review of PR #11 promised the Windows backend; a change here is a change of contract
    def params(f):
        return list(inspect.signature(f).parameters)
    assert params(models.download) == ["urls", "target", "size", "sha256", "label"]
    assert params(models.default) == ["task"]
    impl = backend.impl()
    assert params(impl.transcribe) == ["audio", "model_dir", "srt", "words_json"]
    assert params(impl.translator) == ["model_dir"]
    assert params(impl.ocr) == ["frames_dir"]


def test_this_platform_has_the_three_functions():
    assert backend.impl().__name__ == ("backend_win" if backend.NAME == "win32" else "backend_mac")


def test_mac_transcribe_writes_what_srt_tool_reads(monkeypatch, tmp_path):
    calls = []

    def fake_whisper(cmd, check):                      # what mlx_whisper writes with --output-format all
        calls.append(cmd)
        out, name = Path(cmd[cmd.index("--output-dir") + 1]), cmd[cmd.index("--output-name") + 1]
        (out / f"{name}.srt").write_text("1\n00:00:00,000 --> 00:00:01,500\n你好\n", encoding="utf-8")
        (out / f"{name}.json").write_text(json.dumps({"segments": [{"start": 0.0, "end": 1.5, "text": "你好",
                                          "words": [{"word": "你好", "start": 0.0, "end": 1.5}]}]}), encoding="utf-8")
        for ext in ("txt", "vtt", "tsv"):
            (out / f"{name}.{ext}").write_text("", encoding="utf-8")

    monkeypatch.setattr(backend_mac, "ffmpeg_on_path", lambda: None)
    monkeypatch.setattr(backend_mac.subprocess, "run", fake_whisper)
    srt, words = tmp_path / "zh.long.srt", tmp_path / "zh.whisper.json"
    backend_mac.transcribe(tmp_path / "audio.wav", "model-dir", srt, words)

    assert_transcribe_output(srt, words)
    assert srt_tool.char_times(words) == [("你", 0.0, 0.75), ("好", 0.75, 1.5)]
    # the settings that keep long videos from looping and the script Simplified
    cmd = calls[0]
    assert cmd[cmd.index("--condition-on-previous-text") + 1] == "False"
    assert "以下是普通话的句子，使用简体中文。" in cmd and cmd[cmd.index("--model") + 1] == "model-dir"


def test_translate_retries_once_when_chinese_survives(capsys):
    asked = []

    def generate(prompt, temperature, max_tokens):
        asked.append((prompt, temperature))
        line = prompt.rsplit("\n", 1)[-1]                # the text to translate comes last
        if line == "你好" and temperature:
            return "<think>…</think> 你好 there"          # still Chinese: one greedy retry
        return ' "Hello  there" ' if line == "你好" else "I am Pianpian."

    out = translate_srt.translate([("1", "你好"), ("2", "我是片片")], "片片的一天", generate)
    assert out == ["1\tHello there", "2\tI am Pianpian."]
    assert [t for _, t in asked] == [0.3, 0.0, 0.3]
    assert "视频标题：片片的一天" in asked[2][0] and "前文：你好" in asked[2][0]
    assert "translated 2/2" in capsys.readouterr().out


def test_mac_translator_applies_the_chat_template(monkeypatch):
    calls = []
    tok = type("Tok", (), {"apply_chat_template": lambda self, msgs, **kw: f"<user>{msgs[0]['content']}</user>"})()
    lm = type(sys)("mlx_lm")
    lm.load = lambda path: ("model", tok)
    lm.generate = lambda model, tok, prompt, **kw: calls.append((prompt, kw)) or "Hello"
    utils = type(sys)("mlx_lm.sample_utils")
    utils.make_sampler = lambda temp, top_p, top_k: ("sampler", temp, top_p, top_k)
    utils.make_logits_processors = lambda repetition_penalty: ("penalty", repetition_penalty)
    monkeypatch.setitem(sys.modules, "mlx_lm", lm)
    monkeypatch.setitem(sys.modules, "mlx_lm.sample_utils", utils)
    with backend_mac.translator("model-dir") as generate:
        assert generate("你好", 0.0, 52) == "Hello"
    prompt, kw = calls[0]
    assert prompt == "<user>你好</user>" and kw["max_tokens"] == 52
    assert kw["sampler"] == ("sampler", 0.0, 0.6, 20) and kw["logits_processors"] == ("penalty", 1.05)


def test_mac_ocr_runs_the_swift_helper(monkeypatch):
    seen = []
    monkeypatch.setattr(backend_mac.subprocess, "run",
                        lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "00001.png\t你好\n00002.png\t你好\n"))
    assert_ocr_lines(backend_mac.ocr("frames"))
    assert seen[0][-1] == "frames" and ("ocr_frames" in seen[0][0] or seen[0][0] == "swift")


# ---------------------------------------------------------- the Windows backend (the engines are faked)
def _cpp_json(base: Path) -> None:
    """What whisper.cpp -ojf writes: millisecond offsets and tokens, with control tokens mixed in."""
    Path(str(base) + ".json").write_text(json.dumps({"transcription": [{
        "offsets": {"from": 0, "to": 1050}, "text": "你好 我叫",
        "tokens": [{"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}},
                   {"text": "你好", "offsets": {"from": 0, "to": 530}},
                   {"text": " 我", "offsets": {"from": 530, "to": 790}},
                   {"text": "叫", "offsets": {"from": 790, "to": 1050}},
                   {"text": "[_TT_1]", "offsets": {"from": 1050, "to": 1050}}]}]}), encoding="utf-8")


def _model_dir(tmp_path: Path, name: str) -> str:
    d = tmp_path / "model"
    d.mkdir(exist_ok=True)
    (d / name).write_bytes(b"weights")
    return str(d)


def _out(tmp_path: Path) -> tuple[Path, Path]:
    """The folder transcribe() writes to (the contract: only the srt and the words json may be left in it)."""
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return out / "zh.long.srt", out / "zh.whisper.json"


def test_win_transcribe_writes_what_srt_tool_reads(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, check):
        calls.append(cmd)
        _cpp_json(Path(cmd[cmd.index("-of") + 1]))

    monkeypatch.setattr(backend_win.runtimes, "backend_for", lambda tool: "cuda")
    monkeypatch.setattr(backend_win.runtimes, "ensure", lambda tool: "whisper-cli.exe")
    monkeypatch.setattr(backend_win.subprocess, "run", fake_run)
    srt, words = _out(tmp_path)
    backend_win.transcribe(tmp_path / "audio.wav", _model_dir(tmp_path, backend_win.WHISPER_MODEL), srt, words)

    assert_transcribe_output(srt, words)
    assert [c for c, _, _ in srt_tool.char_times(words)] == list("你好我叫")
    cmd = calls[0]
    assert cmd[cmd.index("-m") + 1].endswith(backend_win.WHISPER_MODEL)
    assert cmd[cmd.index("-mc") + 1] == "0"      # no conditioning on previous text, like the MLX path


def test_win_transcribe_retries_on_cpu_when_the_gpu_build_fails(monkeypatch, tmp_path):
    runs = []

    def fake_run(cmd, check):
        runs.append(cmd)
        if len(runs) == 1:
            raise subprocess.CalledProcessError(1, cmd)     # the CUDA build won't start
        _cpp_json(Path(cmd[cmd.index("-of") + 1]))

    monkeypatch.setattr(backend_win.runtimes, "backend_for", lambda tool: "cuda")
    monkeypatch.setattr(backend_win.runtimes, "ensure", lambda tool: "gpu/whisper-cli.exe")
    monkeypatch.setattr(backend_win.runtimes, "ensure_cpu", lambda tool: "cpu/whisper-cli.exe")
    monkeypatch.setattr(backend_win.subprocess, "run", fake_run)
    srt, words = _out(tmp_path)
    backend_win.transcribe(tmp_path / "audio.wav", _model_dir(tmp_path, backend_win.WHISPER_MODEL), srt, words)
    assert_transcribe_output(srt, words)
    assert len(runs) == 2 and "-ng" not in runs[0] and "-ng" in runs[1]   # GPU, then the CPU build


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
        return _Resp({"choices": [{"message": {"content": "Hello"}}]})
    return fake_urlopen


def test_win_translator_serves_the_chat_with_the_models_sampling(monkeypatch, tmp_path):
    posts, procs = [], []
    monkeypatch.setattr(backend_win.runtimes, "backend_for", lambda tool: "cuda")
    monkeypatch.setattr(backend_win.runtimes, "ensure", lambda tool: "llama-server.exe")
    monkeypatch.setattr(backend_win.subprocess, "Popen", lambda cmd, **kw: procs.append(_Proc(cmd)) or procs[-1])
    monkeypatch.setattr(backend_win, "urlopen", _fake_http(posts))
    with backend_win.translator(_model_dir(tmp_path, backend_win.LLAMA_MODEL)) as generate:
        assert generate("你好", 0.3, 52) == "Hello"
    cmd = procs[0].cmd
    assert "--jinja" in cmd and cmd[cmd.index("-ngl") + 1] == "999"       # the GGUF's chat template, all layers on the GPU
    assert procs[0].terminated                                            # the server is stopped afterwards
    body = posts[0]
    assert body["messages"] == [{"role": "user", "content": "你好"}]
    # the MLX path's sampling values reach the server: 0.3 then greedy (translate_srt), top_p/top_k/penalty of the card
    assert (body["temperature"], body["top_p"], body["top_k"], body["repeat_penalty"], body["max_tokens"]) == (0.3, 0.6, 20, 1.05, 52)


def test_win_translator_falls_back_to_cpu(monkeypatch, tmp_path):
    posts, procs = [], []
    monkeypatch.setattr(backend_win.runtimes, "backend_for", lambda tool: "vulkan")
    monkeypatch.setattr(backend_win.runtimes, "ensure", lambda tool: "gpu/llama-server.exe")
    monkeypatch.setattr(backend_win.runtimes, "ensure_cpu", lambda tool: "cpu/llama-server.exe")
    monkeypatch.setattr(backend_win.subprocess, "Popen", lambda cmd, **kw: procs.append(_Proc(cmd)) or procs[-1])
    ready = iter([False, True])                                           # the Vulkan build never answers /health
    monkeypatch.setattr(backend_win, "_wait_ready", lambda proc, port: next(ready))
    monkeypatch.setattr(backend_win, "urlopen", _fake_http(posts))
    with backend_win.translator(_model_dir(tmp_path, backend_win.LLAMA_MODEL)) as generate:
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

    monkeypatch.setattr(backend_win.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(backend_win.runtimes, "backend_for", lambda tool: "cuda")
    monkeypatch.setattr(backend_win.runtimes, "ensure", lambda tool: "gpu.exe")
    monkeypatch.setattr(backend_win.runtimes, "ensure_cpu", lambda tool: "cpu.exe")
    monkeypatch.setattr(backend_win.subprocess, "Popen", start)
    monkeypatch.setattr(backend_win, "urlopen", _fake_http([]))
    with backend_win.translator(_model_dir(tmp_path, backend_win.LLAMA_MODEL)) as generate:
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

    monkeypatch.setattr(backend_win.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(backend_win.runtimes, "backend_for", lambda tool: "cuda")
    monkeypatch.setattr(backend_win.runtimes, "ensure", lambda tool: "gpu.exe")
    monkeypatch.setattr(backend_win.runtimes, "ensure_cpu", lambda tool: "cpu.exe")
    monkeypatch.setattr(backend_win.subprocess, "Popen", start)
    monkeypatch.setattr(backend_win, "_wait_ready", lambda proc, port: False)
    with pytest.raises(OSError if failure == "launch" else SystemExit):
        with backend_win.translator(_model_dir(tmp_path, backend_win.LLAMA_MODEL)):
            pytest.fail("a failed server must not yield a translator")
    assert procs and all(p.terminated for p in procs)
    assert not list(tmp_path.glob("*.log"))


def test_win_translator_retains_the_offloaded_layer_count(monkeypatch, tmp_path, capsys):
    def start(cmd, stdout, **kw):
        stdout.write("ggml_cuda_init: found 1 CUDA device\nllama_model_load: offloaded 33/33 layers to GPU\n")
        stdout.flush()
        return _Proc(cmd)

    monkeypatch.setattr(backend_win.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(backend_win.runtimes, "backend_for", lambda tool: "cuda")
    monkeypatch.setattr(backend_win.runtimes, "ensure", lambda tool: "gpu.exe")
    monkeypatch.setattr(backend_win.subprocess, "Popen", start)
    monkeypatch.setattr(backend_win, "urlopen", _fake_http([]))
    with backend_win.translator(_model_dir(tmp_path, backend_win.LLAMA_MODEL)):
        pass
    assert "offloaded 33/33 layers to GPU" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.log"))


def test_win_ocr_reads_frames_with_rapidocr(monkeypatch, tmp_path):
    for name in ("00001.png", "00002.png"):
        (tmp_path / name).write_bytes(b"png")
    rocr = type(sys)("rapidocr_onnxruntime")

    class FakeRapidOCR:
        def __call__(self, path):
            return [([[0, 20], [10, 20], [10, 30], [0, 30]], "第二行", 0.9),
                    ([[0, 0], [10, 0], [10, 10], [0, 10]], "第一行", 0.9),
                    ([[0, 40], [10, 40], [10, 50], [0, 50]], "噪声", 0.4)], 1.0

    rocr.RapidOCR = FakeRapidOCR
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", rocr)
    out = backend_win.ocr(str(tmp_path))
    assert_ocr_lines(out)
    assert out.splitlines()[0] == "00001.png\t第一行 第二行"              # reading order, and the unsure box dropped


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
        assert models.default("transcribe") == "ggerganov/whisper.cpp"
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


def test_mac_installs_keep_their_models():
    # .complete holds this fingerprint: it changes only when a model update should make every Mac download again
    lock = json.loads(models.LOCKFILE.read_text(encoding="utf-8"))["platforms"]["darwin"]
    assert models.lock_id(lock["mlx-community/whisper-large-v3-turbo"]) == "950cefa3ce3484fb"
    assert models.lock_id(lock["mlx-community/Hy-MT2-1.8B-4bit"]) == "b12bda06891875f9"


def test_make_lock_pins_every_platform(monkeypatch, tmp_path):
    lockfile = tmp_path / "models.lock.json"
    lockfile.write_text(json.dumps({"platforms": {"win32": {"b/win": {"files": []}}}}))
    names = {"ggerganov/whisper.cpp": "ggml-large-v3-turbo.bin", "OllmOne/whisper.cpp": "ggml-large-v3-turbo.bin",
             "tencent/Hy-MT2-1.8B-GGUF": "Hy-MT2-1.8B-Q4_K_M.gguf", "Tencent-Hunyuan/Hy-MT2-1.8B-GGUF": "Hy-MT2-1.8B-Q4_K_M.gguf"}

    def fake(url, timeout):
        name = next((n for repo, n in names.items() if repo in url), "config.json")
        if "modelscope" in url:
            body = {"Data": {"Files": [{"Type": "blob", "Path": name, "Size": 2, "Sha256": "aa", "Revision": "r1"}]}}
        else:
            body = {"sha": "h1", "siblings": [{"rfilename": name, "size": 2, "lfs": {"sha256": "aa"}}]}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(models, "LOCKFILE", lockfile)
    monkeypatch.setattr(models, "urlopen", fake)
    out = models.make_lock()["platforms"]
    assert set(out) == {"darwin", "win32"} and "b/win" not in out["win32"]
    for m in models.ROWS:
        entry = out[m["platform"]][m["id"]]
        assert entry["huggingface"] == "h1"
        assert entry["files"] and entry["files"][0]["modelscope"] == "r1"
        assert entry.get("modelscope_repo") == m.get("modelscope_repo")


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
    assert windows["ggerganov/whisper.cpp"]["modelscope_repo"] == "OllmOne/whisper.cpp"
    assert windows["tencent/Hy-MT2-1.8B-GGUF"]["modelscope_repo"] == "Tencent-Hunyuan/Hy-MT2-1.8B-GGUF"
    assert all(f.get("modelscope") for entry in windows.values() for f in entry["files"])


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


def test_align_stops_with_one_line_without_mlx(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlx", None)        # as on a machine without MLX
    with pytest.raises(SystemExit) as stop:
        runpy.run_path(str(ROOT / "pipeline" / "align_srt.py"), run_name="align")
    assert "need MLX" in str(stop.value.code)
