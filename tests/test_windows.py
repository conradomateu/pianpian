"""The Windows runtime: pinned binaries, the backend choice, and the first-run plan's GPU step."""
import importlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "pipeline")]
import runtimes  # noqa: E402  (importable on any OS; nothing runs at import time)


@pytest.fixture(autouse=True)
def windows_runtime(monkeypatch, tmp_path):
    import runtimes
    monkeypatch.setattr(runtimes.platform_backend, "NAME", "win32")
    from test_windows_crt import bundle
    monkeypatch.setattr(runtimes, "CRT_DIR", bundle(tmp_path / "crt"))


def test_every_windows_binary_is_pinned():
    assert set(runtimes.EXES) == set(runtimes.RELEASES) == {"llama"}
    assert runtimes.ASSETS
    for (tool, backend), items in runtimes.ASSETS.items():
        assert tool == "llama" and backend in ("cpu", "vulkan", "cuda")
        assert items
        for a in items:
            assert a["url"].startswith("https://github.com/ggml-org/"), a
            assert a["size"] > 0 and len(a["sha256"]) == 64, a


def test_runtime_cli_default_installs_only_translation(monkeypatch):
    installed = []
    monkeypatch.setattr(runtimes.sys, "argv", ["runtimes.py", "ensure"])
    monkeypatch.setattr(runtimes, "ensure", lambda tool: installed.append(tool) or "llama-server.exe")
    runtimes.main()
    assert installed == ["llama"]


def fake_downloads(monkeypatch, tmp_path, files=("llama-server.exe", "ggml.dll"), fail=None):
    """[simulated on macOS] every archive is a small zip with these files; `fail` names one that won't download."""
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path / "runtime"))
    seen = []

    def download(urls, target, size, sha256, label):
        seen.append(list(urls))
        if target.name == fail:
            raise OSError("timed out")
        with zipfile.ZipFile(target, "w") as z:
            for f in files:
                z.writestr(f"bin/{f}", f"{target.name}:{f}")
    monkeypatch.setattr(runtimes.models, "download", download)
    return seen


def test_the_github_mirror_is_opt_in(monkeypatch, tmp_path):
    # no default proxy: a third-party mirror would see every download that fails on GitHub
    seen = fake_downloads(monkeypatch, tmp_path)
    monkeypatch.delenv("PIANPIAN_GITHUB_MIRROR", raising=False)
    runtimes._install("llama", "cpu")
    assert seen[0] == [runtimes.ASSETS[("llama", "cpu")][0]["url"]]
    monkeypatch.setenv("PIANPIAN_GITHUB_MIRROR", "https://mirror.example")
    runtimes._install("llama", "cpu")
    assert seen[1] == [seen[0][0], "https://mirror.example/" + seen[0][0]]


def test_a_new_pin_replaces_the_old_build_whole(monkeypatch, tmp_path):
    # [simulated on macOS] bumping RELEASES must make the old folder "not ready" and swap the new build in,
    # with no file of the old release left beside the new one
    fake_downloads(monkeypatch, tmp_path)
    exe = Path(runtimes.ensure("llama", "cuda"))
    d = runtimes.folder("llama", "cuda")
    assert exe == d / "bin" / "llama-server.exe" and runtimes.exe("llama", "cuda") == exe
    done = json.loads((d / ".complete").read_text(encoding="utf-8"))
    assert done["release"] == runtimes.RELEASES["llama"] and len(done["sha256"]) == 2   # the server and cudart zips
    (d / "bin" / "old-only.dll").write_bytes(b"from the old release")
    monkeypatch.setitem(runtimes.RELEASES, "llama", "b99999")
    assert runtimes.exe("llama", "cuda") is None
    monkeypatch.setenv("PIANPIAN_ACCEL", "cuda")
    assert not runtimes.status()["tools"]["llama"]["ready"]
    assert Path(runtimes.ensure("llama", "cuda")) == exe
    assert not (d / "bin" / "old-only.dll").exists()
    assert json.loads((d / ".complete").read_text(encoding="utf-8"))["release"] == "b99999"
    assert sorted(p.name for p in runtimes.cache().iterdir()) == ["llama-cpu", "llama-cuda"]   # no work folder left


