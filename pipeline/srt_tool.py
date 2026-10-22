# /// script
# requires-python = ">=3.10"
# dependencies = ["pypinyin>=0.51", "jieba>=0.42", "zhconv>=1.4"]
# ///
"""Subtitle helper for study videos. Timestamps are never edited; only the text.

    uv run srt_tool.py pinyin  zh.srt                # -> zh.pinyin.srt + zh.zh-pinyin.srt
    uv run srt_tool.py export  zh.srt                # -> zh.lines.txt  (give this to an LLM)
    uv run srt_tool.py import  zh.srt en.lines.txt   # -> zh.en.srt     (checks every id came back)
    uv run srt_tool.py stack   zh.srt zh.pinyin.srt zh.en.srt -o zh.trilingual.srt
    uv run srt_tool.py ass     zh.pinyin.srt zh.en.srt -o out.ass --margin-v 190   # lifted clear of burned-in text
    uv run srt_tool.py words   zh.srt                # -> zh.words.json (each word with its pinyin, for the player)
    uv run srt_tool.py split   zh.long.srt --max 18 --words zh.whisper.json -o zh.srt   # short lines

Pinyin: pypinyin, corrected by pinyin_fixes.txt (edit it, then rebuild), which also holds the
neutral tones pypinyin misses (先生 xiānsheng). V一V (逛一逛) reads yi.

Translation never touches the .srt: `export` writes "id<TAB>text" lines, the
model translates those, `import` puts the text back under the original timings
and refuses to write if an id is missing, duplicated or invented.
"""
import argparse
import base64
import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path
from urllib.request import urlopen

import jieba
from pypinyin import Style, pinyin

jieba.setLogLevel(60)
HERE = Path(__file__).resolve().parent
FIXES = HERE / "pinyin_fixes.txt"
sys.path.insert(0, str(HERE))
import grammar  # noqa: E402  (pipeline/grammar.py: tense marks for the player)

TIME = re.compile(r"^\d{2}:\d{2}:\d{2}[,.]\d{3} --> \d{2}:\d{2}:\d{2}[,.]\d{3}")
HAN = re.compile(r"[一-鿿]")
PUNCT = str.maketrans({"，": ",", "。": ".", "！": "!", "？": "?", "：": ":", "；": ";",
                       "、": ",", "（": "(", "）": ")", "“": '"', "”": '"', "《": "«", "》": "»"})


def read_srt(path: Path) -> list[tuple[str, str, str]]:
    """-> [(index, timing, text)]; tolerant of BOM, CRLF and blank-line noise."""
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
    cues = []
    for block in re.split(r"\n\s*\n", raw):
        lines = block.strip().split("\n")
        if len(lines) >= 2 and TIME.match(lines[1]):
            cues.append((lines[0].strip(), lines[1].strip(), "\n".join(lines[2:]).strip()))
        elif len(lines) >= 1 and TIME.match(lines[0]):  # cue without a number
            cues.append((str(len(cues) + 1), lines[0].strip(), "\n".join(lines[1:]).strip()))
    if not cues:
        sys.exit(f"{path}: no subtitle cues found")
    return cues


def write_srt(path: Path, cues) -> None:
    body = "\n\n".join(f"{i}\n{t}\n{x}" for i, t, x in cues)
    path.write_text(body + "\n", encoding="utf-8")
    print(f"wrote {path} ({len(cues)} cues)")


def load_overrides() -> tuple[dict[str, str], dict[str, str]]:
    """(words, single characters) -> pinyin, from pinyin_fixes.txt."""
    words, chars = {}, {}
    if FIXES.exists():
        for line in FIXES.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            w, _, py = line.strip().partition("\t") if "\t" in line else line.strip().partition(" ")
            (chars if len(w) == 1 else words)[w] = "".join(py.split())
    return words, chars


OVER_WORDS, OVER_CHARS = load_overrides()
for _w in OVER_WORDS:
    jieba.add_word(_w)                                # so jieba keeps the corrected words whole


