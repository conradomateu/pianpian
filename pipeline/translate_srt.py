"""Translate zh.srt to id<TAB>English using PLaMo 3 Translate 0.8B Q3_K_M.

The same pinned GGUF and native llama.cpp runtime run on Mac and Windows. PFML3 keeps source,
context and target language separate. Existing subtitle IDs and times remain unchanged.
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
from models import ensure as ensure_model  # noqa: E402  (shared with speech, alignment and setup)

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
    # Official PFML3 format; the runtime supplies BOS. Reserved delimiters cannot be source text.
    if "<|plamo:" in text or "<|plamo:" in background:
        raise ValueError("Subtitle or context contains a reserved PLaMo delimiter")
    return ("<|plamo:tag|>dataset<|plamo:msg|>translation"
            + (f"<|plamo:tag|>context<|plamo:msg|>{background}" if background else "")
            + f"<|plamo:tag|>input<|plamo:msg|>{text}"
            + "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>en<|plamo:msg|>")


def translate(lines: list[tuple[str, str]], title: str, generate) -> list[str]:
    """["id<TAB>English"] for each line. generate(prompt, temperature, max_tokens) is the backend's model."""
    out = []
    for n, (cid, text) in enumerate(lines):
        before = [t for _, t in lines[max(0, n - CONTEXT_LINES):n]]
        background = "\n".join(([f"视频标题：{title}"] if title else []) + ([f"前文：{' '.join(before)}"] if before else []))
        # The model card recommends greedy translation. Retry without surrounding context if needed.
        for context in dict.fromkeys((background, "")):
            reply = generate(prompt_for(text, context), 0.0, 40 + 6 * len(text))
            english = " ".join(reply.split()).strip().strip('"“”')
            if english and not HAN.search(english):
                break
        if not english or HAN.search(english):
            raise ValueError(f"PLaMo did not return an English translation for subtitle {cid}")
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
