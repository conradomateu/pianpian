"""The pipeline's retry rule (temporary failures are tried again, real ones are not), and which steps a job runs."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "pipeline")]
import study  # noqa: E402


def test_what_counts_as_temporary():
    for text in ("ERROR: [BiliBili] x: Unable to download webpage: HTTP Error 412: Precondition Failed", "HTTP Error 503: Service Unavailable",
                 "HTTP Error 429: Too Many Requests", "The read operation timed out", "Connection reset by peer"):
        assert study.TRANSIENT.search(text), text
    for text in ("ERROR: Unsupported URL: https://example.com", "HTTP Error 404: Not Found", "Video unavailable", "No video formats found!",
                 "ERROR: [BiliBili] This video requires login"):
        assert not study.TRANSIENT.search(text), text


def test_retries_then_gives_up_and_never_retries_a_real_error(monkeypatch, capsys):
    monkeypatch.setattr(study.time, "sleep", lambda s: None)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "ERROR: HTTP Error 412: Precondition Failed")
    monkeypatch.setattr(study.subprocess, "run", fake_run)
    try:
        study.ytdlp_out(["yt-dlp", "x"])
        raise AssertionError("should have failed")
    except subprocess.CalledProcessError:
        pass
    assert len(calls) == study.TRIES and "trying again" in capsys.readouterr().out

    calls.clear()
    monkeypatch.setattr(study.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), subprocess.CompletedProcess(cmd, 1, "", "ERROR: Unsupported URL"))[1])
    try:
        study.ytdlp_out(["yt-dlp", "x"])
    except subprocess.CalledProcessError:
        pass
    assert len(calls) == 1                                       # an unsupported link is not going to get better


def test_succeeds_on_a_later_try(monkeypatch):
    monkeypatch.setattr(study.time, "sleep", lambda s: None)
    answers = [subprocess.CompletedProcess([], 1, "", "HTTP Error 412"), subprocess.CompletedProcess([], 0, "2008926\n", "")]
    monkeypatch.setattr(study.subprocess, "run", lambda cmd, **kw: answers.pop(0))
    assert study.ytdlp_out(["yt-dlp", "x"]).split()[0] == "2008926"


def test_streaming_retry_with_a_real_process(monkeypatch, tmp_path, capsys):
    """A stand-in for yt-dlp that answers 412 twice and then works: the output must reach the log live, and it must succeed."""
    monkeypatch.setattr(study.time, "sleep", lambda s: None)
    counter = tmp_path / "n"
    script = ("import pathlib,sys; f=pathlib.Path(sys.argv[1]); n=int(f.read_text()) if f.exists() else 0; f.write_text(str(n+1)); "
              "print('[download]  50.0% of 1MiB'); "
              "(print('ERROR: [BiliBili] x: Unable to download webpage: HTTP Error 412: Precondition Failed'), sys.exit(1)) if n < 2 else print('done')")
    study.ytdlp_stream([sys.executable, "-c", script, str(counter)])
    out = capsys.readouterr().out
    assert counter.read_text() == "3" and out.count("trying again") == 2 and out.rstrip().endswith("done")


def test_word_links_run_only_where_the_backend_can_align(monkeypatch, tmp_path):
    # align_srt.py needs MLX: on Windows (no align() in backend_win) a job must not start it, fail and log
    # "No module named 'mlx'", which report.explain() would then blame for a later failure
    import types
    for name in ("source.mp4", "zh.srt", "zh.en.srt", "en.lines.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(study, "get_video", lambda src, browser: tmp_path)
    monkeypatch.setattr(study, "tool", lambda *a: None)
    monkeypatch.setattr(study, "mux", lambda video, hardsubs: None)
    monkeypatch.setattr(study, "run", lambda *cmd, **kw: pytest.fail(f"unexpected step {cmd}"))
    monkeypatch.setattr(sys, "argv", ["study.py", str(tmp_path / "source.mp4")])
    aligned = []
    monkeypatch.setattr(study.backend, "impl", lambda: types.SimpleNamespace())          # like backend_win
    study.main()
    assert aligned == []
    monkeypatch.setattr(study.backend, "impl", lambda: types.SimpleNamespace(align=lambda zh, en: aligned.append((zh, en))))
    study.main()
    assert aligned == [(Path("zh.srt"), Path("zh.en.srt"))]


def test_segmentation_upgrade_refreshes_cached_tracks_without_redoing_sources(monkeypatch, tmp_path):
    import srt_tool
    monkeypatch.chdir(tmp_path)
    for key in ("HARDSUBS", "RESPLIT", "FORCE_EN", "SPLIT_MAX"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AUTO_EN", "1")
    pipeline = tmp_path / "pipeline"
    pipeline.mkdir()
    for name in ("srt_tool.py", "align_srt.py", "pinyin_fixes.txt"):
        path = pipeline / name
        path.write_text("old code", encoding="utf-8")
        os.utime(path, (100, 100))
    monkeypatch.setattr(study, "HERE", pipeline)
    monkeypatch.setattr(study, "FIXES", pipeline / "pinyin_fixes.txt")
    timing = "1\n00:00:01,000 --> 00:00:03,000\n"
    source = {"source.mp4": "unused video", "zh.srt": timing + "今天天气。\n", "zh.long.srt": timing + "今天天气。\n",
              "en.lines.txt": "1\tToday's weather.\n", "zh.whisper.json": json.dumps({"segments": [{"words": [
                  {"word": "今天天气。", "start": 1, "end": 3}]}]}), ".split": "18\n", ".from-whisper": ""}
    cached = {"zh.en.srt": timing + "Today's weather.\n", "zh.pinyin.srt": timing + "jīntiāntiānqì.\n",
              "zh.zh-pinyin.srt": "old combined track", "zh.words.json": "old word boundaries", "zh.align.json": "old links",
              "zh.lines.txt": "1\t今天天气。\n"}
    for files, stamp in ((source, 100), (cached, 200)):
        for name, text in files.items():
            Path(name).write_text(text, encoding="utf-8")
            os.utime(name, (stamp, stamp))
    os.utime("zh.align.json", (201, 201))
    preserved = {name: (Path(name).read_bytes(), Path(name).stat().st_mtime_ns) for name in [*source, "zh.en.srt", "zh.lines.txt"]}
    monkeypatch.setattr(srt_tool, "_DICT", {"今天": [["11", "today", ""]], "天气": [["14", "weather", ""]]})
    monkeypatch.setattr(sys, "argv", ["study.py", str(tmp_path / "source.mp4")])
    monkeypatch.setattr(study, "run", lambda *cmd, **kw: pytest.fail(f"unexpected transcription/translation: {cmd}"))
    calls, clock = [], 1000

    def fresh(name):
        nonlocal clock
        clock += 1
        os.utime(name, (clock, clock))

    def tool(*args):
        calls.append(args[0])
        with monkeypatch.context() as m:
            m.setattr(sys, "argv", ["srt_tool.py", *args])
            srt_tool.main()
        for name in {"pinyin": ["zh.pinyin.srt", "zh.zh-pinyin.srt"], "words": ["zh.words.json"],
                     "stack": ["zh.trilingual.srt"], "ass": ["zh.pinyin-en.ass"]}[args[0]]:
            fresh(name)

    def align(zh, en):
        calls.append("align")
        cue = json.loads(Path("zh.words.json").read_text(encoding="utf-8"))["cues"][0]
        assert [w[0] for w in cue["w"][0]] == ["今天", "天气", "。"]
        assert cue["k"] == [[[1, 2], [2, 3], 0]]
        Path("zh.align.json").write_text("new links", encoding="utf-8")
        fresh("zh.align.json")

    monkeypatch.setattr(study, "tool", tool)
    monkeypatch.setattr(study.backend, "impl", lambda: SimpleNamespace(align=align))
    monkeypatch.setattr(study, "mux", lambda *args: calls.append("mux"))
    study.main()
    assert calls == ["stack", "ass", "mux"]                     # all cached tracks are initially current
    os.utime(pipeline / "srt_tool.py", (300, 300))
    calls.clear()
    study.main()
    assert calls == ["pinyin", "words", "stack", "ass", "align", "mux"]
    assert srt_tool.read_srt(Path("zh.pinyin.srt"))[0][2] == "jīntiān tiānqì."
    calls.clear()
    study.main()
    assert calls == ["stack", "ass", "mux"]                     # no repeated segmentation or model work
    fresh(pipeline / "align_srt.py")
    calls.clear()
    study.main()
    assert calls == ["stack", "ass", "align", "mux"]             # an aligner upgrade only refreshes links
    assert {name: (Path(name).read_bytes(), Path(name).stat().st_mtime_ns) for name in preserved} == preserved
