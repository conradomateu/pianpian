"""The source launcher uses its dependencies, and native-window jobs preserve Chinese paths."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_windows_app_uses_the_uv_environment_python(monkeypatch):
    import dev

    commands = []
    monkeypatch.setattr(dev, "WINDOWS", True)
    monkeypatch.setattr(dev.sys, "executable", "C:/global/python.exe")
    monkeypatch.setattr(dev, "run", lambda *cmd: commands.append(cmd))
    dev.app()
    assert commands == [(dev.UV, "run", "--group", "runtime", "--group", "desktop", "python", "launcher.py")]


def test_native_window_job_preserves_chinese_paths_without_main(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_HOME", str(tmp_path))
    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    import server

    folder = tmp_path / "中文视频"
    folder.mkdir()
    # Real child output: main() was never called, and even job overrides must obey the log encoding.
    code = "import sys; from pathlib import Path; assert sys.flags.utf8_mode; print('folder: ' + str(Path.cwd()))"
    job = server.Job("Chinese folder", [sys.executable, "-c", code], str(folder),
                     {"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"})
    jobs = iter([job])
    monkeypatch.setattr(server, "QUEUE", SimpleNamespace(get=lambda: next(jobs)))
    with pytest.raises(StopIteration):
        server.worker()
    assert job.state == "done", job.log
    assert job.video == folder.name
    assert "folder: " + str(folder) in job.log
