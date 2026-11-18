"""Bilingual word links from PLaMo Q3 middle-layer states, on Mac and Windows.

The bundled helper loads the same translation GGUF through the pinned llama.cpp runtime on CPU.
Mutual nearest word vectors supplement the dictionary links. These are heuristic associations,
not guaranteed translations: layer 7 was checked on a small self-authored development sample.
No MLX, Python ML library or second set of model weights is required.
"""
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import backend
import runtimes
from plamo import model_file
from srt_tool import segment_words
from translate_srt import MODEL, ensure_model, prompt_for, read_lines

LAYER = 7
HAN = re.compile(r"[一-鿿]")
GRAMMAR_ZH = set("的了着过呢吗吧啊呀啦嘛哦咯里有是在就都也")
GRAMMAR_EN = set("a an the to of be is are am was were been do does did have has had it its this that these those "
                 "in on at for with by from as or and but not no so very one where when what which who how s m re ll ve d t".split())


def alignment_prompt(zh: str, en: str) -> str:
    if "<|plamo:" in en:
        raise ValueError("English subtitle contains a reserved PLaMo delimiter")
    return "<|plamo:bos|>" + prompt_for(zh, "") + en


def word_links(zh: str, en: str, data: dict) -> list[list]:
    """Use byte offsets so split Unicode tokens still map to the original subtitle characters."""
    prompt = alignment_prompt(zh, en)
    if not isinstance(data, dict):
        raise ValueError("PLaMo alignment returned no object")
    tokens, vectors = data.get("tokens"), data.get("vectors")
    if not isinstance(tokens, list) or not isinstance(vectors, list) or not 0 < len(tokens) == len(vectors) <= 4096:
        raise ValueError("PLaMo alignment returned an invalid token/vector count")
    pieces = []
    for token in tokens:
        piece = token.get("piece") if isinstance(token, dict) else None
        if not isinstance(piece, list) or any(type(b) is not int or not 0 <= b <= 255 for b in piece):
            raise ValueError("PLaMo alignment returned invalid token bytes")
        pieces.append(bytes(piece))
    if b"".join(pieces) != prompt.encode("utf-8"):
        raise ValueError("PLaMo alignment tokens do not cover the exact subtitle prompt")
    width = len(vectors[0]) if isinstance(vectors[0], list) else 0
    if width != 1536 or any(not isinstance(v, list) or len(v) != width or
                           any(type(x) not in (int, float) or not math.isfinite(x) for x in v) for v in vectors):
        raise ValueError("PLaMo alignment returned invalid hidden states")
    spans, end = [], 0
    for piece in pieces:
        spans.append((end, end + len(piece)))
        end += len(piece)
    prefix = "<|plamo:bos|><|plamo:tag|>dataset<|plamo:msg|>translation<|plamo:tag|>input<|plamo:msg|>"
    z0, e0 = len(prefix.encode()), len(prompt.encode()) - len(en.encode())

    def embedding(text, begin, finish, offset):
        a, b = offset + len(text[:begin].encode()), offset + len(text[:finish].encode())
        selected = [vectors[i] for i, (left, right) in enumerate(spans) if left < b and right > a]
        if not selected:
            raise ValueError("PLaMo alignment omitted a subtitle word")
        mean = [sum(column) / len(selected) for column in zip(*selected)]
        norm = math.hypot(*mean)
        return [x / norm for x in mean] if norm else None

    zw, pos = [], 0
    for word in segment_words(zh):
        if HAN.search(word) and word not in GRAMMAR_ZH:
            vector = embedding(zh, pos, pos + len(word), z0)
            if vector:
                zw.append((pos, pos + len(word), vector))
        pos += len(word)
    ew = []
    for match in re.finditer(r"[A-Za-z]+", en):
        if match[0].lower() not in GRAMMAR_EN:
            vector = embedding(en, match.start(), match.end(), e0)
            if vector:
                ew.append((match.start(), match.end(), vector))
    if not zw or not ew:
        return []
    similarity = [[sum(a * b for a, b in zip(e[2], z[2])) for z in zw] for e in ew]
    best_z = [max(range(len(zw)), key=row.__getitem__) for row in similarity]
    best_e = [max(range(len(ew)), key=lambda j: similarity[j][k]) for k in range(len(zw))]
    return [[ew[j][0], ew[j][1], zw[k][0], zw[k][1], round(similarity[j][k], 3)]
            for j, k in enumerate(best_z) if best_e[k] == j]


def align(zh_path: Path, en_path: Path, out_path: Path) -> None:
    zh_lines = [t.replace(" / ", "") for _, t in read_lines(zh_path)]
    en_lines = [t.replace(" / ", " ") for _, t in read_lines(en_path)]
    if len(zh_lines) != len(en_lines):
        raise ValueError("Chinese and English tracks have different line counts")
    name = backend.native_binary("pianpian-align")
    helper = Path(__file__).parent / "bin" / name
    if not helper.is_file():
        raise RuntimeError("The bundled word-link helper is missing. Reinstall Pianpian; in a checkout run python dev.py native.")
    try:
        manifest = json.loads(helper.with_name("alignment-build-manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("The word-link helper manifest is missing or damaged. Reinstall Pianpian.") from error
    if not isinstance(manifest, dict) or manifest.get("llama_release") != runtimes.RELEASES["llama"]:
        raise RuntimeError("The word-link helper and translation runtime ABI differ. Reinstall Pianpian.")
    model = model_file(ensure_model(MODEL))
    runtime = Path(runtimes.ensure("llama", "cpu")).parent
    cues = []
    with tempfile.TemporaryDirectory(prefix="pianpian-align-") as folder:
        log_path = Path(folder) / "native.log"
        with log_path.open("w", encoding="utf-8") as log:
            with subprocess.Popen([str(helper), "--runtime", str(runtime), "--model", str(model), "--layer", str(LAYER)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                  text=True, encoding="utf-8", creationflags=runtimes.NO_WINDOW) as proc:
                try:
                    for zh, en in zip(zh_lines, en_lines):
                        if not zh.strip() or not en.strip():
                            cues.append([])
                            continue
                        proc.stdin.write(alignment_prompt(zh, en).encode().hex() + "\n")
                        proc.stdin.flush()
                        line = proc.stdout.readline()
                        if not line:
                            raise RuntimeError("PLaMo word-link helper stopped: " + log_path.read_text(encoding="utf-8")[-4000:])
                        cues.append(word_links(zh, en, json.loads(line)))
                    proc.stdin.close()
                    if proc.wait(timeout=30):
                        raise RuntimeError("PLaMo word-link helper failed: " + log_path.read_text(encoding="utf-8")[-4000:])
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
    # Complete and validate all cues before replacing existing links, including hand-edited libraries.
    temporary = out_path.with_name(out_path.name + ".part")
    temporary.write_text(json.dumps({"version": 1, "layer": LAYER, "model": MODEL, "cues": cues}, separators=(",", ":")), encoding="utf-8")
    temporary.replace(out_path)
    print(f"wrote {out_path} ({sum(map(len, cues))} links over {len(cues)} lines)")


def main() -> None:
    zh_path, en_path = Path(sys.argv[1]), Path(sys.argv[2])
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else zh_path.with_name("zh.align.json")
    align(zh_path, en_path, out_path)


if __name__ == "__main__":
    main()
