#!/usr/bin/env python3
"""Turn subtitles that are burned into a video's picture into a real zh.srt.

    python3 hardsubs_to_srt.py video.mp4 [zh.srt] [--crop 0.28] [--fps 2]

When the Chinese text is part of the image, Whisper has nothing to gain from the sound (and fails
on songs and memes). This reads the text off the picture instead: ffmpeg cuts the bottom strip of
the video into frames, the platform's OCR reads them (backend.py; on a Mac, ocr_frames.swift with
macOS's built-in OCR), and consecutive frames with the same text become one cue. Timing is the frame
time, so it is accurate to 1/fps s.

Check the result by eye: OCR confuses similar characters (自/白, 窝/我). Fix zh.srt before the pinyin
and translation steps. Standard library only; needs ffmpeg and, on a Mac, the Xcode command line tools.
"""
import argparse
import difflib
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import backend

HAN = re.compile(r"[一-鿿]")


def stamp(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def ffmpeg() -> str:
    """Homebrew's ffmpeg if there is one, else the engine's (imageio-ffmpeg)."""
    if exe := shutil.which("ffmpeg"):
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("out", nargs="?", default="zh.srt")
    ap.add_argument("--crop", type=float, default=0.28, help="bottom fraction of the picture that holds the subtitles")
    ap.add_argument("--fps", type=float, default=2.0)
    a = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-i", a.video, "-vf",
                        f"fps={a.fps},crop=iw:ih*{a.crop}:0:ih*{1 - a.crop},scale=1280:-1", f"{tmp}/%05d.png"], check=True)
        ocr = backend.impl().ocr(tmp)

    frames = []  # (time, text)
    for line in ocr.splitlines():
        name, _, text = line.partition("\t")
        text = text.strip()
        frames.append(((int(name.split(".")[0]) - 1) / a.fps, text if len(HAN.findall(text)) >= 2 else ""))

    groups, cur = [], None  # each group: [start, end, [texts]]
    for t, text in frames:
        if not text:
            cur = None
            continue
        if cur and difflib.SequenceMatcher(None, cur[2][-1], text).ratio() >= 0.7:
            cur[1] = t + 1 / a.fps
            cur[2].append(text)
        else:
            cur = [t, t + 1 / a.fps, [text]]
            groups.append(cur)

    cues = [(s, e, Counter(texts).most_common(1)[0][0]) for s, e, texts in groups if len(texts) >= 2]
    if not cues:
        sys.exit("no burned-in Chinese text found; try a different --crop")
    Path(a.out).write_text("\n\n".join(f"{i}\n{stamp(s)} --> {stamp(e)}\n{txt}" for i, (s, e, txt) in enumerate(cues, 1)) + "\n",
                           encoding="utf-8")
    print(f"wrote {a.out}: {len(cues)} cues from {len(frames)} frames")


if __name__ == "__main__":
    main()
