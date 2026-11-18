"""Release signing fails closed; Apple commands are simulated, not a real notarization test."""
import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_app as build  # noqa: E402

IDENTITY = "A" * 40
NAME = "Developer ID Application: Example (TESTTEAM01)"


def test_failed_command_keeps_captured_apple_diagnostics(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args, output='{"status":"Invalid"}', stderr="Apple diagnostic")

    monkeypatch.setattr(build.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        build.run("xcrun", "notarytool", "submit", capture_output=True, text=True)
    error = capsys.readouterr().err
    assert "Invalid" in error and "Apple diagnostic" in error


@pytest.mark.parametrize("requested", ["", IDENTITY, NAME])
def test_selects_developer_id_not_development_certificate(monkeypatch, requested):
    monkeypatch.setenv("PIANPIAN_SIGNING_IDENTITY", requested)
    output = f'1) {"B" * 40} "Apple Development: Example"\n2) {IDENTITY} "{NAME}"\n'
    monkeypatch.setattr(build, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout=output))
    assert build.signing_identity() == IDENTITY


@pytest.mark.parametrize("output,requested", [
    ("0 valid identities found", ""),
    (f'1) {IDENTITY} "{NAME}"\n2) {"B" * 40} "Developer ID Application: Other"', ""),
    (f'1) {IDENTITY} "{NAME}"', "missing identity"),
])
def test_no_fallback_to_adhoc_or_arbitrary_identity(monkeypatch, output, requested):
    monkeypatch.setenv("PIANPIAN_SIGNING_IDENTITY", requested)
    monkeypatch.setattr(build, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout=output))
    with pytest.raises(SystemExit, match="Developer ID Application"):
        build.signing_identity()


@pytest.mark.parametrize("status", ["Invalid", "In Progress", None])
def test_never_staples_an_unaccepted_submission(monkeypatch, status):
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"status": status, "id": "submission-id"}))

    monkeypatch.setattr(build, "run", run)
    with pytest.raises(SystemExit, match="not accepted"):
        build.notarize(Path("app.zip"), Path("app.app"), "test-profile")
    assert not any("stapler" in args for args in calls)
    assert any("log" in args and "submission-id" in args for args in calls)


def test_missing_credentials_preserves_previous_build(monkeypatch, tmp_path):
    app = tmp_path / "Pianpian.app"
    app.mkdir()
    marker = app / "previous-build"
    marker.write_text("keep")
    monkeypatch.setattr(build, "APP", app)
    monkeypatch.setattr(build.sys, "platform", "darwin")
    monkeypatch.setattr(build.shutil, "which", lambda _: "/path/to/uv")
    monkeypatch.setattr(build, "signing_identity", lambda: IDENTITY)

    def unavailable(*args, **kwargs):
        raise subprocess.CalledProcessError(69, args)

    monkeypatch.setattr(build, "run", unavailable)
    with pytest.raises(subprocess.CalledProcessError):
        build.main(signed=True)
    assert marker.read_text() == "keep"


@pytest.mark.parametrize("signed", [True, False])
def test_release_artifacts_include_stapled_app(monkeypatch, tmp_path, signed):
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build, "BUILD", tmp_path / "build")
    monkeypatch.setattr(build, "APP", build.DIST / "Pianpian.app")
    monkeypatch.setattr(build, "version", lambda: "0.1.0")
    monkeypatch.setattr(build.sys, "platform", "darwin")
    monkeypatch.setattr(build.shutil, "which", lambda _: "/path/to/uv")
    monkeypatch.setattr(build, "signing_identity", lambda: IDENTITY)
    monkeypatch.setattr(build, "icon", lambda _: Path("icon.icns"))
    (tmp_path / "pipeline").mkdir()
    calls = []

    def run(*args, **kwargs):
        args = tuple(map(str, args))
        calls.append(args)
        if "pyinstaller" in args:
            (build.APP / "Contents").mkdir(parents=True)
            (build.APP / "Contents" / "Info.plist").write_bytes(plistlib.dumps({}))
        if args[0] == "ditto":
            if signed and "notarization" not in args[-1]:
                assert "stapled" in (build.APP / "Contents" / "Info.plist").read_text()
            Path(args[-1]).write_text("zip")
        if "stapler" in args and "staple" in args and args[-1] == str(build.APP):
            info = build.APP / "Contents" / "Info.plist"
            info.write_text(info.read_text() + "<!-- stapled -->")
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"status": "Accepted", "id": "submission-id"}))

    def make_dmg():
        if signed:
            assert "stapled" in (build.APP / "Contents" / "Info.plist").read_text()
        dmg = build.DIST / "Pianpian-macOS.dmg"
        dmg.write_text("dmg")
        return dmg

    monkeypatch.setattr(build, "run", run)
    monkeypatch.setattr(build, "make_dmg", make_dmg)
    build.main(signed=signed)
    pyinstaller = next(args for args in calls if "pyinstaller" in args)
    assert ("--codesign-identity" in pyinstaller) == signed
    signing = [args for args in calls if args[:2] == ("codesign", "--force")]
    if signed:
        assert all("--timestamp" in args and IDENTITY in args and "--deep" not in args for args in signing)
        assert "--options" in signing[0] and "runtime" in signing[0]
        assert len([args for args in calls if "submit" in args]) == 2
        assert len([args for args in calls if args[:3] == ("xcrun", "stapler", "validate")]) == 2
    else:
        assert not any("notarytool" in args for args in calls)
        assert signing == [("codesign", "--force", "--deep", "--sign", "-", str(build.APP))]
