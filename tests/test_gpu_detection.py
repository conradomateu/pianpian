"""CUDA discovery contracts, simulated on macOS; these do not validate a Windows GPU."""
import ctypes
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import runtimes  # noqa: E402


@pytest.mark.parametrize("init_code,count_code,count,ready", [(0, 0, 1, True), (0, 0, 0, False),
                                                            (1, 0, 1, False), (0, 1, 1, False)])
def test_cuda_driver_requires_successful_initialization_and_a_device(monkeypatch, init_code, count_code, count, ready):
    class Function:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    def devices(pointer):
        pointer._obj.value = count
        return count_code

    driver = type("Driver", (), {"cuInit": Function(lambda flags: init_code), "cuDeviceGetCount": Function(devices)})()
    monkeypatch.setattr(ctypes, "WinDLL", lambda name: driver, raising=False)
    assert runtimes.cuda_driver() is ready


@pytest.mark.parametrize("missing_api", [False, True])
def test_cuda_driver_missing_or_unloadable_is_not_ready(monkeypatch, missing_api):
    if missing_api:
        monkeypatch.delattr(ctypes, "WinDLL", raising=False)
    else:
        def unavailable(name):
            raise OSError("nvcuda.dll unavailable")
        monkeypatch.setattr(ctypes, "WinDLL", unavailable, raising=False)
    assert not runtimes.cuda_driver()


def installed_cuda(monkeypatch, tmp_path, tools=("llama",)):
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path))
    from test_windows_crt import bundle
    monkeypatch.setattr(runtimes, "CRT_DIR", bundle(tmp_path / "crt"))
    for tool in tools:
        folder = runtimes.folder(tool, "cuda")
        folder.mkdir(parents=True)
        (folder / runtimes.EXES[tool][0]).write_bytes(b"simulated executable; never run")
        (folder / ".complete").write_text(json.dumps(runtimes.stamp(tool, "cuda")))
        runtimes._sync_crt(folder / runtimes.EXES[tool][0])
    monkeypatch.setattr(runtimes, "ensure", lambda *args, **kw: pytest.fail("detection must never install"))
    monkeypatch.setattr(runtimes.models, "download", lambda *args, **kw: pytest.fail("detection must never download"))
    monkeypatch.setattr(runtimes, "nvidia", lambda: True)
    monkeypatch.setenv("PIANPIAN_ACCEL", "cpu")


@pytest.mark.parametrize("output,returncode,visible", [("Available devices:\nCUDA0: NVIDIA test GPU\n", 0, True),
                                                     ("Available devices:\n", 0, False),
                                                     ("CUDA0: NVIDIA test GPU\n", 1, False),
                                                     ("CUDA support compiled in", 0, False)])
def test_installed_cuda_tools_enumerate_without_claiming_inference(monkeypatch, tmp_path, output, returncode, visible):
    installed_cuda(monkeypatch, tmp_path)
    monkeypatch.setattr(runtimes, "cuda_driver", lambda: True)
    calls = []

    def probe(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=output)

    monkeypatch.setattr(runtimes, "probe_run", probe)
    result = runtimes.detect()
    assert result["cuda"] == {"driverReady": True, "installed": {"llama": True}, "deviceVisible": visible}
    assert calls == [[str(runtimes.exe("llama", "cuda")), "--list-devices"]]
    assert "optional local test" in result["message"] and "SenseVoice speech stays on CPU" in result["message"]
    assert "speedup" not in result
    assert runtimes.backend_for("llama") == "cpu"


@pytest.fixture(autouse=True)
def windows_runtime(monkeypatch):
    import runtimes
    monkeypatch.setattr(runtimes.platform_backend, "NAME", "win32")


def test_failed_driver_initialization_never_launches_installed_cuda_tools(monkeypatch, tmp_path):
    installed_cuda(monkeypatch, tmp_path)
    monkeypatch.setattr(runtimes, "cuda_driver", lambda: False)
    monkeypatch.setattr(runtimes, "probe_run", lambda *args, **kw: pytest.fail("unready driver launched a tool"))
    result = runtimes.detect()
    assert not result["cuda"]["driverReady"] and not result["cuda"]["deviceVisible"]
    assert not result["benchmarkAvailable"]
    assert runtimes.backend_for("llama") == "cpu"


def test_driver_without_pianpian_cuda_tools_does_not_download_them(monkeypatch, tmp_path):
    installed_cuda(monkeypatch, tmp_path, tools=())
    monkeypatch.setattr(runtimes, "cuda_driver", lambda: True)
    monkeypatch.setattr(runtimes, "probe_run", lambda *args, **kw: pytest.fail("missing tools must not launch"))
    result = runtimes.detect()
    assert result["cuda"]["installed"] == {"llama": False}
    assert not result["benchmarkAvailable"] and not result["cuda"]["deviceVisible"]


def test_cuda_device_probe_timeout_does_not_claim_working_inference(monkeypatch, tmp_path):
    installed_cuda(monkeypatch, tmp_path)
    monkeypatch.setattr(runtimes, "cuda_driver", lambda: True)

    def timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(runtimes, "probe_run", timeout)
    result = runtimes.detect()
    assert not result["cuda"]["deviceVisible"] and "speedup" not in result


def test_unknown_hardware_keeps_cpu_and_offers_no_cuda_benchmark(monkeypatch):
    monkeypatch.setattr(runtimes, "nvidia", lambda: False)
    monkeypatch.setattr(runtimes, "vulkan", lambda: False)
    monkeypatch.setattr(runtimes, "cuda_driver", lambda: pytest.fail("unknown hardware initialized CUDA"))
    result = runtimes.detect()
    assert result["backend"] == "cpu" and not result.get("benchmarkAvailable")
