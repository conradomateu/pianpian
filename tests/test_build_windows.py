"""The Windows build's own logic (tools/build_app_windows.py) and launcher.py's mutex, on any OS:
PyInstaller, Inno Setup and the Windows API are stubbed, so these say nothing about a real Windows build."""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import build_app_windows as bw  # noqa: E402


def test_pyinstaller_ships_the_logo_only_and_pins_its_tools(monkeypatch, tmp_path):
    calls = []
    def build_speech(output):
        assert output.name == "pianpian-sensevoice.exe"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"native helper")
        for name in ("sensevoice-NOTICES.txt", "build-manifest.json"):
            output.with_name(name).write_text("included")
        return output
    def build_alignment(output):
        output.parent.mkdir(parents=True)
        output.write_bytes(b"alignment helper")
        for name in ("alignment-NOTICES.txt", "alignment-build-manifest.json"):
            output.with_name(name).write_text("included")
        return output
    monkeypatch.setitem(sys.modules, "build_sensevoice", SimpleNamespace(build=build_speech))
    monkeypatch.setitem(sys.modules, "build_alignment", SimpleNamespace(build=build_alignment))
    monkeypatch.setattr(bw, "STAGE", tmp_path / "stage")
    monkeypatch.setattr(bw, "uv_exe", lambda: Path("uv.exe"))
    monkeypatch.setattr(bw, "DIST", tmp_path / "dist")
    def run(*cmd, **kw):
        calls.append([str(c) for c in cmd])
        if "pyinstaller" in cmd:
            destination = bw.DIST / "Pianpian/_internal/pipeline/bin"
            destination.mkdir(parents=True)
            for path in (bw.STAGE / "crt").iterdir():
                (destination / path.name).write_bytes(path.read_bytes())
    monkeypatch.setattr(bw, "run", run)
    from test_windows_crt import bundle
    monkeypatch.setenv("PIANPIAN_VC_REDIST_DIR", str(bundle(tmp_path / "redist")))
    bw.pyinstaller(debug_console=False)
    [cmd, smoke, align_smoke] = calls
    assert "--noupx" in cmd
    assert {f"{bw.STAGE / 'crt' / name};pipeline/bin" for name in bw.windows_crt.NAMES} <= set(cmd)
    assert cmd[:4] == ["uv.exe", "run", "--isolated", "--no-project"]
    assert {bw.PYINSTALLER, bw.PYWEBVIEW} <= set(cmd) and "==" in bw.PYINSTALLER and "==" in bw.PYWEBVIEW
    datas = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--add-data"]
    design = [d for d in datas if ";design" in d]
    assert design == [f"{ROOT / 'design' / 'icons' / '20-pianpian-watermelon.svg'};design/icons"]
    assert "links" not in cmd                                 # pipeline/ ships as data, not as hidden imports
    assert "ctypes" in [cmd[i + 1] for i, c in enumerate(cmd) if c == "--hidden-import"]
    assert (tmp_path / "stage" / "stage" / "pipeline" / "links.py").is_file()
    assert not (tmp_path / "stage" / "stage" / "pipeline" / "benchmark-mandarin.wav").exists()
    assert f"{tmp_path / 'stage' / 'speech' / 'pianpian-sensevoice.exe'};pipeline/bin" in cmd
    assert {f"{tmp_path / 'stage' / 'speech' / name};pipeline/bin" for name in
            ("sensevoice-NOTICES.txt", "build-manifest.json")} <= set(datas)
    assert f"{tmp_path / 'stage' / 'alignment' / 'pianpian-align.exe'};pipeline/bin" in cmd
    assert align_smoke[-1] == "--help" and align_smoke[0].endswith("pianpian-align.exe")
    assert smoke == [str(bw.DIST / "Pianpian" / "_internal" / "pipeline" / "bin" / "pianpian-sensevoice.exe"), "--help"]


def test_an_old_installer_is_neither_kept_nor_reported(monkeypatch, tmp_path, capsys):
    dist = tmp_path / "dist"
    (dist / "Pianpian").mkdir(parents=True)
    (dist / "Pianpian-Windows-Setup.exe").write_text("from an older build")
    monkeypatch.setattr(bw, "ROOT", tmp_path)
    monkeypatch.setattr(bw, "DIST", dist)
    monkeypatch.setattr(bw, "BUILD", tmp_path / "build")
    monkeypatch.setattr(bw, "SETUP", dist / "Pianpian-Windows-Setup.exe")
    monkeypatch.setattr(bw.sys, "platform", "win32")
    monkeypatch.setattr(bw, "pyinstaller", lambda debug: (dist / "Pianpian" / "Pianpian.exe").write_text("exe"))
    monkeypatch.setattr(bw, "installer", lambda: (_ for _ in ()).throw(AssertionError("installer ran")))
    monkeypatch.setattr(bw.sys, "argv", ["build_app_windows.py", "--no-installer"])
    bw.main()
    out = capsys.readouterr().out
    assert not (dist / "Pianpian-Windows-Setup.exe").exists()
    assert "Setup" not in out and "Pianpian.exe" in out and "Pianpian-Windows.zip" in out


def test_normal_windows_build_requires_inno_setup(monkeypatch, tmp_path):
    monkeypatch.setattr(bw.shutil, "which", lambda name: None)
    for name in ("LOCALAPPDATA", "ProgramFiles(x86)", "ProgramFiles"):
        monkeypatch.setenv(name, str(tmp_path))
    try:
        bw.installer()
    except RuntimeError as e:
        assert "Inno Setup 6 is required" in str(e) and "--no-installer" in str(e)
    else:
        raise AssertionError("a build without the installer would make check-windows green with only the ZIP")


def _launcher(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_HOME", str(tmp_path))
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace())
    import launcher
    return launcher


def _fake_ctypes(last_error):
    made = []
    kernel32 = SimpleNamespace(CreateMutexW=lambda attrs, owner, name: made.append(name) or 42)
    return made, SimpleNamespace(WinDLL=lambda name, use_last_error: kernel32, get_last_error=lambda: last_error)


def test_mutex_only_in_the_installed_windows_app(monkeypatch, tmp_path):
    launcher = _launcher(monkeypatch, tmp_path)
    for windows, frozen in ((False, False), (False, True), (True, False)):
        made, fake = _fake_ctypes(0)
        monkeypatch.setitem(sys.modules, "ctypes", fake)
        monkeypatch.setattr(launcher.engine, "WINDOWS", windows)
        monkeypatch.setattr(launcher.engine, "FROZEN", frozen)
        assert launcher.first_instance() and made == []


def test_a_second_windows_app_does_not_start(monkeypatch, tmp_path):
    launcher = _launcher(monkeypatch, tmp_path)
    monkeypatch.setattr(launcher.engine, "WINDOWS", True)
    monkeypatch.setattr(launcher.engine, "FROZEN", True)
    for last_error, first in ((0, True), (183, False)):
        made, fake = _fake_ctypes(last_error)
        monkeypatch.setitem(sys.modules, "ctypes", fake)
        assert launcher.first_instance() is first and made == ["PianpianApp"] and launcher._mutex == 42
    monkeypatch.setattr(launcher, "serve", lambda: (_ for _ in ()).throw(AssertionError("second server")))
    launcher.main()                                           # returns quietly, no server, no window
