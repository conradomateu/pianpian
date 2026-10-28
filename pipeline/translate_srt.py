# /// script
# requires-python = ">=3.10"
# dependencies = ["mlx-lm>=0.28; sys_platform == 'darwin'"]
# ///
"""Translate zh.srt into English line by line with a small local translation model (on a Mac: MLX).

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
The model itself runs in the platform's backend (backend.py); this file keeps the prompt and the loop.
Nothing leaves the Mac.
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend  # noqa: E402
import models  # noqa: E402
from models import ensure as ensure_model  # noqa: E402  (shared with Whisper, align_srt.py and the installer)

MODEL = os.environ.get("MT_MODEL") or models.default("translate")
TIME = re.compile(r"\d{2}:\d{2}:\d{2}[,.]\d{3} --> ")
CONTEXT_LINES = 3
HAN = re.compile(r"[\u4e00-\u9fff]")


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


def translate(lines: list[tuple[str, str]], title: str, generate) -> list[str]:
    """["id<TAB>English"] for each line. generate(prompt, temperature, max_tokens) is the backend's model."""
    out = []
    for n, (cid, text) in enumerate(lines):
        before = [t for _, t in lines[max(0, n - CONTEXT_LINES):n]]
        background = "\n".join(([f"视频标题：{title}"] if title else []) + ([f"前文：{' '.join(before)}"] if before else []))
        prompt = prompt_for(text, background)
        # a lower temperature than the model card's, so names stay the same from line to line;
        # a reply that still has Chinese in it gets one greedy retry
        for temperature in (0.3, 0.0):
            reply = generate(prompt, temperature, 40 + 6 * len(text))
            english = " ".join(re.sub(r"<think>.*?</think>", "", reply, flags=re.S).split()).strip().strip('"“”')
            if not HAN.search(english):
                break
        out.append(f"{cid}\t{english}")
        if (n + 1) % 10 == 0 or n + 1 == len(lines):
            print(f"translated {n + 1}/{len(lines)}", flush=True)
    return out


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
    with backend.impl().translator(path) as generate:
        print(f"translating {len(lines)} lines…", flush=True)
        out_lines = translate(lines, title, generate)

    out = Path(a.out) if a.out else src.with_name("en.lines.txt")
    out.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(lines)} lines, {time.time() - t0:.0f} s, {a.model})")


if __name__ == "__main__":
    main()
