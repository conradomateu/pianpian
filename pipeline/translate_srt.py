# /// script
# requires-python = ">=3.10"
# dependencies = ["mlx-lm>=0.28"]
# ///
"""Translate zh.srt into English line by line with a small local translation model (Apple Silicon, MLX).

    uv run translate_srt.py zh.srt                  # -> en.lines.txt next to it
    uv run translate_srt.py zh.srt -o out.txt

Writes the same "id<TAB>English" file as the manual ChatGPT/Claude step, so
`srt_tool.py import` checks it and the English keeps the Chinese timings.

Model: Tencent Hy-MT2-1.8B, 4-bit MLX build (1.02 GB, downloaded once by models.py: ModelScope's
copy first, which is fast from mainland China, checked against Hugging Face's SHA-256). A translation-only model: on FLORES-200 Chinese↔X its
1.8B version scores XCOMET 84.3, above Microsoft Translator (83.0) and Doubao
(80.9), and 4-bit costs it about 1.3 points (Hy-MT2 report, arXiv 2605.22064).
Each line is translated with the video title and the previous lines as background,
using the model card's prompt and sampling settings. Set MT_MODEL to try another.
Nothing leaves the Mac.
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

from mlx_lm import generate, load
from mlx_lm.sample_utils import make_logits_processors, make_sampler

MODEL = os.environ.get("MT_MODEL", "mlx-community/Hy-MT2-1.8B-4bit")
TIME = re.compile(r"\d{2}:\d{2}:\d{2}[,.]\d{3} --> ")
CONTEXT_LINES = 3
sys.path.insert(0, str(Path(__file__).resolve().parent))
from models import ensure as ensure_model  # noqa: E402  (shared with Whisper and the installer)


def read_lines(path: Path) -> list[tuple[str, str]]:
    """[(id, text)] from an .srt, joining multi-line cues with ' / ' like `srt_tool.py export`."""
    out = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()):
        lines = block.strip().split("\n")
        i = next((k for k, l in enumerate(lines) if TIME.match(l)), None)
        if i is None:
            continue
        cid = lines[i - 1].strip() if i > 0 else str(len(out) + 1)
        out.append((cid, " / ".join(l.strip() for l in lines[i + 1:] if l.strip())))
    return out


def prompt_for(text: str, background: str) -> str:
    # the model card's "background information" template, plus its "translation only" instruction
    if not background:
        return f"将以下文本翻译为英语，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
    return (f"【背景信息】\n{background}\n\n"
            f"请结合背景信息将以下文本翻译为英语，注意只需要输出翻译后的结果，不要额外解释，也不要翻译背景信息。\n"
            f"【待翻译文本】\n{text}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srt")
    ap.add_argument("-o", dest="out")
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()

    src = Path(a.srt)
    lines = read_lines(src)
    if not lines:
        sys.exit(f"{src}: no subtitle lines")
    title_file = src.parent / "title.txt"
    title = title_file.read_text(encoding="utf-8").strip() if title_file.exists() else ""

    t0 = time.time()
    path = ensure_model(a.model)
    print(f"loading {a.model}…", flush=True)
    model, tok = load(path)
    # the model card's top_p/top_k/penalty, with a lower temperature so names stay the same from line to line
    sampler = make_sampler(temp=0.3, top_p=0.6, top_k=20)
    greedy = make_sampler(temp=0.0)
    procs = make_logits_processors(repetition_penalty=1.05)
    print(f"translating {len(lines)} lines…", flush=True)

    out_lines = []
    for n, (cid, text) in enumerate(lines):
        before = [t for _, t in lines[max(0, n - CONTEXT_LINES):n]]
        background = "\n".join(([f"视频标题：{title}"] if title else []) + ([f"前文：{' '.join(before)}"] if before else []))
        msgs = [{"role": "user", "content": prompt_for(text, background)}]
        prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
        for smp in (sampler, greedy):                    # a reply that still has Chinese in it gets one greedy retry
            reply = generate(model, tok, prompt=prompt, max_tokens=40 + 6 * len(text), sampler=smp,
                             logits_processors=procs, verbose=False)
            english = " ".join(re.sub(r"<think>.*?</think>", "", reply, flags=re.S).split()).strip().strip('"“”')
            if not re.search(r"[\u4e00-\u9fff]", english):
                break
        out_lines.append(f"{cid}\t{english}")
        if (n + 1) % 10 == 0 or n + 1 == len(lines):
            print(f"translated {n + 1}/{len(lines)}", flush=True)

    out = Path(a.out) if a.out else src.with_name("en.lines.txt")
    out.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(lines)} lines, {time.time() - t0:.0f} s, {a.model})")


if __name__ == "__main__":
    main()
