"""One native speech/translation/alignment backend shared by Mac and Windows."""
import subprocess
import sys
from pathlib import Path

import backend
import sensevoice
from plamo import translator as translator  # shared contract, imported lazily by backend.impl()

HERE = Path(__file__).resolve().parent


def transcribe(audio: Path, model_dir: str, srt: Path, words_json: Path) -> None:
    sensevoice.transcribe(audio, model_dir, srt, words_json, HERE / "bin" / backend.native_binary("pianpian-sensevoice"))


def align(zh_srt: Path, en_srt: Path) -> None:
    subprocess.run([sys.executable, str(HERE / "align_srt.py"), str(zh_srt), str(en_srt)], check=True)
