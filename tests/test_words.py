"""Helpers behind zh.words.json: measure words, numbered pinyin, the video's HSK level."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import srt_tool as t  # noqa: E402


def test_numbered_to_marks():
    assert [t.numbered_to_marks(s) for s in ("ge4", "ben3", "lu:4", "zuo4", "ma5", "liu2")] == ["gè", "běn", "lǜ", "zuò", "ma", "liú"]


def test_measure_words():
    assert t.measure_words("CL:個|个[ge4],本[ben3]") == "个 gè, 本 běn"
    assert t.measure_words("CL:座[zuo4]") == "座 zuò"


def test_hsk_level_by_parts():
    assert t.hsk_level("爸爸") == 1                    # listed
    assert t.hsk_level("爸爸妈妈") == 1                # not listed: its hardest part


def test_video_level_ignores_unlisted_words():
    assert t.video_level([1] * 9 + [3] + [0] * 50)["level"] == 1
    assert t.video_level([1] * 8 + [4] * 2)["level"] == 4