def word_pinyin(word: str) -> str:
    if word in OVER_WORDS:
        return OVER_WORDS[word]
    if m := re.fullmatch(r"(.)一\1", word):            # 逛一逛, 看一看: the 一 is light
        return word_pinyin(m[1]) + "yi" + word_pinyin(m[1])
    out, i, rest = "", 0, ""
    def flush(chunk):                                 # pypinyin reads an unknown chunk with phrase context
        return "".join(OVER_CHARS.get(c, s[0]) for c, s in zip(chunk, pinyin(chunk, style=Style.TONE))) if chunk else ""
    while i < len(word):                              # longest corrected word inside this one (早上 in 早上好)
        for n in range(min(4, len(word) - i), 1, -1):
            if word[i:i + n] in OVER_WORDS:
                out += flush(rest) + OVER_WORDS[word[i:i + n]]
                rest, i = "", i + n
                break
        else:
            rest += word[i]
            i += 1
    return out + flush(rest)


# ---------- meanings: CC-CEDICT (CC BY-SA 4.0), fetched once from the npm package cedict-json ----------
CACHE = Path.home() / ".cache" / "mandarin-kit"
CEDICT = CACHE / "cedict.v3.json"                    # { simplified: [[tones, "gloss; gloss", "个 gè"], …] }, one per reading
SKIP_GLOSS = re.compile(r"^(CL:|variant of|old variant|see |also pr|Taiwan pr|surname|\(phonetic\)|used in|abbr\. for|\(old\))", re.I)


