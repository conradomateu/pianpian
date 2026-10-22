"""Tense markers in one line of Chinese, character by character, for the player's colours.

Chinese verbs don't change for tense: time shows through a few particles and time words.

    past      verb + 了 (done) · verb + 过 (have done before) · 没/没有 + verb (didn't)
    present   在/正在 + verb (in progress) · verb + 着 (ongoing state)
    future    将 + verb · 快要/就要 … 了 (about to)
    maybe     会/要 + verb: future, but 会 is also "can" and 要 "want to": never shown as sure
    change    了 after something that is not a verb: a new situation (好了, 下雨了)
    time-*    time words: 昨天 (past) · 现在 (present) · 明天 (future)

jieba's part-of-speech tags decide what is a verb. The checks run per character because jieba
glues markers into words (吃了饭, 去过, 我会). It is a heuristic: tests/test_grammar.py holds
the sentences it must get right, and the player says "maybe" where the rule can't tell.

    tags("我们昨天去了公园") -> [[2, "time-past"], [3, "time-past"], [5, "past:le"]]
"""
import re

import jieba
import jieba.posseg as pseg

jieba.setLogLevel(60)

TIME = {
    "time-past": {"昨天", "前天", "去年", "前年", "以前", "刚才", "刚刚", "那时", "那时候", "当时", "上次", "上周", "上个月", "上星期", "之前", "从前", "过去"},
    "time-present": {"现在", "今天", "目前", "如今", "这会儿", "此刻", "今年", "这周", "这个月"},
    "time-future": {"明天", "后天", "明年", "以后", "将来", "下次", "下周", "下个月", "下星期", "待会儿", "等会儿", "一会儿", "之后", "未来"},
}
# words that contain a marker character without being the marker
NOT_LE = {"了解", "为了", "除了", "了不起", "不得了", "受不了", "了不得", "罢了", "得了", "算了"}
NOT_GUO = {"不过", "经过", "难过", "过去", "过来", "超过", "通过", "过年", "过程", "过于", "过分", "错过", "度过", "路过", "过生日"}
NOT_ZHE = {"着急", "睡着", "着火", "着凉", "着想", "接着", "随着", "跟着", "沿着", "朝着", "向着", "看着办", "找着"}
NOT_HUI = {"机会", "社会", "会议", "开会", "学会", "约会", "聚会", "一会", "一会儿", "大会", "晚会", "舞会", "协会", "体会", "误会", "会员", "宴会"}
NOT_YAO = {"不要", "需要", "重要", "主要", "只要", "要是", "要求", "想要", "要么", "摘要", "必要", "要素"}
CLAUSE_END = set("。！？!?，,；;…、")


def tags(text: str) -> list[list]:
    """[[character index, tag], …] for one line (indices count every character of `text`)."""
    toks = [(w, f) for w, f in pseg.cut(text)]
    spans, pos = [], 0
    for w, f in toks:
        spans.append((pos, pos + len(w), w, f))
        pos += len(w)
    at = [0] * len(text)
    for k, (a, b, _, _) in enumerate(spans):
        for c in range(a, b):
            at[c] = k

    def verbish(f: str) -> bool:
        return f.startswith("v") or f in ("l", "i")      # verbs, plus idioms jieba glues (吃了饭 is "l")

    def next_verb(c: int) -> bool:
        a, b, w, f = spans[at[c]]
        if c + 1 < b:                                    # glued: 会说 / 要去 inside one token
            return verbish(f)
        nxt = at[c] + 1
        return nxt < len(spans) and verbish(spans[nxt][3])

    def prev_verb(c: int) -> bool:
        a, b, w, f = spans[at[c]]
        if c > a:                                        # glued: 吃了饭 / 去过
            return verbish(f)
        return at[c] > 0 and verbish(spans[at[c] - 1][3])

    out: dict[int, str] = {}

    def mark(a: int, b: int, tag: str):
        for c in range(a, b):
            out.setdefault(c, tag)

    for a, b, w, f in spans:                             # whole words first: time words, 正在, 没有, 快要
        for tag, words in TIME.items():
            if w in words:
                mark(a, b, tag)
        if w == "正在":
            mark(a, b, "present:zai")
        if w in ("没", "没有") and next_verb(b - 1):
            mark(a, b, "past:mei")
        if w in ("快要", "就要"):
            mark(a, b, "future:kuaiyao")

    for c, ch in enumerate(text):
        a, b, w, f = spans[at[c]]
        if ch == "了" and w not in NOT_LE:
            if re.search(r"(快要|就要|快)[^。！？!?，,；;]{0,8}了$", text[: c + 1]):
                out.setdefault(c, "future:kuaiyao")
            else:
                out.setdefault(c, "past:le" if prev_verb(c) else "change:le")
        elif ch == "过" and w not in NOT_GUO and not w.startswith("过") and prev_verb(c):
            out.setdefault(c, "past:guo")
        elif ch == "着" and w not in NOT_ZHE and prev_verb(c):
            out.setdefault(c, "present:zhe")
        elif ch == "在" and w in ("在", "正在") and next_verb(c):
            out.setdefault(c, "present:zai")
        elif ch == "会" and w not in NOT_HUI and w.endswith("会") and next_verb(c):
            out.setdefault(c, "maybe:hui")
        elif ch == "要" and w not in NOT_YAO and w.endswith("要") and w not in ("快要", "就要") and next_verb(c):
            out.setdefault(c, "maybe:yao")
        elif ch == "将" and w == "将" and next_verb(c):
            out.setdefault(c, "future:jiang")
    return [[c, t] for c, t in sorted(out.items())]
