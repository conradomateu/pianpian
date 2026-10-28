"""The macOS engines: mlx_whisper for speech, mlx_lm for translation, Apple Vision for burned-in text.

The contract is in backend.py. Every engine is imported inside its function, so this module imports on
any platform (the tests rely on that).
"""
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ffmpeg_on_path() -> None:
    """mlx_whisper reads the audio with a program named exactly `ffmpeg`. On a Mac without Homebrew there is
    none, so the engine's (imageio-ffmpeg) is linked as `ffmpeg` next to this Python and that folder goes first
    on PATH."""
    if shutil.which("ffmpeg"):
        return
    import imageio_ffmpeg
    link = Path(sys.executable).parent / "ffmpeg"
    if not link.exists():
        link.symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
    os.environ["PATH"] = f"{link.parent}{os.pathsep}{os.environ.get('PATH', '')}"


def transcribe(audio: Path, model_dir: str, srt: Path, words_json: Path) -> None:
    """Whisper (MLX) on a 16 kHz mono wav: writes srt (one cue per segment) and words_json (segments with word times).
    mlx_whisper writes whisper.* next to srt first, so srt and words_json must be in the same folder."""
    ffmpeg_on_path()
    out = srt.parent
    # a Simplified-Chinese prompt nudges Whisper away from Traditional output; no conditioning on the
    # previous text avoids repetition loops on long audio; word timestamps let lines be cut exactly
    subprocess.run([str(Path(sys.executable).parent / "mlx_whisper"), str(audio), "--model", model_dir, "--language", "zh",
                    "--initial-prompt", "以下是普通话的句子，使用简体中文。",
                    "--condition-on-previous-text", "False", "--word-timestamps", "True",
                    "--output-format", "all", "--output-name", "whisper", "--output-dir", str(out)], check=True)
    (out / "whisper.srt").replace(srt)
    (out / "whisper.json").replace(words_json)
    for ext in ("txt", "vtt", "tsv"):
        (out / f"whisper.{ext}").unlink(missing_ok=True)


@contextmanager
def translator(model_dir: str):
    """Hy-MT2 with mlx_lm, loaded once; yields generate(prompt, temperature, max_tokens) -> reply text."""
    from mlx_lm import generate as mlx_generate
    from mlx_lm import load
    from mlx_lm.sample_utils import make_logits_processors, make_sampler
    model, tok = load(model_dir)
    procs = make_logits_processors(repetition_penalty=1.05)

    def generate(prompt: str, temperature: float, max_tokens: int) -> str:
        # the model card's top_p/top_k/penalty; at temperature 0 make_sampler is greedy
        text = tok.apply_chat_template([{"role": "user", "content": prompt}], add_generation_prompt=True, tokenize=False)
        return mlx_generate(model, tok, prompt=text, max_tokens=max_tokens, logits_processors=procs, verbose=False,
                            sampler=make_sampler(temp=temperature, top_p=0.6, top_k=20))

    yield generate


def ocr(frames_dir: str) -> str:
    """Apple Vision over every frame. The app ships ocr_frames compiled (tools/build_app.py); a checkout runs it with swift."""
    built = HERE / "bin" / "ocr_frames"
    cmd = [str(built), frames_dir] if built.exists() else ["swift", str(HERE / "ocr_frames.swift"), frames_dir]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
