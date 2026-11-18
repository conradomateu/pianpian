"""Opt-in Mac release check: real downloads, developer commands blocked on PATH."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_engine import fresh


@pytest.mark.skipif(sys.platform != "darwin" or not os.environ.get("PIANPIAN_TEST_UV"),
                    reason="Mac release check requires PIANPIAN_TEST_UV pointing to bundled uv")
def test_fresh_mac_engine_without_developer_commands(monkeypatch, tmp_path):
    uv = str(Path(os.environ["PIANPIAN_TEST_UV"]).resolve())
    blocked = tmp_path / "blocked-tools"
    blocked.mkdir()
    marker = tmp_path / "developer-tool-invocations"
    for name in ("install_name_tool", "xcrun", "xcodebuild", "clang", "clang++", "gcc", "g++", "cc", "c++", "make"):
        tool = blocked / name
        tool.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$CLT_MARKER"\nexit 99\n')
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(blocked) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("CLT_MARKER", str(marker))
    monkeypatch.setenv("UV_PYTHON_CACHE_DIR", str(tmp_path / "python-downloads"))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    e = fresh(monkeypatch, tmp_path / "home")
    monkeypatch.setattr(e, "FROZEN", True)
    monkeypatch.setattr(e, "uv", lambda: uv)
    monkeypatch.setattr(e, "python", lambda: str(e.engine_python(e.engine_dir())))
    e.check()
    e.SETUP.start(str(tmp_path / "videos"), None, [])
    try:
        e.SETUP.thread.join(timeout=240)
        assert not e.SETUP.thread.is_alive(), list(e.SETUP.log)
        assert e.SETUP.state == "done", (e.SETUP.error, list(e.SETUP.log))
        assert not marker.exists(), marker.read_text()
        subprocess.run([e.python(), "-c", 'import pypinyin, zhconv, imageio_ffmpeg; '
                        'assert pypinyin.lazy_pinyin("你好") == ["ni", "hao"]; '
                        'assert zhconv.convert("學習", "zh-cn") == "学习"; '
                        'print(imageio_ffmpeg.get_ffmpeg_exe())'], check=True, timeout=30)
        assert not marker.exists(), marker.read_text()
    finally:
        if e.SETUP.thread.is_alive():
            e.stop_processes()
            e.SETUP.thread.join(timeout=10)
