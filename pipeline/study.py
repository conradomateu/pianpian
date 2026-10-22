#!/usr/bin/env python3
"""Turn one link or video file into study subtitles (Chinese, pinyin, English) and study.mkv.

    python pipeline/study.py "https://www.bilibili.com/video/BV…"         # public subtitles only
    python pipeline/study.py "https://www.bilibili.com/video/BV…" brave   # use your Bilibili login
    python pipeline/study.py ~/Movies/clip.mp4                            # a file: works in clip_study/

    AUTO_EN=1     also translate to English with the local model (FORCE_EN=1 replaces existing English)
    HARDSUBS=1    the Chinese is burned into the picture: read it with macOS OCR instead of Whisper
    RESPLIT=1 SPLIT_MAX=12   cut the lines again (0 = as transcribed)

Run it with the app's Python environment (pyproject.toml, group "runtime"): every step calls the
scripts next to it with the same interpreter. Each video folder keeps its own state, which server.py
reads too (title.txt, source.url, .hardsubs, .english-auto, .from-whisper, .split, the .srt tracks,
zh.words.json, study.mkv), and every step is skipped when its output is newer than its inputs, so it
can be run again after you fix zh.srt or drop in a hand-made en.lines.txt.
For videos you are allowed to watch; do not re-upload them.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
MODEL = os.environ.get("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
FIXES = HERE / "pinyin_fixes.txt"
os.environ.setdefault("PYTHONWARNINGS", "ignore::SyntaxWarning")   # jieba 0.42 on Python 3.12+


def run(*cmd, **kw) -> None:
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def tool(*args) -> None:
    run(PY, HERE / "srt_tool.py", *args)


def ffmpeg() -> str:
    """Homebrew's ffmpeg if there is one, else the one that comes with imageio-ffmpeg (the app's)."""
    if exe := shutil.which("ffmpeg"):
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def ffmpeg_on_path() -> None:
    """Some steps call a program named exactly `ffmpeg` (mlx_whisper reads the audio that way). On a Mac without
    Homebrew there is none, so the engine's is linked as `ffmpeg` next to this Python and that folder goes first
    on PATH for every step."""
    if shutil.which("ffmpeg"):
        return
    link = Path(PY).parent / "ffmpeg"
    if not link.exists():
        link.symlink_to(ffmpeg())
    os.environ["PATH"] = f"{link.parent}{os.pathsep}{os.environ.get('PATH', '')}"


def newer(out: str | Path, *deps: str | Path) -> bool:
    """out exists and is newer than every dependency that exists."""
    out = Path(out)
    return out.exists() and all(out.stat().st_mtime > Path(d).stat().st_mtime for d in deps if Path(d).exists())


def get_video(src: str, browser: str) -> Path:
    """The study folder for src, with the video (and the platform's Chinese subtitles) in it."""
    if Path(src).is_file():
        f = Path(src).resolve()
        if f.name.startswith("source."):
            return f.parent                                   # already inside a study folder
        work = f.parent / f"{f.stem}_study"
        work.mkdir(exist_ok=True)
        if not (work / f"source{f.suffix}").exists():
            shutil.copy2(f, work / f"source{f.suffix}")
        return work
    ytdlp = [PY, "-m", "yt_dlp", "--ffmpeg-location", ffmpeg(), *(["--cookies-from-browser", browser] if browser else [])]
    # only stdout is captured: yt-dlp's errors still reach the log, where the app turns them into a hint
    vid = subprocess.run([*ytdlp, "--print", "id", "--no-warnings", "--no-playlist", src],
                         check=True, stdout=subprocess.PIPE, text=True).stdout.split()[0]
    work = Path.cwd() / vid
    work.mkdir(exist_ok=True)
    if not list(work.glob("source.*")):
        # ai-zh = Bilibili's AI subtitles (usually only visible when logged in);
        # H.264 first, because AV1 does not play in every browser or player
        run(*ytdlp, "-f", "bv*[height<=1080][vcodec^=avc]+ba/bv*[height<=1080]+ba/b", "--merge-output-format", "mp4",
            "--write-subs", "--sub-langs", "ai-zh,zh-Hans,zh-CN,zh,zh-Hant", "--convert-subs", "srt",
            "--print-to-file", "%(title)s", work / "title.txt", "--no-playlist", "-o", work / "source.%(ext)s", src)
    (work / "source.url").write_text(src + "\n", encoding="utf-8")
    return work


def transcribe(video: str) -> None:
    sys.path.insert(0, str(HERE))
    import models
    model = models.ensure(MODEL)
    print(f"transcribing with {MODEL}", flush=True)
    run(ffmpeg(), "-loglevel", "error", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", "audio.wav")
    # a Simplified-Chinese prompt nudges Whisper away from Traditional output; no conditioning on the
    # previous text avoids repetition loops on long audio; word timestamps let lines be cut exactly
    run(Path(PY).parent / "mlx_whisper", "audio.wav", "--model", model, "--language", "zh",
        "--initial-prompt", "以下是普通话的句子，使用简体中文。",
        "--condition-on-previous-text", "False", "--word-timestamps", "True",
        "--output-format", "all", "--output-name", "zh", "--output-dir", ".")
    Path("zh.srt").rename("zh.long.srt")
    Path("zh.json").rename("zh.whisper.json")
    for f in ("zh.txt", "zh.vtt", "zh.tsv", "audio.wav"):
        Path(f).unlink(missing_ok=True)
    Path(".from-whisper").touch()


def mux(video: str, hardsubs: bool) -> None:
    """One MKV with every track selectable in IINA, mpv or VLC."""
    tracks = [("zh.srt", "中文", "chi"), ("zh.pinyin.srt", "Pinyin", "chi"), ("zh.zh-pinyin.srt", "中文 + Pinyin", "chi")]
    if Path("zh.en.srt").exists():
        tracks += [("zh.en.srt", "English", "eng"), ("zh.trilingual.srt", "中文 + Pinyin + English", "chi"),
                   ("zh.pinyin-en.ass", "Pinyin + English (raised, for burned-in Chinese)", "chi")]
    # on by default: the raised track when the Chinese is part of the picture, else the three-line track
    want = "Pinyin + English (raised" if hardsubs else "中文 + Pinyin + English"
    default = next((i for i, (_, n, _) in enumerate(tracks) if n.startswith(want)), 2)
    args = [ffmpeg(), "-loglevel", "error", "-y", "-i", video]
    for f, _, _ in tracks:
        args += ["-i", f]
    args += ["-map", "0:v", "-map", "0:a"] + [x for i in range(len(tracks)) for x in ("-map", str(i + 1))]
    args += ["-c:v", "copy", "-c:a", "copy", "-c:s", "srt"]
    for i, (f, name, lang) in enumerate(tracks):
        if f.endswith(".ass"):
            args += [f"-c:s:{i}", "ass"]
        args += [f"-metadata:s:s:{i}", f"language={lang}", f"-metadata:s:s:{i}", f"title={name}", f"-disposition:s:{i}", "0"]
    run(*args, f"-disposition:s:{default}", "default", "study.mkv")
    print(f"\ndone: {Path.cwd() / 'study.mkv'}  ({len(tracks)} subtitle tracks)", flush=True)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src, browser = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
    ffmpeg_on_path()
    env = os.environ.get
    work = get_video(src, browser)
    os.chdir(work)
    print(f"folder: {work}", flush=True)                     # server.py reads this line
    if env("HARDSUBS"):
        Path(".hardsubs").touch()                            # remembered for rebuilds
    hardsubs = Path(".hardsubs").exists()
    video = next(str(p) for p in sorted(Path(".").glob("source.*")) if p.suffix not in (".srt", ".vtt", ".xml", ".json"))
    auto_en, resplit = bool(env("AUTO_EN")), bool(env("RESPLIT"))
    split_max = env("SPLIT_MAX") or (Path(".split").read_text().strip() if Path(".split").exists() else "18")

    # Chinese: the platform's subtitles, else OCR (burned in) or Whisper; zh.long.srt as made, zh.srt cut short
    if not Path("zh.srt").exists():
        existing = next((p for p in sorted(Path(".").glob("source.*.srt")) if "danmaku" not in p.name), None)
        if existing:
            print(f"using the platform's subtitles: {existing}", flush=True)
            shutil.copy2(existing, "zh.long.srt")
        elif hardsubs:
            print("Chinese is burned into the picture: reading it with macOS OCR (check zh.srt afterwards)", flush=True)
            run(PY, HERE / "hardsubs_to_srt.py", video, "zh.long.srt", "--crop", "0.15", "--fps", "4")
        else:
            print("no Chinese subtitles found", flush=True)
            transcribe(video)
        resplit = True
    elif resplit:
        if not Path("zh.long.srt").exists():
            shutil.copy2("zh.srt", "zh.long.srt")           # folders made before lines were cut
        if Path(".from-whisper").exists() and not Path("zh.whisper.json").exists():
            transcribe(video)                                 # Whisper folders made before word timestamps
        if Path("en.lines.txt").exists():                     # the line numbers change: the English is redone
            Path("en.lines.txt").rename("en.lines.before-split.txt")
            Path("zh.en.srt").unlink(missing_ok=True)
            auto_en = True
    if resplit:
        print(f"cutting into lines of at most {split_max} characters", flush=True)
        words = ["--words", "zh.whisper.json"] if Path("zh.whisper.json").exists() else []
        tool("split", "zh.long.srt", "--max", split_max, *words, "-o", "zh.srt")
        Path(".split").write_text(split_max + "\n")

    # pinyin, the translation worksheet and the player's words (redone when zh.srt or the fixes change)
    if not newer("zh.pinyin.srt", "zh.srt", FIXES) or not Path("zh.zh-pinyin.srt").exists():   # it writes both
        tool("pinyin", "zh.srt")
    if not newer("zh.lines.txt", "zh.srt"):
        tool("export", "zh.srt")
    if not newer("zh.words.json", "zh.srt", FIXES):
        tool("words", "zh.srt")

    # English from the local model; written to a .part file first, so a failed run never loses English you had
    if auto_en and (not Path("en.lines.txt").exists() or env("FORCE_EN")):
        print("translating with a local model (translate_srt.py)", flush=True)
        run(PY, HERE / "translate_srt.py", "zh.srt", "-o", "en.lines.txt.part")
        Path("en.lines.txt.part").rename("en.lines.txt")
        Path(".english-auto").touch()
    if Path("en.lines.txt").exists() and not newer("zh.en.srt", "en.lines.txt", "zh.srt"):
        tool("import", "zh.srt", "en.lines.txt")
    if Path("zh.en.srt").exists():
        tool("stack", "zh.srt", "zh.pinyin.srt", "zh.en.srt", "-o", "zh.trilingual.srt")
        tool("ass", "zh.pinyin.srt", "zh.en.srt", "-o", "zh.pinyin-en.ass", "--margin-v", "190")
        if not newer("zh.align.json", "zh.en.srt", "zh.srt"):  # English word ↔ Chinese word links
            try:
                run(PY, HERE / "align_srt.py", "zh.srt", "zh.en.srt")
            except subprocess.CalledProcessError:
                print("word links skipped (align_srt.py failed)", flush=True)

    mux(video, hardsubs)
    if not Path("zh.en.srt").exists():
        print("next: add English with the app's Video menu, or save a translation of zh.lines.txt as en.lines.txt and run again")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"step failed ({e.returncode}): {' '.join(map(str, e.cmd[:3]))}…")
