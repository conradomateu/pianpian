"""Build the demo video and its study folder: demo/library/pianpian-day/.

    python3 tools/demo/make_demo.py --tts-python PATH --kokoro DIR

Everything in it is made here: the lines are script.txt, the music is music.py, the voice is Kokoro-82M (Apache-2.0,
voice zm_yunxia, a young boy) run through mlx-audio, and the pictures are scenes.py rendered by Chrome. Then
the app's own pipeline makes the subtitles, so the demo shows exactly what the app makes.

--tts-python is a Python with mlx-audio and misaki[zh] installed (kept out of the app's engine);
--kokoro is a local copy of mlx-community/Kokoro-82M-bf16. Needs ffmpeg and Chrome or Brave.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "demo" / "library" / "pianpian-day"
TITLE = "片片的一天 · A day with Pianpian"
# where the local model slips, the English is fixed by hand (as the app lets you), keyed by line id
EN_FIXES = {"1": "Hello, my name is Pianpian. I'm a slice of watermelon."}
LEAD, GAP, TAIL, FADE, FPS = 1.2, 0.9, 3.0, 0.5, 25     # the tail lets the music's last chord ring
MUSIC = 0.20                                             # the music's level under the voice (it also ducks when he speaks)
KEEP = {"source.mp4", "title.txt", "thumb.jpg", "zh.srt", "zh.pinyin.srt", "zh.en.srt", "zh.words.json", "zh.align.json",
        "zh.lines.txt", "en.lines.txt", ".english-auto", ".from-whisper", ".split"}
BROWSERS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium"]


def run(*cmd, **kw):
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def duration(f: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                check=True, capture_output=True, text=True).stdout)


def chrome() -> str:
    exe = next((b for b in BROWSERS if Path(b).exists()), None)
    if not exe:
        sys.exit("needs Chrome, Brave or Chromium to draw the scenes")
    return exe


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tts-python", required=True)
    ap.add_argument("--kokoro", required=True)
    ap.add_argument("--voice", default="zm_yunxia")
    ap.add_argument("--music", default="bouncy", help="a style in music.py: bouncy, dizi, sneaky, festival, calm")
    a = ap.parse_args()
    lines = [s for s in (HERE / "script.txt").read_text(encoding="utf-8").splitlines() if s.strip()]
    tmp = Path(tempfile.mkdtemp(prefix="pianpian-demo-"))

    print("drawing the scenes", flush=True)
    run(sys.executable, HERE / "scenes.py", tmp)
    for i in range(1, len(lines) + 1):
        run(chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
            "--window-size=1280,720", f"--screenshot={tmp / f'{i}.png'}", (tmp / f"{i}.svg").as_uri(), stderr=subprocess.DEVNULL)

    print("voicing the lines", flush=True)
    for i, text in enumerate(lines, 1):
        run(a.tts_python, "-m", "mlx_audio.tts.generate", "--model", a.kokoro, "--voice", a.voice, "--lang_code", "z",
            "--speed", "0.9", "--text", text, "--file_prefix", tmp / f"v{i}", "--audio_format", "wav", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    spoken = [duration(tmp / f"v{i}_000.wav") for i in range(1, len(lines) + 1)]
    # each scene lasts its line plus a pause (the first starts with a lead-in, the last ends with a tail)
    dur = [s + GAP + (LEAD if i == 0 else 0) + (TAIL - GAP if i == len(spoken) - 1 else 0) for i, s in enumerate(spoken)]

    print(f"cutting the video ({sum(dur):.1f} s)", flush=True)
    args, vf, af = ["ffmpeg", "-v", "error", "-y"], [], []
    for i, d in enumerate(dur):
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d + FADE:.3f}", "-i", tmp / f"{i + 1}.png"]
    for i in range(len(dur)):
        args += ["-i", tmp / f"v{i + 1}_000.wav"]
    run(sys.executable, HERE / "music.py", tmp / "music.wav", f"{sum(dur) - 2.5:.2f}", a.music)
    args += ["-i", tmp / "music.wav"]
    n = len(dur)
    for i, d in enumerate(dur):
        # still pictures (a slow zoom shook: zoompan moves in whole pixels); only the crossfades move
        vf.append(f"[{i}]scale=1280:720,fps={FPS},format=yuv420p[s{i}]")
        delay = f"adelay={int(LEAD * 1000)}," if i == 0 else ""
        af.append(f"[{n + i}]aresample=48000,{delay}apad=whole_dur={d:.3f}[a{i}]")
    chain, offset = "[s0]", 0.0
    for i in range(1, n):
        offset += dur[i - 1]
        vf.append(f"{chain}[s{i}]xfade=transition=fade:duration={FADE}:offset={offset - FADE / 2:.3f}[x{i}]")
        chain = f"[x{i}]"
    af.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1,asplit=2[voice][key]")
    # the music under the voice: quieter while he speaks (sidechain), faded out at the very end
    af.append(f"[{2 * n}]aresample=48000,volume={MUSIC}[music];[music][key]sidechaincompress=threshold=0.015:ratio=4:attack=20:release=500[duck];"
              f"[voice][duck]amix=inputs=2:normalize=0:duration=first,afade=t=out:st={sum(dur) - 1.0:.3f}:d=1.0,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]")
    video = tmp / "source.mp4"
    run(*args, "-filter_complex", ";".join(vf + af), "-map", chain, "-map", "[aout]", "-t", f"{sum(dur):.3f}",
        "-c:v", "libx264", "-preset", "slow", "-tune", "animation", "-crf", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart", video)

    print("making the subtitles with the app's pipeline", flush=True)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copy2(video, OUT / "source.mp4")
    (OUT / "title.txt").write_text(TITLE + "\n", encoding="utf-8")
    engine = ROOT / ".venv" / "bin" / "python"
    py = engine if engine.exists() else sys.executable
    run(py, ROOT / "pipeline" / "study.py", OUT / "source.mp4", env={**os.environ, "AUTO_EN": "1"})
    en = OUT / "en.lines.txt"
    fixed = [f"{i}\t{EN_FIXES[i]}" if i in EN_FIXES else f"{i}\t{t}" for i, t in (ln.split("\t", 1) for ln in en.read_text(encoding="utf-8").splitlines())]
    if EN_FIXES:
        en.write_text("\n".join(fixed) + "\n", encoding="utf-8")
        (OUT / ".english-auto").unlink(missing_ok=True)
        run(py, ROOT / "pipeline" / "study.py", OUT / "source.mp4")          # imports the fixed English, links the words again
    run("ffmpeg", "-v", "error", "-y", "-ss", "4", "-i", OUT / "source.mp4", "-frames:v", "1", "-vf", "scale=480:-2", OUT / "thumb.jpg")
    for p in OUT.iterdir():
        if p.name not in KEEP:
            p.unlink()

    heard = "".join(c for c in (OUT / "zh.srt").read_text(encoding="utf-8") if "一" <= c <= "鿿")
    said = "".join(c for c in "".join(lines) if "一" <= c <= "鿿")
    print(json.dumps({"seconds": round(sum(dur), 1), "mb": round((OUT / "source.mp4").stat().st_size / 1e6, 2),
                      "transcript matches script": heard == said}), flush=True)
    if heard != said:
        print(f"  script: {said}\n  heard:  {heard}\n  fix zh.long.srt by hand if it matters", flush=True)
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
