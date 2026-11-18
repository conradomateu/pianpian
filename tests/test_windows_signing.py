"""Fail-closed packaging checks; Windows trust is exercised separately on the Windows runner."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_app_windows as bw  # noqa: E402
import windows_signing as ws  # noqa: E402


@pytest.fixture
def payload(monkeypatch, tmp_path):
    monkeypatch.setattr(ws, "ROOT", tmp_path)
    monkeypatch.setattr(ws, "APP", tmp_path / "dist/Pianpian")
    monkeypatch.setattr(ws, "WORK", tmp_path / "scratch/windows-signing")
    for name in (*ws.OWN, "_internal/python312.dll", "_internal/uv.exe", "assets/player.js"):
        path = ws.APP / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"original bytes including any upstream signature")
    cache = tmp_path / "build/windows-uninstaller"
    cache.mkdir(parents=True)
    (cache / "uninst-fixture.e32").write_bytes(b"uninstaller")
    ws.prepare()
    shutil.copytree(ws.WORK / "unsigned", ws.WORK / "signed")
    return tmp_path


def test_apply_only_overwrites_own_files_and_uninstaller(payload):
    for file in (ws.WORK / "signed").iterdir():
        file.write_bytes(b"signed fixture")
    ws.apply()
    assert all((ws.APP / p).read_bytes() == b"signed fixture" for p in ws.OWN)
    assert ws.uninstaller().read_bytes() == b"signed fixture"
    ws.preserve()


@pytest.mark.parametrize("name", ["_internal/uv.exe", "_internal/python312.dll", "assets/player.js"])
def test_any_third_party_or_data_mutation_blocks_packaging(payload, name):
    (ws.APP / name).write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="outside Pianpian"):
        ws.apply()


def test_missing_or_extra_provider_output_is_rejected(payload):
    (ws.WORK / "signed/Pianpian.exe").unlink()
    with pytest.raises(RuntimeError, match="allowlist"):
        ws.apply()
    shutil.copyfile(ws.WORK / "unsigned/Pianpian.exe", ws.WORK / "signed/Pianpian.exe")
    (ws.WORK / "signed/unexpected.exe").write_bytes(b"unrelated")
    with pytest.raises(RuntimeError, match="allowlist"):
        ws.apply()


def test_new_own_binary_requires_allowlist_review(payload):
    (ws.APP / "pianpian-new.exe").write_bytes(b"new")
    with pytest.raises(RuntimeError, match="allowlist"):
        ws.prepare()


def test_zip_and_install_must_preserve_exact_payload(payload, monkeypatch):
    ws.apply()
    monkeypatch.setattr(bw, "DIST", payload / "dist")
    bw.zip_app()
    installed = payload / "installed"
    shutil.copytree(ws.APP, installed)
    (installed / "unins000.exe").write_bytes(b"uninstaller")
    ws.verify_package(installed)
    (installed / "_internal/uv.exe").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="Installer did not preserve"):
        ws.verify_package(installed)
    (ws.APP / "Pianpian.exe").write_bytes(b"replaced after zip")
    with pytest.raises(RuntimeError, match="ZIP"):
        ws.verify_package()


def test_inno_preparation_accepts_only_the_expected_signature_boundary(monkeypatch, tmp_path):
    monkeypatch.setattr(bw, "UNINSTALLER", tmp_path / "uninstaller")
    monkeypatch.setattr(bw.shutil, "which", lambda _: "ISCC.exe")
    def compile(args, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL
        (bw.UNINSTALLER / "uninst-fixture.e32").write_bytes(b"PE")
        return subprocess.CompletedProcess(args, 1, "please attach your digital signature")
    monkeypatch.setattr(bw.subprocess, "run", compile)
    assert bw.installer(prepare=True).name == "uninst-fixture.e32"
    monkeypatch.setattr(bw.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "unrelated failure"))
    with pytest.raises(RuntimeError, match="expected uninstaller-signing boundary"):
        bw.installer(prepare=True)


def test_signpath_configurations_only_include_our_outputs():
    import xml.etree.ElementTree as ET
    root = Path(__file__).resolve().parents[1]
    ns = {"s": "http://signpath.io/artifact-configuration/v1"}
    for config, expected in [("windows-executables", {Path(p).name for p in ws.OWN} | {"uninstaller.exe"}),
                             ("windows-installer", {"Pianpian-Windows-Setup.exe"})]:
        tree = ET.parse(root / f"tools/windows/{config}.xml")
        files = tree.findall(".//s:pe-file", ns)
        assert {f.attrib["path"] for f in files} == expected
        assert all(f.attrib["product-name"] == "Pianpian" and f.attrib["product-version"] == "${version}" for f in files)
        assert all(f.find("s:authenticode-sign", ns).attrib["hash-algorithm"] == "sha256" for f in files)
    config = json.loads((root / "release-please-config.json").read_text())
    assert config["packages"]["."]["draft"] is True
    assert config["packages"]["."]["force-tag-creation"] is True
