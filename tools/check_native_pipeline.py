"""Exercise the packaged native pipeline with the self-authored demo and an isolated data folder.

Run with an engine Python installed from the platform's hashed requirements, after dev.py build:
    python tools/check_native_pipeline.py --pipeline dist/Pianpian/_internal/pipeline

Downloads only current pinned models and CPU tools into scratch/native-acceptance by default.
It is an inference/integration check, not a translation-accuracy or GPU-performance benchmark.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
MODEL = "pfnet/plamo-3-translate-0.8b-GGUF"
PACKAGES = {"imageio-ffmpeg", "jieba", "pypinyin", "yt-dlp", "zhconv"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def validate_outputs(work: Path, read_srt, validate_speech, duration: float) -> dict:
    tracks = {name: read_srt(work / name) for name in ("zh.srt", "zh.pinyin.srt", "zh.en.srt")}
    chinese = tracks["zh.srt"]
    require(bool(chinese), "No Chinese subtitles were produced")
    for name, cues in tracks.items():
        require(len(cues) == len(chinese), f"{name}: subtitle count differs from Chinese")
        require([cue[:2] for cue in cues] == [cue[:2] for cue in chinese], f"{name}: subtitle IDs/times differ")
        require(all(cue[2].strip() for cue in cues), f"{name}: empty subtitle")
    speech = json.loads((work / "zh.whisper.json").read_text(encoding="utf-8"))
    require(speech.get("model") == "SenseVoiceSmall-Q8", "Packaged speech used the wrong model")
    segments = validate_speech(speech, duration)
    require(bool(segments), "Speech helper returned no segments")
    words = json.loads((work / "zh.words.json").read_text(encoding="utf-8"))
    require(words.get("version") == 2 and len(words.get("cues", [])) == len(chinese), "Invalid word metadata")
    intervals = []
    for cue in words["cues"]:
        require(len(cue.get("k", [])) == len(cue["w"]), "Missing spoken word times")
        for row, times in zip(cue["w"], cue["k"]):
            require(len(row) == len(times), "Word timing count mismatch")
            for pair in times:
                if pair == 0:
                    continue
                require(isinstance(pair, list) and len(pair) == 2 and all(type(x) in (int, float) and math.isfinite(x) for x in pair),
                        "Invalid word interval")
                require(cue["s"] - 0.15 <= pair[0] < pair[1] <= cue["e"] + 0.15, "Word interval out of bounds")
                intervals.append(pair)
    require(bool(intervals), "No spoken word intervals reached the player metadata")
    alignment = json.loads((work / "zh.align.json").read_text(encoding="utf-8"))
    require(alignment.get("version") == 1 and alignment.get("model") == MODEL and alignment.get("layer") == 7,
            "Missing current PLaMo word links")
    require(len(alignment.get("cues", [])) == len(chinese), "Word-link cue count mismatch")
    count = 0
    for zh, en, links in zip(chinese, tracks["zh.en.srt"], alignment["cues"]):
        for link in links:
            require(len(link) == 5 and all(type(x) is int for x in link[:4]), "Invalid link offsets")
            require(0 <= link[0] < link[1] <= len(en[2]) and 0 <= link[2] < link[3] <= len(zh[2]), "Link offset out of bounds")
            require(type(link[4]) in (int, float) and math.isfinite(link[4]), "Invalid link score")
            count += 1
    require(count > 0, "No bilingual model links were produced")
    require((work / "study.mkv").is_file() and (work / "study.mkv").stat().st_size > 0, "No study video")
    return {"cues": len(chinese), "speech_segments": len(segments), "word_intervals": len(intervals), "bilingual_links": count}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipeline", type=Path, required=True, help="The pipeline directory inside the built app")
    parser.add_argument("--data", type=Path, default=ROOT / "scratch" / "native-acceptance" / "数据", help="Isolated cache/results folder; may reuse a prior test's pins")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    pipeline, data = args.pipeline.resolve(), args.data.resolve()
    require((pipeline / "study.py").is_file(), "Packaged pipeline directory is missing")
    # No cached source module or bytecode may mask the packaged code or alter its signature.
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.path.insert(0, str(pipeline))
    installed = {d.metadata["Name"].lower().replace("_", "-") for d in importlib.metadata.distributions()}
    require(installed == PACKAGES, f"Acceptance needs a clean five-package engine, got {sorted(installed)}")
    data.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for key in ("ASR_MODEL", "MT_MODEL", "PIANPIAN_LLAMA_DEVICE", "FORCE_EN", "RESPLIT", "SPLIT_MAX"):
        env.pop(key, None)
    env.update(PIANPIAN_HOME=str(data / "home"), PIANPIAN_MODELS=str(data / "models"),
               PIANPIAN_RUNTIME=str(data / "runtime"), PIANPIAN_CACHE=str(data / "cache"),
               PIANPIAN_ACCEL="cpu", AUTO_EN="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    os.environ.update(env)
    import backend
    import models
    import runtimes
    import sensevoice
    import srt_tool
    import imageio_ffmpeg
    require(models.default("translate") == MODEL, "Packaged model catalog is stale")
    require(set(models.lock()) == {MODEL, "FunAudioLLM/SenseVoiceSmall-GGUF"}, "Packaged catalog still contains old models")
    require(runtimes.backend_for("llama") == "cpu", "Acceptance must not select or download a GPU runtime")
    for name in (backend.native_binary("pianpian-sensevoice"), backend.native_binary("pianpian-align")):
        subprocess.run([str(pipeline / "bin" / name), "--help"], check=True, stdout=subprocess.DEVNULL, timeout=30)
    work = Path(tempfile.mkdtemp(prefix="中文 空格-", dir=data))
    source = ROOT / "demo" / "library" / "pianpian-day" / "source.mp4"
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copyfile(source, work / "source.mp4")
    log_path = work / "pipeline.log"
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run([sys.executable, str(pipeline / "study.py"), str(work / "source.mp4")],
                       env=env, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    wav = work / "validation.wav"
    subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-i", str(work / "source.mp4"), "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True, timeout=60)
    with wave.open(str(wav)) as audio:
        duration = audio.getnframes() / audio.getframerate()
    result = validate_outputs(work, srt_tool.read_srt, sensevoice.validate, duration)
    streams = subprocess.run([ffmpeg, "-hide_banner", "-i", str(work / "study.mkv")], capture_output=True, text=True, encoding="utf-8", timeout=30)
    result["subtitle_tracks"] = len(re.findall(r"Stream #\d+:\d+.*Subtitle:", streams.stderr))
    require(result["subtitle_tracks"] == 6, "Study video does not contain six subtitle tracks")
    require(hashlib.sha256(source.read_bytes()).hexdigest() == original_hash == hashlib.sha256((work / "source.mp4").read_bytes()).hexdigest(),
            "Acceptance changed the original or copied demo video")
    if backend.NAME == "win32":
        require(not (data / "runtime" / "llama-cuda").exists() and not (data / "runtime" / "llama-vulkan").exists(), "CPU acceptance downloaded GPU tools")
    result.update(platform=sys.platform, python=sys.version.split()[0], model=MODEL, accelerator="cpu", source_sha256=original_hash,
                  packages=sorted(installed), pipeline=str(pipeline), work=str(work), quality_scope="Execution and data contracts, not translation accuracy")
    (data / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
