"""Sentences the tense colours must get right.  uv run --with jieba --with pytest pytest tests/"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from grammar import tags  # noqa: E402


def marked(text):
    return {text[c]: t for c, t in tags(text)}


CASES = [
    ("我吃了饭", {"了": "past:le"}),
    ("我们昨天去了公园", {"昨": "time-past", "天": "time-past", "了": "past:le"}),
    ("我去过北京", {"过": "past:guo"}),
    ("我没吃", {"没": "past:mei"}),
    ("我在吃饭", {"在": "present:zai"}),
    ("我在家", {}),                                   # 在 + a place is not "in progress"
    ("我正在看书呢", {"正": "present:zai", "在": "present:zai"}),
    ("门开着", {"着": "present:zhe"}),
    ("明天会下雨", {"明": "time-future", "天": "time-future", "会": "maybe:hui"}),
    ("我会说中文", {"会": "maybe:hui"}),               # ability or future: marked "maybe"
    ("我要去上海", {"要": "maybe:yao"}),
    ("我要咖啡", {}),                                 # 要 + a thing is "want"
    ("快要下雨了", {"快": "future:kuaiyao", "要": "future:kuaiyao", "了": "future:kuaiyao"}),
    ("我不了解他", {}),
    ("现在在看花", {"现": "time-present", "在": "present:zai"}),
    ("这是一个机会", {}),
]


def test_cases():
    bad = []
    for text, want in CASES:
        got = marked(text)
        if got != want:
            bad.append(f"{text}: want {want}, got {got}")
    assert not bad, "\n".join(bad)
