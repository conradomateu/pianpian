# /// script
# requires-python = ">=3.10"
# dependencies = ["mlx-lm>=0.28", "jieba>=0.42"]
# ///
"""Link each English word to the Chinese word it translates, using the translation model itself.

    uv run align_srt.py zh.srt zh.en.srt            # -> zh.align.json

How: the model reads the Chinese line and its English (any English, also hand-made) in one pass,
and in its middle layers a word and its translation end up with similar vectors. Each English word
is linked to the Chinese word it is most similar to, when that is mutual (SimAlign's "inter" rule).
Layer 10 of Hy-MT2-1.8B was chosen on your vlog: it agreed with the CC-CEDICT dictionary on 72% of
the words both could link, and together with the dictionary 86% of English words get a link.
Links to grammar words (的, 了…) are dropped: there the vectors are not reliable.
The player uses these links only where the dictionary found none. About 3 s for 120 lines.
"""
import json
import re
import sys
from pathlib import Path

import jieba
import mlx.core as mx
from mlx_lm import load
from mlx_lm.models.base import create_attention_mask

sys.path.insert(0, str(Path(__file__).resolve().parent))
from translate_srt import MODEL, ensure_model, read_lines   # same model, same download

jieba.setLogLevel(60)
LAYER = 10
HAN = re.compile(r"[一-鿿]")
GRAMMAR_ZH = set("的了着过呢吗吧啊呀啦嘛哦咯里有是在就都也")      # unreliable targets for vector links
GRAMMAR_EN = set("a an the to of be is are am was were been do does did have has had it its this that these those "
                 "in on at for with by from as or and but not no so very one where when what which who how s m re ll ve d t".split())


def char_ends(tok, ids):
    """Character offset where each token ends, by decoding growing prefixes."""
    return [len(tok.decode(ids[: i + 1])) for i in range(len(ids))]


def main() -> None:
    zh_path, en_path = Path(sys.argv[1]), Path(sys.argv[2])
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else zh_path.with_name("zh.align.json")
    zh_lines = [t.replace(" / ", "") for _, t in read_lines(zh_path)]
    en_lines = [t.replace(" / ", " ") for _, t in read_lines(en_path)]
    if len(zh_lines) != len(en_lines):
        sys.exit("zh and en tracks have different line counts")
    model, tok = load(ensure_model(MODEL))
    marker = "§§§"
    tmpl = tok.apply_chat_template([{"role": "user", "content": f"将以下文本翻译为英语，注意只需要输出翻译后的结果，不要额外解释：\n\n{marker}"}],
                                   add_generation_prompt=True, tokenize=False)
    pre_ids, post_ids = (tok.encode(x, add_special_tokens=False) for x in tmpl.split(marker))

    cues = []
    for zh, en in zip(zh_lines, en_lines):
        links = []
        z_ids, e_ids = tok.encode(zh, add_special_tokens=False), tok.encode(en, add_special_tokens=False)
        if z_ids and e_ids:
            ids = pre_ids + z_ids + post_ids + e_ids
            h = model.model.embed_tokens(mx.array([ids]))
            mask = create_attention_mask(h, None)
            for layer in model.model.layers[: LAYER + 1]:   # only the layers we need
                h = layer(h, mask, None)
            H = h[0]
            z0, e0 = len(pre_ids), len(ids) - len(e_ids)
            # Chinese words (jieba) and English words, each as the tokens it covers
            zc, ec = char_ends(tok, z_ids), char_ends(tok, e_ids)
            def tokens(ends, a, b):
                starts = [0] + ends[:-1]
                return [k for k, (x, y) in enumerate(zip(starts, ends)) if x < b and y > a]
            zw, pos = [], 0
            for w in jieba.cut(zh):
                if HAN.search(w) and w not in GRAMMAR_ZH and (t := tokens(zc, pos, pos + len(w))):
                    zw.append((pos, pos + len(w), t))
                pos += len(w)
            ew = [(m.start(), m.end(), t) for m in re.finditer(r"[A-Za-z]+", en)
                  if m.group().lower() not in GRAMMAR_EN and (t := tokens(ec, m.start(), m.end()))]
            if zw and ew:
                Z = mx.stack([H[[z0 + t for t in toks]].mean(0) for _, _, toks in zw])
                E = mx.stack([H[[e0 + t for t in toks]].mean(0) for _, _, toks in ew])
                Z = Z / mx.linalg.norm(Z, axis=1, keepdims=True)
                E = E / mx.linalg.norm(E, axis=1, keepdims=True)
                S = (E @ Z.T).tolist()
                best_z = [max(range(len(zw)), key=row.__getitem__) for row in S]
                best_e = [max(range(len(ew)), key=lambda j: S[j][k]) for k in range(len(zw))]
                for j, k in enumerate(best_z):
                    if best_e[k] == j:                       # mutual best match
                        links.append([ew[j][0], ew[j][1], zw[k][0], zw[k][1], round(S[j][k], 3)])
        cues.append(links)
    out_path.write_text(json.dumps({"version": 1, "layer": LAYER, "model": MODEL, "cues": cues}, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out_path} ({sum(map(len, cues))} links over {len(cues)} lines)")


if __name__ == "__main__":
    main()