def ensure_cedict() -> dict[str, str]:
    if CEDICT.exists():
        return json.loads(CEDICT.read_text(encoding="utf-8"))
    for registry in ("https://registry.npmmirror.com", "https://registry.npmjs.org"):   # the first is fast from China
        try:
            meta = json.load(urlopen(f"{registry}/cedict-json/latest", timeout=30))
            blob = urlopen(meta["dist"]["tarball"], timeout=120).read()
            algo, _, want = meta["dist"]["integrity"].partition("-")
            if base64.b64encode(hashlib.new(algo, blob).digest()).decode() != want:
                raise OSError("checksum mismatch")
            break
        except OSError as e:
            print(f"cedict from {registry} failed ({e})", file=sys.stderr)
    else:
        print("no dictionary: words get no meanings", file=sys.stderr)
        return {}
    rows = json.load(tarfile.open(fileobj=io.BytesIO(blob)).extractfile("package/cedict.json"))
    rows.sort(key=lambda r: r["pinyin"][:1].isupper())                  # common words before names
    small: dict[str, list] = {}
    for r in rows:
        keep = [g for g in r["english"] if not SKIP_GLOSS.match(g)]
        gl = [g for g in keep if len(g) <= 48][:3] or [g[:60].rstrip() + "…" for g in keep[:1]]   # a long gloss only if it is all there is
        cl = ", ".join(measure_words(g) for g in r["english"] if g.startswith("CL:"))
        if gl:                                       # tones of the reading, neutral left out: "di4 fang5" -> "4"
            small.setdefault(r["simplified"], []).append(["".join(re.findall(r"[1-4]", r["pinyin"])), "; ".join(gl), cl])
    CACHE.mkdir(parents=True, exist_ok=True)
    CEDICT.write_text(json.dumps(small, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"dictionary ready: {len(small)} entries ({CEDICT})", file=sys.stderr)
    return small


def numbered_to_marks(syl: str) -> str:
    """ge4 -> gè, lu:4 -> lǜ, ma5 -> ma: CC-CEDICT's numbered pinyin, as the player shows it."""
    m = re.fullmatch(r"([a-zA-Z:]+?)([1-5])", syl)
    if not m:
        return syl
    base, tone = m[1].replace("u:", "ü").replace("v", "ü"), int(m[2])
    if tone == 5:
        return base
    low = base.lower()
    i = low.find("a") if "a" in low else low.find("e") if "e" in low else low.find("o") if "ou" in low else \
        max(low.rfind(v) for v in "iouü")
    if i < 0:
        return base
    import unicodedata
    return unicodedata.normalize("NFC", base[:i + 1] + "\u0304\u0301\u030c\u0300"[tone - 1] + base[i + 1:])


def measure_words(cl: str) -> str:
    """"CL:個|个[ge4],本[ben3]" -> "个 gè, 本 běn" (simplified form, tone marks)."""
    out = []
    for m in re.finditer(r"(?:[^|,\[]+\|)?([^|,\[]+)\[([^\]]+)\]", cl[3:]):
        out.append(f"{m[1].strip()} {''.join(numbered_to_marks(x) for x in m[2].split())}")
    import unicodedata
    return unicodedata.normalize("NFC", ", ".join(out))


_DICT: dict[str, list] | None = None
MARKS = {"\u0304": "1", "\u0301": "2", "\u030c": "3", "\u0300": "4"}


def gloss(word: str, py: str = "") -> str:
    """Meaning of a word, for the reading our pinyin uses (地方 dìfang = place, not dìfāng = local);
    for a jieba compound the dictionary lacks, the meanings of its parts."""
    global _DICT
    if _DICT is None:
        _DICT = ensure_cedict()
    import unicodedata
    tones = "".join(MARKS.get(c, "") for c in unicodedata.normalize("NFD", py))
    if m := re.fullmatch(r"(.)一\1", word):            # 逛一逛: "do it a little"
        return gloss(m[1]).split("; ")[0] + " (a little)"
    if word in _DICT:
        readings = _DICT[word]
        return next((r[1] for r in readings if r[0] == tones), readings[0][1])
    parts, i = [], 0
    while i < len(word):                             # longest dictionary words inside it
        for n in range(min(4, len(word) - i), 0, -1):
            if word[i:i + n] in _DICT:
                parts.append(f"{word[i:i + n]}: {_DICT[word[i:i + n]][0][1].split('; ')[0]}"); i += n
                break
        else:
            i += 1
    return " · ".join(parts)


def measure(word: str, py: str = "") -> str:
    """Measure words for this reading, from CC-CEDICT's CL: lines ("" when there are none)."""
    if _DICT is None:
        gloss(word, py)
    import unicodedata
    tones = "".join(MARKS.get(c, "") for c in unicodedata.normalize("NFD", py))
    readings = (_DICT or {}).get(word) or []
    hit = next((r for r in readings if r[0] == tones and len(r) > 2 and r[2]), None) or \
        next((r for r in readings if len(r) > 2 and r[2]), None)
    return hit[2] if hit else ""


# ---------- HSK 3.0 levels (pipeline/data/hsk3.json, from complete-hsk-vocabulary, MIT) ----------
HSK = json.loads((HERE / "data" / "hsk3.json").read_text(encoding="utf-8"))["levels"]   # word -> 1…7 (7 = band 7-9)


def hsk_level(word: str) -> int:
    """A word's HSK level; a jieba compound not in the lists (这个, 往左走) takes its hardest part's
    level (longest listed parts first); 0 when even its parts aren't listed (names, rare words)."""
    if word in HSK:
        return HSK[word]
    parts, i = [], 0
    while i < len(word):
        for n in range(min(4, len(word) - i), 0, -1):
            if word[i:i + n] in HSK:
                parts.append(HSK[word[i:i + n]]); i += n
                break
        else:
            return 0
    return max(parts) if parts else 0


def video_level(levels: list[int]) -> dict:
    """The lowest HSK level whose words cover 90% of the video's words; words in no list (names, rare
    words) are left out of the count. 8 = beyond band 7-9."""
    dist = [levels.count(n) for n in range(8)]        # index 0: not in any HSK list, even by parts
    known = sum(dist[1:]) or 1
    level = next((n for n in range(1, 8) if sum(dist[1:n + 1]) / known >= 0.9), 8)
    return {"level": level, "dist": dist}


def word_pairs(text: str) -> list[list[str]]:
    """[[word, pinyin], …] in jieba's segmentation; punctuation pairs with its ASCII form."""
    pairs = []
    for word in jieba.cut(text):
        if not word.strip():
            continue
        pairs.append([word, word_pinyin(word) if HAN.search(word) else word.translate(PUNCT)])
    return pairs


def to_pinyin(text: str) -> str:
    """Word-grouped pinyin with tone marks: 我今天很忙。 -> wǒ jīntiān hěn máng."""
    out = " ".join(py for _, py in word_pairs(text))
    out = re.sub(r"\s+([,.!?:;)\]»\"])", r"\1", out)  # no space before punctuation
    return re.sub(r"\s+", " ", out).strip()


def cmd_pinyin(a):
    src = Path(a.srt)
    cues = read_srt(src)
    py = [(i, t, "\n".join(to_pinyin(l) for l in x.split("\n"))) for i, t, x in cues]
    write_srt(src.with_suffix(".pinyin.srt"), py)
    write_srt(src.with_suffix(".zh-pinyin.srt"), [(i, t, f"{x}\n{p}") for (i, t, x), (_, _, p) in zip(cues, py)])


def cmd_export(a):
    src = Path(a.srt)
    cues = read_srt(src)
    out = src.with_suffix(".lines.txt")
    out.write_text("".join(f"{i}\t{x.replace(chr(10), ' / ')}\n" for i, _, x in cues), encoding="utf-8")
    print(f"wrote {out} ({len(cues)} lines) — translate the text after each TAB, keep the ids")


def cmd_import(a):
    src = Path(a.srt)
    cues = read_srt(src)
    got = {}
    for n, line in enumerate(Path(a.lines).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        if "\t" not in line:
            sys.exit(f"{a.lines}:{n}: no TAB between id and text: {line[:60]!r}")
        k, v = line.split("\t", 1)
        if k.strip() in got:
            sys.exit(f"{a.lines}:{n}: id {k} appears twice")
        got[k.strip()] = v.strip().replace(" / ", "\n")
    ids = [i for i, _, _ in cues]
    missing, extra = [i for i in ids if i not in got], [k for k in got if k not in set(ids)]
    if missing or extra:
        sys.exit(f"refusing to write: missing ids {missing[:10]} · unknown ids {extra[:10]}")
    write_srt(Path(a.out) if a.out else src.with_suffix(".en.srt"), [(i, t, got[i]) for i, t, _ in cues])


def cmd_stack(a):
    tracks = [read_srt(Path(p)) for p in a.srts]
    base = tracks[0]
    for p, tr in zip(a.srts[1:], tracks[1:]):
        if [t for _, t, _ in tr] != [t for _, t, _ in base]:
            sys.exit(f"{p}: timings differ from {a.srts[0]} — stack only tracks made from the same .srt")
    write_srt(Path(a.o), [(i, t, "\n".join(tr[n][2] for tr in tracks)) for n, (i, t, _) in enumerate(base)])


def secs(t: str) -> float:
    h, m, rest = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))