def test_a_failed_download_leaves_the_working_build(monkeypatch, tmp_path):
    fake_downloads(monkeypatch, tmp_path)
    exe = runtimes.ensure("llama", "cuda")
    monkeypatch.setitem(runtimes.RELEASES, "llama", "b99999")
    fake_downloads(monkeypatch, tmp_path, fail="cudart-llama-bin-win-cuda-12.4-x64.zip")
    with pytest.raises(OSError, match="it resumes"):
        runtimes.ensure("llama", "cuda")
    assert Path(exe).is_file()                                 # the old build is still there, only not "ready"
    monkeypatch.setitem(runtimes.RELEASES, "llama", "b100000")       # pinned again before that one finished
    fake_downloads(monkeypatch, tmp_path)
    runtimes.ensure("llama", "cuda")
    assert sorted(p.name for p in runtimes.cache().iterdir()) == ["llama-cpu", "llama-cuda"]


def test_an_archive_without_the_program_is_not_installed(monkeypatch, tmp_path):
    fake_downloads(monkeypatch, tmp_path, files=("readme.txt",))
    with pytest.raises(RuntimeError, match="llama-server.exe is missing"):
        runtimes.ensure("llama", "cpu")
    assert runtimes.exe("llama", "cpu") is None and not runtimes.folder("llama", "cpu").exists()


def test_vulkan_needs_a_device_listing(monkeypatch, tmp_path):
    # the loader (vulkan-1.dll) alone proves nothing: without vulkaninfo's device list, say no
    system32 = tmp_path / "System32"
    system32.mkdir()
    (system32 / "vulkan-1.dll").write_bytes(b"x")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.setattr(runtimes.shutil, "which", lambda name: None)
    assert runtimes.vulkan.__wrapped__() is False
    (system32 / "vulkaninfo.exe").write_bytes(b"x")
    monkeypatch.setattr(runtimes, "probe_run",
                        lambda *a, **k: type("R", (), {"stdout": "deviceName: Some GPU"})())
    assert runtimes.vulkan.__wrapped__() is True


def test_backend_override_never_implicitly_enables_vulkan(monkeypatch):
    monkeypatch.setattr(runtimes, "nvidia", lambda: False)
    monkeypatch.setattr(runtimes, "vulkan", lambda: True)
    monkeypatch.delenv("PIANPIAN_ACCEL", raising=False)
    assert runtimes.backend_for("llama") == "cpu"
    monkeypatch.setenv("PIANPIAN_ACCEL", "cpu")
    assert runtimes.backend_for("llama") == "cpu"
    monkeypatch.setenv("PIANPIAN_ACCEL", "vulkan")
    assert runtimes.backend_for("llama") == "vulkan"


def test_detecting_nvidia_does_not_enable_cuda_implicitly(monkeypatch):
    monkeypatch.setattr(runtimes, "nvidia", lambda: True)
    monkeypatch.setattr(runtimes, "vulkan", lambda: True)
    monkeypatch.delenv("PIANPIAN_ACCEL", raising=False)
    assert runtimes.detect()["backend"] == "cuda"
    assert runtimes.backend_for("llama") == "cpu"
    monkeypatch.setenv("PIANPIAN_ACCEL", "cuda")
    assert runtimes.backend_for("llama") == "cuda"


@pytest.mark.parametrize("probe", [True, False])
def test_status_lists_only_translation_runtime(monkeypatch, tmp_path, probe):
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path))
    monkeypatch.setenv("PIANPIAN_ACCEL", "cpu")
    s = runtimes.status(probe=probe)
    assert set(s["tools"]) == {"llama"}
    assert s["size"] > 0 and s["label"] and not s["ready"]


def test_explicit_vulkan_applies_only_to_translation(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path))
    monkeypatch.setenv("PIANPIAN_ACCEL", "vulkan")
    s = runtimes.status()
    assert set(s["tools"]) == {"llama"}
    assert s["tools"]["llama"]["backend"] == "vulkan"
    assert "llama.cpp: Vulkan GPU" in s["label"]


