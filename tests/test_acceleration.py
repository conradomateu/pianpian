"""The offline benchmark contract; Windows binaries are simulated on this Mac."""
import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import acceleration as a  # noqa: E402

WHISPER_MODEL = "ggml-large-v3-turbo-q8_0.bin"
LLAMA_MODEL = "Hy-MT2-1.8B-Q4_K_M.gguf"


def installed(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for name in ("whisper-cli.exe", "llama-server.exe", "llama-bench.exe"):
        (runtime / name).write_bytes(b"fake executable")
    model = tmp_path / "model"
    model.mkdir()
    for name in (WHISPER_MODEL, LLAMA_MODEL):
        (model / name).write_bytes(b"fake pinned weights")
    monkeypatch.setattr(a.runtimes, "exe", lambda tool, backend: runtime / ("whisper-cli.exe" if tool == "whisper" else "llama-server.exe"))
    monkeypatch.setattr(a.models, "default", lambda task: task)
    monkeypatch.setattr(a.models, "lock", lambda: {"transcribe": {"files": [{"name": WHISPER_MODEL}]},
                                                 "translate": {"files": [{"name": LLAMA_MODEL}]}})
    monkeypatch.setattr(a.models, "local_path", lambda repo: model)
    monkeypatch.setattr(a.models, "ensure", lambda *args: pytest.fail("benchmark must not download models"))
    monkeypatch.setattr(a.runtimes, "ensure", lambda *args: pytest.fail("benchmark must not download runtimes"))
    return runtime, model


def fake_run(cmd, **kwargs):
    assert 0 < kwargs["timeout"] <= 600
    assert kwargs["capture_output"] and kwargs["encoding"] == "utf-8"
    if Path(cmd[0]).name == "whisper-cli.exe":
        assert cmd[cmd.index("-mc") + 1] == "0"
        gpu = "-ng" not in cmd
        Path(cmd[cmd.index("-of") + 1] + ".json").write_text(json.dumps({"transcription": [{"text": "你好我叫片片"}]}))
        log = "whisper_print_timings: load time = 1000.00 ms\nwhisper_print_timings: total time = "
        log += "3000.00 ms\n" if gpu else "5000.00 ms\n"
        log += ("whisper_backend_init_gpu: using CUDA0 backend\nwhisper_model_load: CUDA0 total size = 800.00 MB\n"
                if gpu else "whisper_backend_init_gpu: no GPU found\n")
        return subprocess.CompletedProcess(cmd, 0, "", log)
    assert "--offline" in cmd and cmd[cmd.index("-pg") + 1] == "256,32"
    assert cmd[cmd.index("-r") + 1] == "2" and "--no-warmup" not in cmd
    gpu = cmd[cmd.index("-ngl") + 1] == "999"
    if not gpu:
        assert cmd[cmd.index("-dev") + 1] == "none"
        assert cmd[cmd.index("-nkvo") + 1] == "1" and cmd[cmd.index("-nopo") + 1] == "1"
    log = ("load_tensors: offloaded 25/25 layers to GPU\nload_tensors: CUDA0 model buffer size = 1000.00 MiB\n"
           if gpu else "load_tensors: offloaded 0/25 layers to GPU\n")
    data = [{"n_prompt": 256, "n_gen": 32, "avg_ns": 1_000_000_000 if gpu else 4_000_000_000}]
    return subprocess.CompletedProcess(cmd, 0, json.dumps(data), log)


def test_missing_runtimes_never_spawn_or_download(monkeypatch, tmp_path):
    monkeypatch.setattr(a.runtimes, "exe", lambda *args: None)
    monkeypatch.setattr(a.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not spawn"))
    monkeypatch.setattr(a.models, "ensure", lambda *args: pytest.fail("must not download"))
    assert all(t["status"] == "unavailable" for t in a.readiness()["tools"])
    assert all(t["status"] == "unavailable" for t in a.benchmark(tmp_path)["tools"])


def test_realistic_diagnostics_produce_measured_comparisons(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)
    monkeypatch.setattr(a.subprocess, "run", fake_run)
    assert all(t["status"] == "ready" for t in a.readiness()["tools"])
    whisper, llama = a.benchmark(tmp_path / "results")["tools"]
    assert whisper["status"] == llama["status"] == "measured"
    assert whisper["cpu_seconds"] == 4 and whisper["gpu_seconds"] == 2 and whisper["speedup"] == 2
    assert whisper["load_seconds"] == {"cpu": 1, "gpu": 1}
    assert whisper["estimate"]["cpu_seconds"] == 80 and whisper["estimate"]["gpu_seconds"] == 40
    assert llama["speedup"] == 4 and llama["estimate"]["cpu_seconds"] == 400
    assert "synthetic" in llama["workload"] and "excludes loading" in llama["estimate"]["label"]
    assert len(list((tmp_path / "results").glob("*.log"))) == 4


def test_detected_cuda_without_actual_offload_is_not_a_speed_claim(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)

    def only_detected(cmd, **kwargs):
        result = fake_run(cmd, **kwargs)
        if "-ng" not in cmd:
            result.stderr = "ggml_cuda_init: found 1 CUDA device\nCUDA = 1\n"  # compilation/detection is insufficient
        return result

    monkeypatch.setattr(a.subprocess, "run", only_detected)
    for result in a.benchmark(tmp_path / "results")["tools"]:
        assert result["status"] == "unconfirmed" and "speedup" not in result


def test_missing_model_or_benchmark_binary_is_explained(monkeypatch, tmp_path):
    runtime, model = installed(monkeypatch, tmp_path)
    (model / WHISPER_MODEL).unlink()
    (runtime / "llama-bench.exe").unlink()
    monkeypatch.setattr(a.subprocess, "run", lambda *args, **kwargs: pytest.fail("not ready"))
    whisper, llama = a.benchmark(tmp_path / "results")["tools"]
    assert whisper["status"] == llama["status"] == "unavailable"
    assert "model" in whisper["reason"] and "llama-bench" in llama["reason"]


def test_timeout_does_not_prevent_the_other_tool_comparison(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)

    def timeout(cmd, **kwargs):
        if "whisper" in cmd[0]:
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return fake_run(cmd, **kwargs)

    monkeypatch.setattr(a.subprocess, "run", timeout)
    whisper, llama = a.benchmark(tmp_path / "results")["tools"]
    assert whisper["status"] == "failed" and "10-minute" in whisper["reason"]
    assert llama["status"] == "measured"


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_invalid_runtime_timings_are_not_reported(monkeypatch, tmp_path, bad):
    installed(monkeypatch, tmp_path)

    def bad_time(cmd, **kwargs):
        result = fake_run(cmd, **kwargs)
        if "llama" in cmd[0]:
            result.stdout = json.dumps([{"n_prompt": 256, "n_gen": 32, "avg_ns": bad}])
        return result

    monkeypatch.setattr(a.subprocess, "run", bad_time)
    llama = a.benchmark(tmp_path / "results")["tools"][1]
    assert llama["status"] == "failed" and "speedup" not in llama


def test_bundled_sample_is_thirty_seconds_of_mono_pcm():
    with wave.open(str(a.SAMPLE), "rb") as sample:
        assert sample.getnchannels() == 1 and sample.getsampwidth() == 2
        assert sample.getframerate() == 16000
        assert sample.getnframes() / sample.getframerate() == a.SAMPLE_SECONDS
    assert a.SAMPLE.stat().st_size < 1_000_000


def test_malformed_runtime_results_have_readable_errors():
    with pytest.raises(ValueError, match="loading and total times"):
        a._whisper_times("whisper_print_timings: total time = 5000 ms")
    with pytest.raises(ValueError, match="unreadable timing"):
        a._llama_time('{"not":"a list"}')
    with pytest.raises(ValueError, match="processing time"):
        a._llama_time('[{"n_prompt":256,"n_gen":32}]')
