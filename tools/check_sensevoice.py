"""Measure packaged CPU speech on the self-authored demo; no extra model or dependency.

Downloads the pinned speech weights once, outside timed inference. Reports wall time including
process/model loading, transcript comparisons and structural CTC validation, not accuracy parity.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import wave

from check_native_pipeline import ROOT, run_checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipeline", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=ROOT / "scratch/native-acceptance/数据")
    args = parser.parse_args()
    pipeline, data = args.pipeline.resolve(), args.data.resolve()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(pipeline))
    os.environ["PIANPIAN_MODELS"] = str(data / "models")
    import backend
    import models
    import sensevoice
    import imageio_ffmpeg

    output = data / "speech"
    output.mkdir(parents=True, exist_ok=True)
    executable = pipeline / "bin" / backend.native_binary("pianpian-sensevoice")
    env = dict(os.environ)
    env.pop("PIANPIAN_SENSEVOICE_CPU", None)
    profile = run_checked([str(executable), "--cpu-profile"], timeout=30, env=env,
                          stdout=subprocess.PIPE, text=True, encoding="utf-8").stdout.strip()
    model = Path(models.ensure(models.default("transcribe")))
    audio = output / "demo.wav"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", "-i",
                    str(ROOT / "demo/library/pianpian-day/source.mp4"), "-vn", "-ac", "1", "-ar", "16000", str(audio)],
                   check=True, timeout=60)
    with wave.open(str(audio)) as source:
        duration = source.getnframes() / source.getframerate()
        short = output / "short.wav"
        with wave.open(str(short), "wb") as clip:
            clip.setparams(source.getparams())
            clip.writeframes(source.readframes(3 * 16000))
    silence = output / "silence.wav"
    with wave.open(str(silence), "wb") as clip:
        clip.setnchannels(1); clip.setsampwidth(2); clip.setframerate(16000)
        clip.writeframes(b"\0" * 16000)
    report = {"host": platform.platform(), "logical_cpus": os.cpu_count(), "selected_profile": profile,
              "scope": "Single-run CI diagnostic with file-cache effects, including model loading. CTC validation is structural, not boundary accuracy.", "runs": []}
    reference = None
    cases = [("baseline-one-thread", short, 3., True, 1), ("auto-one-thread", short, 3., False, 1),
             ("auto-demo", audio, duration, False, None), ("auto-silence", silence, .5, False, None)]
    for name, clip, seconds, baseline, threads in cases:
        case_env = dict(env)
        if baseline:
            case_env["PIANPIAN_SENSEVOICE_CPU"] = "baseline"
        command = [str(executable), "-m", str(model / sensevoice.MODEL), "--vad", str(model / sensevoice.VAD),
                   "-a", str(clip), "--json", "--backend", "cpu"]
        if threads:
            command += ["--threads", str(threads)]
        print(f"SenseVoice check: {name} ({seconds:.1f}s audio)", flush=True)
        started = time.perf_counter()
        row = {"case": name, "audio_seconds": seconds}
        report["runs"].append(row)
        try:
            with (output / f"{name}.log").open("w", encoding="utf-8") as log:
                result = run_checked(command, env=case_env, stdout=subprocess.PIPE, stderr=log,
                                     text=True, encoding="utf-8", timeout=180)
            row["wall_seconds"] = time.perf_counter() - started
            value = json.loads(result.stdout)
            segments = sensevoice.validate(value, seconds)
            if bool(segments) != (name != "auto-silence"):
                raise RuntimeError(f"Unexpected speech/silence result in {name}")
            (output / f"{name}.json").write_text(result.stdout, encoding="utf-8")
            row.update(segments=len(segments), tokens=sum(len(s["words"]) for s in segments),
                       transcript="".join(s["text"] for s in segments), status="passed")
            if name == "baseline-one-thread":
                reference = value
            elif name == "auto-one-thread":
                row["same_transcript_as_baseline"] = row["transcript"] == "".join(s["text"] for s in reference["segments"])
                row["same_ctc_output_as_baseline"] = value == reference
                if not row["same_transcript_as_baseline"]:
                    raise RuntimeError("Optimized speech changed the short baseline transcript; review before release")
        except Exception as error:
            row.update(status="failed", error=str(error), wall_seconds=time.perf_counter() - started)
            raise
        finally:
            (output / "speech-benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
