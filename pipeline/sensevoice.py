"""Shared native SenseVoice adapter. CTC times are estimates, not manually checked boundaries.

The bundled CPU executable uses the same Q8 weights for recognition and token alignment. Its
seconds/segment/word contract matches the historical zh.whisper.json consumed by srt_tool.py.
No Python ML package, GPU runtime or separately downloaded alignment model is needed here.
"""
import json
import math
import subprocess
import wave
from pathlib import Path

import srt_tool

MODEL = "sensevoice-small-q8.gguf"
VAD = "fsmn-vad.gguf"


def _time(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("SenseVoice returned a non-finite or non-numeric timestamp")
    return float(value)


def validate(data: dict, duration: float) -> list[dict]:
    """Reject incomplete alignment instead of silently using proportional subtitle timing."""
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        raise ValueError("SenseVoice returned no segment array")
    previous = 0.0
    for segment in data["segments"]:
        if not isinstance(segment, dict):
            raise ValueError("SenseVoice returned an invalid segment")
        start, end = _time(segment.get("start")), _time(segment.get("end"))
        if not (previous <= start <= end <= duration + 0.001):
            raise ValueError("SenseVoice segment times overlap or exceed the audio")
        previous = end
        text, words = segment.get("text"), segment.get("words")
        if not isinstance(text, str) or not text.strip() or not isinstance(words, list) or not words:
            raise ValueError("SenseVoice returned speech without aligned words")
        word_end = start
        for word in words:
            if not isinstance(word, dict) or not isinstance(word.get("word"), str) or not word["word"]:
                raise ValueError("SenseVoice returned an invalid aligned word")
            left, right = _time(word.get("start")), _time(word.get("end"))
            if not (word_end - 0.001 <= left <= right <= end + 0.001):
                raise ValueError("SenseVoice word times overlap or exceed their segment")
            word_end = right
        # SentencePiece spaces can be represented on either side of a token boundary.
        if ''.join(''.join(w["word"].split()) for w in words) != ''.join(text.split()):
            raise ValueError("SenseVoice aligned words do not cover its transcript")
    return data["segments"]


def transcribe(audio: Path, model_dir: str, srt: Path, words_json: Path, executable: Path) -> None:
    if not executable.is_file():
        raise RuntimeError("The bundled SenseVoice engine is missing. Reinstall Pianpian; in a checkout run python dev.py native.")
    model, vad = Path(model_dir) / MODEL, Path(model_dir) / VAD
    if not model.is_file() or not vad.is_file():
        raise RuntimeError("SenseVoice weights or voice detector are missing. Complete model setup first.")
    with wave.open(str(audio)) as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
            raise ValueError("SenseVoice expects 16 kHz mono PCM16 audio")
        duration = source.getnframes() / source.getframerate()
    print("transcribing with SenseVoice Q8 (CPU; CTC word timing)", flush=True)
    result = subprocess.run([str(executable), "-m", str(model), "--vad", str(vad), "-a", str(audio), "--json", "--backend", "cpu"],
                            stdout=subprocess.PIPE, text=True, encoding="utf-8", check=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    data = json.loads(result.stdout)
    segments = validate(data, duration)
    if not segments:
        raise RuntimeError("No speech detected in this audio.")
    data.update(model="SenseVoiceSmall-Q8", timing="CTC estimated token intervals")
    cues = [(str(n), f"{srt_tool.stamp(s['start'])} --> {srt_tool.stamp(s['end'])}", s["text"])
            for n, s in enumerate(segments, 1)]
    srt_tool.write_srt(srt, cues)
    words_json.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
