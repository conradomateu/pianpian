"""Mac runtime download accounting, shared CPU fallback and safe archive extraction."""
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "pipeline")]
import runtimes  # noqa: E402


@pytest.fixture(autouse=True)
def mac_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(runtimes.platform_backend, "NAME", "darwin")
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.delenv("PIANPIAN_ACCEL", raising=False)


def test_metal_and_cpu_reuse_one_verified_download(monkeypatch):
    fetched = []

    def download(urls, target, size, sha256, label):
        fetched.append(target.name)
        assert size == 16244820 and sha256 == runtimes.MAC_ASSET["sha256"]
        with tarfile.open(target, "w:gz") as archive:
            exe = tarfile.TarInfo("bin/llama-server")
            exe.size, exe.mode = 4, 0o755
            archive.addfile(exe, io.BytesIO(b"fake"))

    monkeypatch.setattr(runtimes.models, "download", download)
    assert runtimes.backend_for("llama") == "metal"
    assert runtimes.available_backends() == ("metal", "cpu")
    assert runtimes.status()["size"] == 16244820
    metal = runtimes.ensure("llama")
    assert runtimes.ensure("llama", "cpu") == metal
    assert len(fetched) == 1
    if sys.platform != "win32":
        assert Path(metal).stat().st_mode & 0o111
    assert runtimes.status(backend="cpu")["size"] == runtimes.status(backend="metal")["size"] == 0
    stamp = json.loads((runtimes.folder("llama", "cpu") / ".complete").read_text())
    assert stamp == runtimes.stamp("llama", "metal")


@pytest.mark.parametrize("kind", ["path", "symlink"])
def test_mac_tar_rejects_paths_and_links_outside_destination(tmp_path, kind):
    path = tmp_path / "unsafe.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("../../escaped" if kind == "path" else "unsafe-link")
        if kind == "symlink":
            member.type, member.linkname = tarfile.SYMTYPE, "../../escaped"
        archive.addfile(member)
    with pytest.raises(tarfile.FilterError):
        runtimes.extract(path, tmp_path / "destination")
    assert not (tmp_path.parent / "escaped").exists()


def test_mac_rejects_windows_backends_without_downloading(monkeypatch):
    monkeypatch.setattr(runtimes.models, "download", lambda *args: pytest.fail("must not download"))
    with pytest.raises(ValueError, match="unsupported"):
        runtimes.ensure("llama", "cuda")
    monkeypatch.setenv("PIANPIAN_ACCEL", "cuda")
    assert runtimes.backend_for("llama") == "metal"
