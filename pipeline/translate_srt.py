# /// script
# requires-python = ">=3.10"
# dependencies = ["mlx-lm>=0.28"]
# ///
"""Translate zh.srt into English line by line with a small local translation model (Apple Silicon, MLX).

    uv run translate_srt.py zh.srt                  # -> en.lines.txt next to it
    uv run translate_srt.py zh.srt -o out.txt

Writes the same "id<TAB>English" file as the manual ChatGPT/Claude step, so
`srt_tool.py import` checks it and the English keeps the Chinese timings.

Model: Tencent Hy-MT2-1.8B, 4-bit MLX build (1.02 GB, downloaded once into
~/.cache/mandarin-kit/models). From mainland China Hugging Face crawls (~40 KB/s
measured), so the files come from ModelScope's copy (~8 MB/s) and each one is
checked against the size and SHA-256 that Hugging Face publishes; Hugging Face
itself is the fallback. A translation-only model: on FLORES-200 Chinese↔X its
1.8B version scores XCOMET 84.3, above Microsoft Translator (83.0) and Doubao
(80.9), and 4-bit costs it about 1.3 points (Hy-MT2 report, arXiv 2605.22064).
Each line is translated with the video title and the previous lines as background,
using the model card's prompt and sampling settings. Set MT_MODEL to try another.
Nothing leaves the Mac.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from mlx_lm import generate, load
from mlx_lm.sample_utils import make_logits_processors, make_sampler

MODEL = os.environ.get("MT_MODEL", "mlx-community/Hy-MT2-1.8B-4bit")
TIME = re.compile(r"\d{2}:\d{2}:\d{2}[,.]\d{3} --> ")
CONTEXT_LINES = 3
CACHE = Path.home() / ".cache" / "mandarin-kit" / "models"
NEEDED = re.compile(r"\.(json|safetensors|jinja|model|tiktoken)$")       # weights, config, tokenizer; no images


def fetch(url: str, target: Path, size: int | None) -> None:
    part = target.with_name(target.name + ".part")
    with urlopen(url, timeout=60) as r, part.open("wb") as f:
        done, step = 0, max((size or 0) // 10, 1)
        while chunk := r.read(1 << 20):
            f.write(chunk)
            if size and size > 50_000_000 and (done + len(chunk)) // step > done // step:
                print(f"  {target.name}: {(done + len(chunk)) * 100 // size}%", flush=True)
            done += len(chunk)
    part.replace(target)


def ensure_model(repo: str) -> str:
    """A local folder with the model, downloaded once: ModelScope first, Hugging Face second."""
    if Path(repo).expanduser().is_dir():
        return str(Path(repo).expanduser())
    dest = CACHE / repo.replace("/", "__")
    if (dest / ".complete").exists():
        return str(dest)
    info = json.load(urlopen(f"https://huggingface.co/api/models/{repo}?blobs=true", timeout=60))   # small: file list + checksums
    files = [f for f in info["siblings"] if NEEDED.search(f["rfilename"]) and "/" not in f["rfilename"]]
    dest.mkdir(parents=True, exist_ok=True)
    print(f"downloading {repo} ({sum(f.get('size') or 0 for f in files) / 1e9:.2f} GB), once…", flush=True)
    for f in files:
        name, size, sha = f["rfilename"], f.get("size"), (f.get("lfs") or {}).get("sha256")
        target = dest / name
        for base in (f"https://www.modelscope.cn/models/{repo}/resolve/master/", f"https://huggingface.co/{repo}/resolve/main/"):
            if target.exists() and target.stat().st_size == size:
                break
            try:
                fetch(base + name, target, size)
            except OSError as e:
                print(f"  {name}: {base.split('/')[2]} failed ({e}), trying the next source", flush=True)
        if not target.exists() or target.stat().st_size != size:
            sys.exit(f"could not download {name}")
        if sha and hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            target.unlink()
            sys.exit(f"{name}: checksum does not match Hugging Face's; deleted it, run again")
    (dest / ".complete").touch()
    return str(dest)


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
