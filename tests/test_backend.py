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


def test_catalog_and_lock_follow_the_platform(monkeypatch, tmp_path):
    lockfile = tmp_path / "models.lock.json"
    lockfile.write_text(json.dumps({"platforms": {"darwin": {"a/mac": {"files": []}}, "win32": {"b/win": {"files": []}}}}))
    try:
        monkeypatch.setattr(backend, "NAME", "win32")
        importlib.reload(models)
        monkeypatch.setattr(models, "LOCKFILE", lockfile)
        assert models.CATALOG == [] and set(models.lock()) == {"b/win"}      # the Mac rows are not offered on Windows
        with pytest.raises(LookupError):
            models.default("transcribe")
        monkeypatch.setattr(models, "CATALOG", [{"id": "b/win", "platform": "win32", "task": "transcribe"}])
        assert models.default("transcribe") == "b/win"
    finally:
        monkeypatch.undo()
        importlib.reload(models)
    assert models.default("transcribe") == "mlx-community/whisper-large-v3-turbo"
    assert models.default("translate") == "mlx-community/Hy-MT2-1.8B-4bit"


def test_mac_installs_keep_their_models():
    # .complete holds this fingerprint: it changes only when a model update should make every Mac download again
    lock = models.lock()
    assert models.lock_id(lock["mlx-community/whisper-large-v3-turbo"]) == "950cefa3ce3484fb"
    assert models.lock_id(lock["mlx-community/Hy-MT2-1.8B-4bit"]) == "b12bda06891875f9"


def test_make_lock_keeps_the_other_platforms(monkeypatch, tmp_path):
    lockfile = tmp_path / "models.lock.json"
    lockfile.write_text(json.dumps({"platforms": {"win32": {"b/win": {"files": []}}}}))
    ms = {"Data": {"Files": [{"Type": "blob", "Path": "config.json", "Size": 2, "Sha256": "aa", "Revision": "r1"}]}}
    hf = {"sha": "h1", "siblings": [{"rfilename": "config.json"}]}
    monkeypatch.setattr(models, "LOCKFILE", lockfile)
    monkeypatch.setattr(models, "urlopen", lambda url, timeout: io.BytesIO(json.dumps(ms if "modelscope" in url else hf).encode()))
    out = models.make_lock()["platforms"]
    assert out["win32"] == {"b/win": {"files": []}}
    assert {m["id"] for m in models.CATALOG} == set(out["darwin"])


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
