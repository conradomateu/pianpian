"""The Windows runtime: pinned binaries, the backend choice, and the first-run plan's GPU step."""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "pipeline")]
import runtimes  # noqa: E402  (importable on any OS; nothing runs at import time)


def test_every_windows_binary_is_pinned():
    assert runtimes.ASSETS
    for (tool, backend), items in runtimes.ASSETS.items():
        assert tool in ("whisper", "llama") and backend in ("cpu", "vulkan", "cuda")
        assert items
        for a in items:
            assert a["url"].startswith("https://github.com/ggml-org/"), a
            assert a["size"] > 0 and len(a["sha256"]) == 64, a


def test_the_github_mirror_is_opt_in(monkeypatch, tmp_path):
    # no default proxy: a third-party mirror would see every download that fails on GitHub
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path))
    seen = []
    monkeypatch.setattr(runtimes.models, "download",
                        lambda urls, target, size, sha256, label: seen.append(list(urls)) or target.write_bytes(b"x"))
    monkeypatch.setattr(runtimes, "extract", lambda archive, dest: None)
    monkeypatch.setattr(runtimes, "exe", lambda tool, backend=None: Path("whisper-cli.exe"))
    monkeypatch.delenv("PIANPIAN_GITHUB_MIRROR", raising=False)
    runtimes._install("whisper", "cpu")
    assert seen[0] == [runtimes.ASSETS[("whisper", "cpu")][0]["url"]]
    monkeypatch.setenv("PIANPIAN_GITHUB_MIRROR", "https://mirror.example")
    runtimes._install("whisper", "cpu")
    assert seen[1] == [seen[0][0], "https://mirror.example/" + seen[0][0]]


def test_vulkan_needs_a_device_listing(monkeypatch, tmp_path):
    # the loader (vulkan-1.dll) alone proves nothing: without vulkaninfo's device list, say no
    system32 = tmp_path / "System32"
    system32.mkdir()
    (system32 / "vulkan-1.dll").write_bytes(b"x")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.setattr(runtimes.shutil, "which", lambda name: None)
    assert runtimes.vulkan.__wrapped__() is False
    (system32 / "vulkaninfo.exe").write_bytes(b"x")
    monkeypatch.setattr(runtimes.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "deviceName: Some GPU"})())
    assert runtimes.vulkan.__wrapped__() is True


def test_backend_override_and_missing_vulkan_build(monkeypatch):
    monkeypatch.setattr(runtimes, "nvidia", lambda: False)
    monkeypatch.setattr(runtimes, "vulkan", lambda: True)
    monkeypatch.delenv("PIANPIAN_ACCEL", raising=False)
    assert runtimes.backend_for("whisper") == "cpu"          # no pinned Vulkan whisper.cpp yet
    assert runtimes.backend_for("llama") == "vulkan"
    monkeypatch.setenv("PIANPIAN_ACCEL", "cpu")
    assert runtimes.backend_for("llama") == "cpu"
    monkeypatch.setenv("PIANPIAN_ACCEL", "vulkan")           # asked-for Vulkan: whisper still has no such build
    assert runtimes.backend_for("whisper") == "cpu"


def test_cuda_is_preferred_when_nvidia_is_present(monkeypatch):
    monkeypatch.setattr(runtimes, "nvidia", lambda: True)
    monkeypatch.setattr(runtimes, "vulkan", lambda: True)
    monkeypatch.delenv("PIANPIAN_ACCEL", raising=False)
    assert runtimes.backend_for("whisper") == "cuda"
    assert runtimes.backend_for("llama") == "cuda"


def test_status_lists_both_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path))
    monkeypatch.setenv("PIANPIAN_ACCEL", "cpu")
    s = runtimes.status()
    assert set(s["tools"]) == {"whisper", "llama"}
    assert s["size"] > 0 and s["label"] and not s["ready"]


def test_vulkan_only_machine_uses_cpu_whisper(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path))
    monkeypatch.setenv("PIANPIAN_ACCEL", "vulkan")
    s = runtimes.status()
    assert s["tools"]["whisper"]["backend"] == "cpu"
    assert s["tools"]["llama"]["backend"] == "vulkan"
    assert "whisper.cpp: CPU" in s["label"]


def test_windows_plan_offers_the_gpu_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_HOME", str(tmp_path))
    monkeypatch.setenv("PIANPIAN_MODELS", str(tmp_path / "models"))  # Setup.plan() writes os.environ; monkeypatch restores it
    import engine
    e = importlib.reload(engine)
    monkeypatch.setattr(e, "WINDOWS", True)
    monkeypatch.setattr(e.models, "status", lambda: [])
    monkeypatch.setattr(e.runtimes, "status", lambda: {"backend": "cuda", "label": "gpu", "size": 10, "ready": False, "tools": {}})
    e.STATE.update(engine=True, current=True)
    plan = e.SETUP.plan()
    assert plan["runtime"]["label"] == "gpu" and plan["needed"]
    monkeypatch.setattr(e.runtimes, "status", lambda: {"backend": "cuda", "label": "gpu", "size": 10, "ready": True, "tools": {}})
    assert not e.SETUP.plan()["needed"]
