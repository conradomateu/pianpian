"""Offline translation benchmark contracts; Windows binaries are simulated on this Mac."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import acceleration as a  # noqa: E402

LLAMA_MODEL = "plamo-3-translate-0.8b-Q3_K_M.gguf"


def installed(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for name in ("llama-server.exe", "llama-bench.exe"):
        (runtime / name).write_bytes(b"fake executable")
    model = tmp_path / "model"
    model.mkdir()
    (model / LLAMA_MODEL).write_bytes(b"fake pinned weights")
    monkeypatch.setattr(a.runtimes, "exe", lambda tool, backend: runtime / "llama-server.exe")
    monkeypatch.setattr(a.models, "default", lambda task: task)
    monkeypatch.setattr(a.models, "lock", lambda: {"translate": {"files": [{"name": LLAMA_MODEL}]}})
    monkeypatch.setattr(a.models, "local_path", lambda repo: model)
    monkeypatch.setattr(a.models, "ensure", lambda *args: pytest.fail("benchmark must not download models"))
    monkeypatch.setattr(a.runtimes, "ensure", lambda *args: pytest.fail("benchmark must not download runtimes"))
    return runtime, model


def fake_run(cmd, **kwargs):
    assert Path(cmd[0]).name == "llama-bench.exe"
    assert 0 < kwargs["timeout"] <= 600
    assert kwargs["capture_output"] and kwargs["encoding"] == "utf-8"
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


@pytest.fixture(autouse=True)
def windows_runtime(monkeypatch):
    import runtimes
    monkeypatch.setattr(runtimes.platform_backend, "NAME", "win32")


def test_missing_runtimes_never_spawn_or_download(monkeypatch, tmp_path):
    monkeypatch.setattr(a.runtimes, "exe", lambda *args: None)
    monkeypatch.setattr(a.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not spawn"))
    monkeypatch.setattr(a.models, "ensure", lambda *args: pytest.fail("must not download"))
    monkeypatch.setattr(a.runtimes, "ensure", lambda *args: pytest.fail("must not download"))
    for result in (a.readiness(), a.benchmark(tmp_path)):
        [tool] = result["tools"]
        assert tool["tool"] == "llama" and tool["status"] == "unavailable"


def test_realistic_diagnostics_produce_measured_translation_only(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)
    monkeypatch.setenv("PIANPIAN_ACCEL", "cpu")
    monkeypatch.setattr(a.subprocess, "run", fake_run)
    assert a.readiness()["tools"] == [{"tool": "llama", "status": "ready", "reason": ""}]
    [llama] = a.benchmark(tmp_path / "results")["tools"]
    assert llama["tool"] == "llama" and llama["status"] == "measured"
    assert llama["cpu_seconds"] == 4 and llama["gpu_seconds"] == 1 and llama["speedup"] == 4
    assert llama["estimate"]["cpu_seconds"] == 400 and llama["estimate"]["gpu_seconds"] == 100
    assert "synthetic" in llama["workload"] and "excludes loading" in llama["estimate"]["label"]
    assert len(list((tmp_path / "results").glob("*.log"))) == 2
    assert a.runtimes.backend_for("llama") == "cpu"  # the optional test never changes the saved choice


@pytest.mark.parametrize("log", ["ggml_cuda_init: found 1 CUDA device\nCUDA = 1\n",
                                  "load_tensors: offloaded 25/25 layers to GPU\n",
                                  "load_tensors: CUDA0 model buffer size = 1000.00 MiB\n"])
def test_detected_cuda_without_actual_offload_is_not_a_speed_claim(monkeypatch, tmp_path, log):
    installed(monkeypatch, tmp_path)

    def only_detected(cmd, **kwargs):
        result = fake_run(cmd, **kwargs)
        if cmd[cmd.index("-ngl") + 1] == "999":
            result.stderr = log
        return result

    monkeypatch.setattr(a.subprocess, "run", only_detected)
    [result] = a.benchmark(tmp_path / "results")["tools"]
    assert result["status"] == "unconfirmed" and "speedup" not in result


def test_a_gpu_cpu_baseline_does_not_make_a_speed_claim(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)

    def wrong_baseline(cmd, **kwargs):
        result = fake_run(cmd, **kwargs)
        result.stderr = "load_tensors: offloaded 25/25 layers to GPU\n"
        return result

    monkeypatch.setattr(a.subprocess, "run", wrong_baseline)
    [result] = a.benchmark(tmp_path / "results")["tools"]
    assert result["status"] == "unconfirmed" and "CPU-only baseline" in result["reason"]
    assert "speedup" not in result


@pytest.mark.parametrize("missing", ["model", "llama-bench"])
def test_missing_model_or_benchmark_binary_is_explained(monkeypatch, tmp_path, missing):
    runtime, model = installed(monkeypatch, tmp_path)
    (model / LLAMA_MODEL if missing == "model" else runtime / "llama-bench.exe").unlink()
    monkeypatch.setattr(a.subprocess, "run", lambda *args, **kwargs: pytest.fail("not ready"))
    [result] = a.benchmark(tmp_path / "results")["tools"]
    assert result["status"] == "unavailable" and missing in result["reason"]


def test_timeout_has_no_speed_claim(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)

    def timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(a.subprocess, "run", timeout)
    [result] = a.benchmark(tmp_path / "results")["tools"]
    assert result["status"] == "failed" and "10-minute" in result["reason"] and "speedup" not in result


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), True, None, "1000", 1e-320])
def test_invalid_runtime_timings_are_not_reported(monkeypatch, tmp_path, bad):
    installed(monkeypatch, tmp_path)

    def bad_time(cmd, **kwargs):
        result = fake_run(cmd, **kwargs)
        result.stdout = json.dumps([{"n_prompt": 256, "n_gen": 32, "avg_ns": bad}])
        return result

    monkeypatch.setattr(a.subprocess, "run", bad_time)
    [result] = a.benchmark(tmp_path / "results")["tools"]
    assert result["status"] == "failed" and "speedup" not in result


@pytest.mark.parametrize("text,reason", [('{"not":"a list"}', "unreadable timing"),
                                        ('[{"n_prompt":256,"n_gen":32}]', "processing time"),
                                        ('[{"n_prompt":128,"n_gen":32,"avg_ns":100}]', "expected"),
                                        ('[]', "expected")])
def test_malformed_runtime_results_have_readable_errors(text, reason):
    with pytest.raises(ValueError, match=reason):
        a._llama_time(text)