def test_windows_plan_offers_the_gpu_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_HOME", str(tmp_path))
    monkeypatch.setenv("PIANPIAN_MODELS", str(tmp_path / "models"))  # Setup.plan() writes os.environ; monkeypatch restores it
    import engine
    e = importlib.reload(engine)
    monkeypatch.setattr(e, "WINDOWS", True)
    monkeypatch.setattr(e.runtimes.platform_backend, "NAME", "win32")
    monkeypatch.setattr(e.models, "status", lambda: [])
    monkeypatch.setattr(e.runtimes, "status", lambda **kwargs: {"backend": "cuda", "label": "gpu", "size": 10, "ready": False, "tools": {}})
    e.STATE.update(engine=True, current=True)
    plan = e.SETUP.plan()
    assert plan["runtime"]["label"] == "gpu" and plan["needed"]
    monkeypatch.setattr(e.runtimes, "status", lambda **kwargs: {"backend": "cuda", "label": "gpu", "size": 10, "ready": True, "tools": {}})
    assert not e.SETUP.plan()["needed"]


def test_windows_plan_never_probes_gpu(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_HOME", str(tmp_path))
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.delenv("PIANPIAN_ACCEL", raising=False)
    import engine
    e = importlib.reload(engine)
    monkeypatch.setattr(e, "WINDOWS", True)
    monkeypatch.setattr(e.runtimes.platform_backend, "NAME", "win32")
    monkeypatch.setattr(e.models, "status", lambda: [])
    monkeypatch.setattr(e.runtimes, "backend_for", lambda tool: (_ for _ in ()).throw(AssertionError("GPU probe ran")))
    e.STATE.update(engine=True, current=True)
    plan = e.SETUP.plan()
    assert plan["runtime"]["backend"] == "cpu" and not plan["needed"]


@pytest.mark.parametrize("version, returncode, supported", [("551.61", 0, True), ("591.74", 0, True),
                                                          ("550.10", 0, False), ("", 0, False),
                                                          ("N/A", 0, False), ("591.74", 1, False)])
def test_nvidia_probe_checks_the_driver_not_the_toolkit(monkeypatch, tmp_path, version, returncode, supported):
    import subprocess
    exe = tmp_path / "nvidia-smi.exe"
    exe.touch()
    monkeypatch.setattr(runtimes.shutil, "which", lambda name: str(exe))
    def query(cmd, **kwargs):
        assert cmd[1:] == ["--query-gpu=driver_version", "--format=csv,noheader"]
        return subprocess.CompletedProcess(cmd, returncode, stdout=version)
    monkeypatch.setattr(runtimes, "probe_run", query)
    assert runtimes.nvidia.__wrapped__() is supported


def test_runtime_size_counts_only_missing_selected_archives(monkeypatch, tmp_path):
    fake_downloads(monkeypatch, tmp_path)
    monkeypatch.setenv("PIANPIAN_ACCEL", "cpu")
    assert runtimes.status()["size"] == 24_172_821
    runtimes.ensure("llama")
    assert runtimes.status()["size"] == 0
    assert runtimes.status(which=["llama"])["ready"]
    assert runtimes.status(which=["llama"])["size"] == 0
    assert runtimes.status(which=[])["ready"] and runtimes.status(which=[])["size"] == 0


def test_uppercase_acceleration_has_the_same_plan_and_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path))
    monkeypatch.setenv("PIANPIAN_ACCEL", "CUDA")
    assert runtimes.status()["backend"] == runtimes.backend_for("llama") == "cuda"
    assert runtimes.status()["size"] == 688_046_286


@pytest.mark.parametrize("gpu", ["cuda", "vulkan"])
def test_gpu_setup_includes_cpu_word_links_and_then_works_offline(monkeypatch, tmp_path, gpu):
    seen = fake_downloads(monkeypatch, tmp_path)
    monkeypatch.setenv("PIANPIAN_ACCEL", gpu)
    cpu_bytes = sum(a["size"] for a in runtimes.assets("llama", "cpu"))
    gpu_bytes = sum(a["size"] for a in runtimes.assets("llama", gpu))
    assert runtimes.status()["size"] == cpu_bytes + gpu_bytes
    # An older GPU-only installation must reopen setup for the missing alignment dependency.
    runtimes._install("llama", gpu)
    assert not runtimes.status()["ready"] and runtimes.status()["size"] == cpu_bytes
    runtimes.ensure("llama")
    assert runtimes.status()["ready"] and runtimes.status()["size"] == 0
    assert any("cpu-x64" in urls[0] for urls in seen)
    monkeypatch.setattr(runtimes.models, "download", lambda *a: pytest.fail("offline job attempted a download"))
    assert Path(runtimes.ensure("llama", "cpu")).is_file()  # align_srt's exact dependency
    assert Path(runtimes.ensure("llama", gpu)).is_file()    # translation and CPU fallback are both cached
