"""Study word boundaries, dictionary metadata and generated subtitle consistency."""
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import srt_tool as t  # noqa: E402


@pytest.fixture
def dictionary(monkeypatch):
    entries = {word: [["", meaning, ""]] for word, meaning in {
        "今天": "today; the present time", "天气": "weather", "天": "day", "气": "air",
        "朋友": "friend", "家": "home", "回家": "to return home", "回": "to return", "吧": "suggestion particle",
        "我": "I", "要": "to want", "你": "you", "好": "good", "你好": "hello", "了": "completed action",
        "画蛇添足": "to overdo it", "画蛇": "to draw a snake", "添足": "to add feet",
    }.items()}
    monkeypatch.setattr(t, "_DICT", entries)
    return entries


def test_dictionary_refines_unknown_compounds_but_keeps_known_words(dictionary):
    # These compounds really are single jieba tokens; the fallback must refine them.
    assert list(t.jieba.cut("今天天气")) == ["今天天气"]
    assert t.word_pairs("今天天气") == [["今天", "jīntiān"], ["天气", "tiānqì"]]
    for compound, parts in [("朋友家", ["朋友", "家"]), ("回家吧", ["回家", "吧"]), ("我要", ["我", "要"])]:
        assert [zh for zh, _ in t.word_pairs(compound)] == parts
    for word in ("你好", "回家", "画蛇添足"):
        assert [zh for zh, _ in t.word_pairs(word)] == [word]
    assert t.gloss("今天天气") == "今天: today · 天气: weather"
    assert t.dictionary_parts("龘靐今天天气龘") == ["龘靐", "今天", "天气", "龘"]


def test_segmentation_preserves_punctuation_whitespace_and_pinyin_overrides(dictionary):
    text = "今天天气，\n你好！  A2？"
    assert "".join(t.segment_words(text)) == text
    assert t.word_pairs(text) == [["今天", "jīntiān"], ["天气", "tiānqì"], ["，", ","],
                                  ["你好", "nǐhǎo"], ["！", "!"], ["A2", "A2"], ["？", "?"]]
    assert t.to_pinyin("今天天气， 你好！") == "jīntiān tiānqì, nǐhǎo!"
    assert t.word_pairs("朋友 逛一逛") == [["朋友", "péngyou"], ["逛一逛", "guàngyiguàng"]]
    assert t.word_pairs("一点儿") == [["一点儿", "yìdiǎnr"]]
    assert t.word_pairs("") == []


def test_missing_dictionary_keeps_jieba_words_and_loads_only_once(monkeypatch):
    calls = []
    monkeypatch.setattr(t, "_DICT", None)
    monkeypatch.setattr(t, "ensure_cedict", lambda: calls.append(True) or {})
    assert list(t.segment_words("今天天气，朋友家")) == list(t.jieba.cut("今天天气，朋友家"))
    assert calls == [True]


def test_generated_word_pinyin_timing_and_grammar_share_offsets(dictionary, tmp_path):
    src = tmp_path / "zh.srt"
    t.write_srt(src, [("1", "00:00:01,000 --> 00:00:08,000", "今天天气，\n我回家了。")])
    (tmp_path / "zh.whisper.json").write_text(json.dumps({"segments": [{"words": [
        {"word": "今天天气，", "start": 1, "end": 3},
        {"word": "我回家了。", "start": 4, "end": 8},
    ]}]}), encoding="utf-8")
    args = SimpleNamespace(srt=str(src), out=None)
    t.cmd_pinyin(args)
    t.cmd_words(args)
    data = json.loads(src.with_suffix(".words.json").read_text(encoding="utf-8"))
    cue = data["cues"][0]
    assert data["version"] == 2
    assert cue["k"] == [[[1, 2], [2, 3], 0], [[4, 5], [5, 7], [7, 8], 0]]
    assert [[w[0] for w in row] for row in cue["w"]] == [["今天", "天气", "，"], ["我", "回家", "了", "。"]]
    assert cue["g"] == [t.grammar.tags("今天天气，"), t.grammar.tags("我回家了。")]
    assert [3, "change:le"] in cue["g"][1]
    assert t.read_srt(src.with_suffix(".pinyin.srt")) == [
        ("1", "00:00:01,000 --> 00:00:08,000", "jīntiān tiānqì,\nwǒ huíjiā le.")]


def test_import_error_has_path_and_line_but_no_translation(tmp_path, capsys):
    src, lines, out = (tmp_path / name for name in ("zh.srt", "en.lines.txt", "zh.en.srt"))
    t.write_srt(src, [("1", "00:00:01,000 --> 00:00:02,000", "你好")])
    lines.write_text("\n1 secret translation without a tab\n", encoding="utf-8")
    out.write_text("keep the previous translation", encoding="utf-8")
    with pytest.raises(SystemExit) as err:
        t.cmd_import(SimpleNamespace(srt=str(src), lines=str(lines), out=str(out)))
    assert str(err.value) == f"{lines}:2: no TAB between id and text"
    assert "secret translation" not in capsys.readouterr().out
    assert out.read_text(encoding="utf-8") == "keep the previous translation"


def test_demo_artifacts_share_words_timings_and_character_spans():
    library = Path(__file__).resolve().parents[1] / "demo" / "library"
    for src in library.glob("*/zh.srt"):
        chinese = t.read_srt(src)
        pinyin = t.read_srt(src.with_suffix(".pinyin.srt"))
        english = t.read_srt(src.with_suffix(".en.srt"))
        data = json.loads(src.with_suffix(".words.json").read_text(encoding="utf-8"))
        links = json.loads(src.with_suffix(".align.json").read_text(encoding="utf-8"))["cues"]
        assert len(chinese) == len(pinyin) == len(english) == len(data["cues"]) == len(links)
        for (_, timing, zh), (_, pt, py), (_, et, en), cue, align in zip(chinese, pinyin, english, data["cues"], links):
            assert timing == pt == et
            assert [cue["s"], cue["e"]] == [t.secs(x) for x in timing.split(" --> ")]
            assert "\n".join("".join(w[0] for w in row) for row in cue["w"]) == zh
            assert "\n".join(re.sub(r'\s+([,.!?:;)\]»\"])', r'\1', " ".join(w[1] for w in row)) for row in cue["w"]) == py
            assert cue["g"] == [t.grammar.tags(line) for line in zh.split("\n")]
            spans, pos = [], 0
            for row, times in zip(cue["w"], cue["k"]):
                assert len(row) == len(times)
                for word, at in zip(row, times):
                    spans.append([pos, pos + len(word[0])])
                    pos += len(word[0])
                    assert at == 0 or cue["s"] <= at[0] <= at[1] <= cue["e"]
            for es, ee, zs, ze, _ in align:
                assert 0 <= es < ee <= len(en)
                assert [zs, ze] in spans
            if "今天天气" in zh:
                assert [w[0] for w in cue["w"][0]][:2] == ["今天", "天气"]
        retimed = json.loads(json.dumps(data["cues"]))
        t.spoken_times(retimed, src.with_name("zh.whisper.json"))
        assert [cue["k"] for cue in retimed] == [cue["k"] for cue in data["cues"]]


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
