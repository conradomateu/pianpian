"""Original timing fixtures: punctuation must not shorten the audio of spoken words."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import srt_tool  # noqa: E402


def whisper_file(tmp_path, words):
    path = tmp_path / "zh.whisper.json"
    path.write_text(json.dumps({"segments": [{"words": words}]}), encoding="utf-8")
    return path


@pytest.mark.parametrize("text,expected", [
    ("你好。", [("你", 1, 2), ("好", 2, 3), ("。", 3, 3)]),
    (" ‘你，好！’ ", [("‘", 1, 1), ("你", 1, 2), ("，", 2, 2), ("好", 2, 3), ("！", 3, 3), ("’", 3, 3)]),
    ("？！", [("？", 1, 1), ("！", 1, 1)]),
    ("A2。", [("A", 1, 2), ("2", 2, 3), ("。", 3, 3)]),
])
def test_punctuation_has_no_share_of_speech(tmp_path, text, expected):
    path = whisper_file(tmp_path, [{"word": text, "start": 1, "end": 3}])
    assert srt_tool.char_times(path) == expected


def test_spoken_times_preserves_end_and_rejects_partial_word(tmp_path):
    path = whisper_file(tmp_path, [
        {"word": "你好。", "start": 1, "end": 3},
        {"word": "明。", "start": 4, "end": 5},
    ])
    cues = [{"s": 1, "e": 3, "w": [[["你好", "nǐhǎo"], ["。", "."]]]},
            {"s": 4, "e": 6, "w": [[["明天", "míngtiān"], ["。", "."]]]}]
    srt_tool.spoken_times(cues, path)
    assert cues[0]["k"] == [[[1, 3], 0]]
    assert cues[1]["k"] == [[0, 0]]


def test_split_still_matches_punctuation_and_uses_spoken_bounds(tmp_path):
    path = whisper_file(tmp_path, [
        {"word": "我们喝茶。", "start": 1, "end": 3},
        {"word": "我们回家。", "start": 4, "end": 6},
    ])
    src, out = tmp_path / "zh.long.srt", tmp_path / "zh.srt"
    src.write_text("1\n00:00:00,000 --> 00:00:08,000\n我们喝茶。我们回家。\n", encoding="utf-8")
    srt_tool.cmd_split(SimpleNamespace(srt=str(src), out=str(out), words=str(path), max=4))
    assert srt_tool.read_srt(out) == [
        ("1", "00:00:01,000 --> 00:00:03,000", "我们喝茶。"),
        ("2", "00:00:04,000 --> 00:00:06,000", "我们回家。"),
    ]


def test_retime_cli_repairs_old_cache_without_writing_inputs(tmp_path):
    raw = whisper_file(tmp_path, [{"word": "你好。", "start": 1, "end": 3}])
    words = tmp_path / "zh.words.json"
    original = {"version": 2, "source": "zh.srt", "hsk": 1, "extra": "preserved",
                "cues": [{"s": 1, "e": 3, "w": [[["你好", "nǐhǎo", "hello", 1, ""], ["。", "."]]],
                          "g": [[]], "k": [[[1, 2.33], 0]]}]}
    words.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    before = [p.read_bytes() for p in (raw, words)]
    result = subprocess.run([sys.executable, str(ROOT / "pipeline" / "srt_tool.py"), "retime", str(words),
                             "--whisper", str(raw)], capture_output=True, text=True, check=True)
    expected = json.loads(json.dumps(original))
    expected["cues"][0]["k"] = [[[1, 3], 0]]
    assert json.loads(result.stdout) == expected
    assert [p.read_bytes() for p in (raw, words)] == before