def cmd_words(a):
    """The same segmentation as the pinyin track, kept as pairs so the player can link
    each Chinese word to its pinyin (hover one, both light up; or pinyin above the word)."""
    src = Path(a.srt)
    cues, levels = [], []
    for _, t, x in read_srt(src):
        start, end = t.split(" --> ")
        lines, marks = [], []
        for line in x.split("\n"):
            pairs = word_pairs(line)
            # each Chinese word: [zh, pinyin, meaning, HSK level (0: not in the lists), measure words]
            lines.append([[zh, py, gloss(zh, py), HSK.get(zh, 0), measure(zh, py)] if HAN.search(zh) else [zh, py] for zh, py in pairs])
            marks.append(grammar.tags("".join(zh for zh, _ in pairs)))   # character index -> tense tag
        cues.append({"s": secs(start), "e": secs(end), "w": lines, "g": marks})
        levels += [hsk_level(w[0]) for line in lines for w in line if len(w) > 3]
    out = Path(a.out) if a.out else src.with_suffix(".words.json")
    out.write_text(json.dumps({"version": 2, "source": src.name, "hsk": video_level(levels), "cues": cues},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({len(cues)} cues)")


SENTENCE_END = set("。！？!?；;…")
SOFT_BREAK = set("，,、：:")


def han_len(t: str) -> int:
    return len(HAN.findall(t))


def split_text(text: str, limit: int) -> list[tuple[int, int]]:
    """[(start, end)] character ranges: one per sentence; a sentence longer than `limit` Chinese
    characters is cut after commas, then at word boundaries; tiny leftovers join a neighbour."""
    def cut(t, i, j, marks):                         # ranges ending just after a mark
        out, a = [], i
        for k in range(i, j):
            if t[k] in marks and k + 1 < j:
                while k + 1 < j and t[k + 1] in "”」』)）\"'":   # closing quotes stay with their sentence
                    k += 1
                out.append((a, k + 1)); a = k + 1
        return out + ([(a, j)] if a < j else [])

    def by_words(i, j):                              # last resort: even pieces, cut between jieba words
        n_parts = -(-han_len(text[i:j]) // limit)
        target = -(-han_len(text[i:j]) // n_parts)
        out, a, k, n = [], i, i, 0
        for w in jieba.cut(text[i:j]):
            if n and n + han_len(w) > target and len(out) < n_parts - 1:
                out.append((a, k)); a, n = k, 0
            k += len(w); n += han_len(w)
        return out + [(a, j)]

    pieces = []
    for a, b in cut(text, 0, len(text), SENTENCE_END):
        if han_len(text[a:b]) <= limit:
            pieces.append((a, b)); continue
        cur = None                                   # pack comma-separated clauses up to the limit
        for c, d in cut(text, a, b, SOFT_BREAK):
            if cur and han_len(text[cur[0]:d]) <= limit:
                cur = (cur[0], d)
            else:
                if cur: pieces.append(cur)
                cur = (c, d)
        pieces.append(cur)
    final = []
    for a, b in pieces:
        final.extend(by_words(a, b) if han_len(text[a:b]) > limit else [(a, b)])
    merged = []                                      # "走咯。" (2 characters) joins the previous line if it fits
    for a, b in final:
        if merged and han_len(text[a:b]) < 3 and han_len(text[merged[-1][0]:b]) <= limit:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return [(a, b) for a, b in merged if text[a:b].strip()]


def char_times(words_json: Path) -> list[tuple[str, float, float]]:
    """Whisper's word timestamps spread over each word's characters."""
    data = json.loads(words_json.read_text(encoding="utf-8"))
    out = []
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            chars = [c for c in w["word"] if not c.isspace()]
            step = (w["end"] - w["start"]) / max(len(chars), 1)
            out += [(c, w["start"] + k * step, w["start"] + (k + 1) * step) for k, c in enumerate(chars)]
    return out


def stamp(t: float) -> str:
    ms = round(max(t, 0) * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def cmd_split(a):
    """Shorter cues. With Whisper's word timestamps the cuts are timed to the word; without
    them, each piece gets a share of the cue's time in proportion to its length."""
    from zhconv import convert                       # Whisper sometimes drifts into Traditional characters
    cues = [(i, t, convert(x, "zh-cn")) for i, t, x in read_srt(Path(a.srt))]
    if a.max <= 0:                                   # "as transcribed"
        return write_srt(Path(a.out), [(str(n), t, x) for n, (_, t, x) in enumerate(cues, 1)])
    times = char_times(Path(a.words)) if a.words and Path(a.words).exists() else []
    ptr, out = 0, []
    for _, timing, text in cues:
        start, end = (secs(x) for x in timing.split(" --> "))
        text = text.replace("\n", "")
        at = []                                      # (start, end) of each character, when Whisper knows it
        for ch in text:
            hit = next((k for k in range(ptr, min(ptr + 4, len(times))) if times[k][0] == ch), None)
            if hit is None:
                at.append(None)
            else:
                at.append(times[hit][1:]); ptr = hit + 1
        timed = sum(x is not None for x in at) >= 0.8 * max(len(text), 1)
        for i, j in split_text(text, a.max):
            known = [x for x in at[i:j] if x] if timed else []
            if known:
                s0, e0 = known[0][0], known[-1][1]
            else:                                    # proportional share of the original cue
                total = max(len(text), 1)
                s0, e0 = start + (end - start) * i / total, start + (end - start) * j / total
            out.append([max(s0, start), min(max(e0, s0 + 0.5), end), text[i:j].strip()])
    for k in range(len(out) - 1):                    # no overlaps; close tiny gaps so lines don't flicker
        nxt = out[k + 1][0]
        if out[k][1] > nxt or nxt - out[k][1] < 0.3:
            out[k][1] = max(nxt, out[k][0] + 0.2)
    write_srt(Path(a.out), [(str(n), f"{stamp(s0)} --> {stamp(e0)}", t) for n, (s0, e0, t) in enumerate(out, 1)])


def ass_time(t: str) -> str:
    h, m, rest = t.split(":")
    sec, ms = re.split(r"[,.]", rest)
    return f"{int(h)}:{m}:{sec}.{int(ms) // 10:02d}"


def cmd_ass(a):
    """Stack SRT tracks into one ASS track, first line gold, second white, lifted by --margin-v pixels
    (of a 1080-pixel-high picture). For videos whose Chinese is burned in at the bottom."""
    tracks = [read_srt(Path(p)) for p in a.srts]
    base = tracks[0]
    for p, tr in zip(a.srts[1:], tracks[1:]):
        if [t for _, t, _ in tr] != [t for _, t, _ in base]:
            sys.exit(f"{p}: timings differ from {a.srts[0]}")
    colours = ["&H0000D7FF&", "&H00FFFFFF&"]
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 0\n\n[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
            "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Default,PingFang SC,46,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,{a.margin_v},1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    lines = []
    for n, (_, t, _) in enumerate(base):
        start, end = t.split(" --> ")
        text = "\\N".join("{\\c" + colours[k % 2] + "}" + tr[n][2].replace("{", "(").replace("}", ")").replace("\n", "\\N")
                         for k, tr in enumerate(tracks))
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}")
    Path(a.o).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {a.o} ({len(base)} cues)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(required=True)
    p = sub.add_parser("pinyin"); p.add_argument("srt"); p.set_defaults(f=cmd_pinyin)
    p = sub.add_parser("export"); p.add_argument("srt"); p.set_defaults(f=cmd_export)
    p = sub.add_parser("import"); p.add_argument("srt"); p.add_argument("lines"); p.add_argument("-o", dest="out"); p.set_defaults(f=cmd_import)
    p = sub.add_parser("stack"); p.add_argument("srts", nargs="+"); p.add_argument("-o", required=True); p.set_defaults(f=cmd_stack)
    p = sub.add_parser("split"); p.add_argument("srt"); p.add_argument("-o", dest="out", required=True)
    p.add_argument("--max", type=int, default=18, help="Chinese characters per line (0 = keep as is)"); p.add_argument("--words"); p.set_defaults(f=cmd_split)
    p = sub.add_parser("words"); p.add_argument("srt"); p.add_argument("-o", dest="out"); p.set_defaults(f=cmd_words)
    p = sub.add_parser("ass"); p.add_argument("srts", nargs="+"); p.add_argument("-o", required=True); p.add_argument("--margin-v", type=int, default=40); p.set_defaults(f=cmd_ass)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
