"""Bundle wiring only: compilers, PyInstaller and codesign are mocked, not native platform validation."""
import plistlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_app as ba  # noqa: E402


def test_packaging_rejects_a_helper_without_upstream_notices(monkeypatch, tmp_path):
    def incomplete(output):
        output.write_bytes(b"executable")
        return output
    monkeypatch.setitem(sys.modules, "build_sensevoice", SimpleNamespace(build=incomplete))
    with pytest.raises(RuntimeError, match="sensevoice-NOTICES.txt"):
        ba.speech_payload(tmp_path)


def test_mac_bundle_collects_native_binary_notices_and_checks_launch(monkeypatch, tmp_path):
    calls = []
    app = tmp_path / "dist" / "Pianpian.app"

    def build(output):
        assert output.name == "pianpian-sensevoice"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"native helper")
        for name in ("sensevoice-NOTICES.txt", "build-manifest.json"):
            output.with_name(name).write_text("included")
        return output

    def run(*args, **kwargs):
        cmd = [str(arg) for arg in args]
        calls.append(cmd)
        if "pyinstaller" in cmd:
            (app / "Contents").mkdir(parents=True)
            (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({}))
            binaries = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--add-binary"]
            assert any(arg.endswith("/pianpian-sensevoice:pipeline/bin") for arg in binaries)
            assert any(arg.endswith("/pianpian-align:pipeline/bin") for arg in binaries)
            data = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--add-data"]
            for name in ("sensevoice-NOTICES.txt", "build-manifest.json"):
                source = next(arg.rsplit(":", 1)[0] for arg in data if arg.endswith(f"/{name}:pipeline/bin"))
                assert Path(source).is_file()
        if cmd[0] == "ditto":
            Path(cmd[-1]).write_bytes(b"zip")

    def dmg():
        path = app.parent / "Pianpian-macOS.dmg"
        path.write_bytes(b"dmg")
        return path

    def build_alignment(output):
        output.parent.mkdir(parents=True)
        output.write_bytes(b"alignment helper")
        for name in ("alignment-NOTICES.txt", "alignment-build-manifest.json"):
            output.with_name(name).write_text("included")
        return output

    monkeypatch.setitem(sys.modules, "build_sensevoice", SimpleNamespace(build=build))
    monkeypatch.setitem(sys.modules, "build_alignment", SimpleNamespace(build=build_alignment))
    monkeypatch.setattr(ba, "APP", app)
    monkeypatch.setattr(ba, "DIST", app.parent)
    monkeypatch.setattr(ba, "BUILD", tmp_path / "build")
    monkeypatch.setattr(ba, "ROOT", tmp_path)
    # Only source files used by staging are needed; there is no model/runtime download in this test.
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline" / "study.py").write_text("# pipeline")
    monkeypatch.setattr(ba, "version", lambda: "0.2.0")
    monkeypatch.setattr(ba.sys, "platform", "darwin")
    monkeypatch.setattr(ba.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(ba, "icon", lambda path: path / "icon.icns")
    monkeypatch.setattr(ba, "run", run)
    monkeypatch.setattr(ba, "make_dmg", dmg)
    ba.main()
    smoke = [str(app / "Contents" / "Resources" / "pipeline" / "bin" / "pianpian-sensevoice"), "--help"]
    assert smoke in calls
    assert calls.index(smoke) > next(i for i, cmd in enumerate(calls) if cmd[:2] == ["codesign", "--verify"])


def test_windows_speech_packaging_requires_both_cpu_variants(monkeypatch, tmp_path):
    def build(output):
        output.write_bytes(b"baseline")
        for name in ("sensevoice-NOTICES.txt", "build-manifest.json"):
            output.with_name(name).write_text("included")
        return output
    monkeypatch.setitem(sys.modules, "build_sensevoice", SimpleNamespace(build=build))
    with pytest.raises(RuntimeError, match="pianpian-sensevoice-avx2.exe"):
        ba.speech_payload(tmp_path, windows=True)
    (tmp_path / "pianpian-sensevoice-avx2.exe").write_bytes(b"optimized")
    helper, data = ba.speech_payload(tmp_path, windows=True)
    assert helper.name == "pianpian-sensevoice.exe" and len(data) == 2


def test_alignment_packaging_rejects_missing_notices(monkeypatch, tmp_path):
    def incomplete(output):
        output.write_bytes(b"helper")
        return output
    monkeypatch.setitem(sys.modules, "build_alignment", SimpleNamespace(build=incomplete))
    with pytest.raises(RuntimeError, match="alignment-NOTICES.txt"):
        ba.alignment_payload(tmp_path)


def test_alignment_header_abi_must_match_downloaded_runtime(monkeypatch):
    import build_alignment
    with pytest.raises(RuntimeError, match="different ABI"):
        build_alignment.check_runtime_pin({"release": "b-obsolete"})
    build_alignment.check_runtime_pin({"release": build_alignment.runtimes.RELEASES["llama"]})
