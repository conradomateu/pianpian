"""App-local CRT collection and repair; filesystem simulations, not Windows execution."""
import hashlib
import json
from pathlib import Path
import struct
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pipeline")]
import runtimes  # noqa: E402
import windows_crt  # noqa: E402


def pe():
    data = bytearray(128)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 80)
    data[80:86] = b"PE\x00\x00\x64\x86"
    return bytes(data)


def bundle(folder):
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in windows_crt.NAMES:
        data = pe() + name.encode()
        (folder / name).write_bytes(data)
        files[name] = {"sha256": hashlib.sha256(data).hexdigest()}
    (folder / "msvc-manifest.json").write_text(json.dumps({"files": files}))
    return folder


def test_collects_only_explicit_x64_redist_and_preserves_hashes(monkeypatch, tmp_path):
    src = bundle(tmp_path / "VS" / "x64" / "Microsoft.VC145.CRT")
    (src / "Redist.txt").write_text("original Microsoft notice fixture")
    monkeypatch.setenv("PIANPIAN_VC_REDIST_DIR", str(src))
    output = tmp_path / "bundle"
    files = windows_crt.collect(output)
    assert {p.name for p in files} == {*windows_crt.NAMES, "msvc-manifest.json", "msvc-NOTICES.txt", "msvc-Redist.txt"}
    manifest = json.loads((output / "msvc-manifest.json").read_text())
    assert manifest["source"] == str(src)
    for name in windows_crt.NAMES:
        assert (output / name).read_bytes() == (src / name).read_bytes()
        assert manifest["files"][name]["sha256"] == hashlib.sha256((src / name).read_bytes()).hexdigest()
    assert (output / "msvc-Redist.txt").read_text() == "original Microsoft notice fixture"


def test_missing_or_wrong_architecture_redist_fails_build(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_VC_REDIST_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="Missing MSVC"):
        windows_crt.collect(tmp_path / "out")
    bundle(tmp_path)
    (tmp_path / windows_crt.NAMES[0]).write_bytes(b"wrong architecture")
    with pytest.raises(RuntimeError, match="x64 PE"):
        windows_crt.collect(tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_discovers_only_visual_studio_redist(monkeypatch, tmp_path):
    vswhere = tmp_path / "Microsoft Visual Studio/Installer/vswhere.exe"
    vswhere.parent.mkdir(parents=True)
    vswhere.touch()
    vs = tmp_path / "VS"
    old = bundle(vs / "VC/Redist/MSVC/14.9.1/x64/Microsoft.VC143.CRT")
    new = bundle(vs / "VC/Redist/MSVC/14.50.1/x64/Microsoft.VC145.CRT")
    monkeypatch.delenv("PIANPIAN_VC_REDIST_DIR", raising=False)
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))
    monkeypatch.setattr(windows_crt.subprocess, "check_output", lambda *args, **kw: str(vs) + "\n")
    assert windows_crt.source() == new and windows_crt.source() != old


@pytest.mark.parametrize("backend", ["cpu", "cuda", "vulkan"])
def test_cached_runtime_repairs_crt_offline_including_cpu_links(monkeypatch, tmp_path, backend):
    monkeypatch.setattr(runtimes.platform_backend, "NAME", "win32")
    monkeypatch.setattr(runtimes, "CRT_DIR", bundle(tmp_path / "bundle"))
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.setattr(runtimes, "_install", lambda *args: pytest.fail("cached archives must not download"))
    selected = {"cpu", backend}
    for kind in selected:
        folder = runtimes.folder("llama", kind)
        folder.mkdir(parents=True)
        (folder / "llama-server.exe").write_bytes(b"cached pinned exe")
        (folder / ".complete").write_text(json.dumps(runtimes.stamp("llama", kind)))
    before = runtimes.status(backend=backend)
    assert before["size"] == 0 and not before["ready"]
    runtimes.ensure("llama", backend)
    assert runtimes.status(backend=backend)["ready"]
    for kind in selected:
        for name in windows_crt.NAMES:
            assert (runtimes.folder("llama", kind) / name).read_bytes() == (runtimes.CRT_DIR / name).read_bytes()
    # An app update refreshes CRT without invalidating the unchanged pinned runtime archive.
    name = windows_crt.NAMES[0]
    data = (runtimes.CRT_DIR / name).read_bytes() + b"updated"
    (runtimes.CRT_DIR / name).write_bytes(data)
    manifest = json.loads((runtimes.CRT_DIR / "msvc-manifest.json").read_text())
    manifest["files"][name]["sha256"] = hashlib.sha256(data).hexdigest()
    (runtimes.CRT_DIR / "msvc-manifest.json").write_text(json.dumps(manifest))
    assert not runtimes.status(backend=backend)["ready"] and runtimes.status(backend=backend)["size"] == 0
    runtimes.ensure("llama", backend)
    assert runtimes.status(backend=backend)["ready"]
    (runtimes.CRT_DIR / name).write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="missing or damaged"):
        runtimes.ensure("llama", backend)


def test_mac_does_not_require_or_read_crt(monkeypatch, tmp_path):
    monkeypatch.setattr(runtimes.platform_backend, "NAME", "darwin")
    monkeypatch.setattr(runtimes, "_crt_files", lambda: pytest.fail("Mac read Windows CRT"))
    runtimes._sync_crt(tmp_path / "llama-server")
    assert runtimes._crt_ready(tmp_path / "llama-server")


def test_missing_bundled_crt_fails_before_runtime_download(monkeypatch, tmp_path):
    monkeypatch.setattr(runtimes.platform_backend, "NAME", "win32")
    monkeypatch.setattr(runtimes, "CRT_DIR", tmp_path / "missing")
    monkeypatch.setattr(runtimes, "_install", lambda *args: pytest.fail("download before checking bundled CRT"))
    with pytest.raises(RuntimeError, match="missing or damaged"):
        runtimes.ensure("llama", "cpu")
