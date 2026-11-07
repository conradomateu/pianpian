"""Problem reports: the hints match real failures, and nothing personal survives redaction."""
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import report  # noqa: E402


def test_hints_for_known_failures():
    assert report.explain(["ERROR: [BiliBili] BV1: HTTP Error 412: Precondition Failed"])["code"] == "DL-BLOCKED"
    assert report.explain(["ERROR: [BiliBili] 1: Unable to download webpage: HTTP Error 412"])["code"] == "DL-BLOCKED"
    assert report.explain(["ERROR: [BiliBiliBangumi] 790639: No video formats found!"])["code"] == "DL-NOFORMATS"
    assert report.explain(["ERROR: This video requires login (大会员 only)"])["code"] == "DL-LOGIN"
    assert report.explain(["ERROR: Unsupported URL: https://example.com"])["code"] == "DL-UNSUPPORTED"
    assert report.explain(["OSError: [Errno 28] No space left on device"])["code"] == "DISK-FULL"
    assert report.explain(["FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'"])["code"] == "TOOL-MISSING"
    assert report.explain(["all good"]) is None


def test_a_failed_runtime_download_is_not_called_a_model_download():
    # the message a failed .zip download prints; MODEL-DOWNLOAD's "checksum does not match" would claim it otherwise
    log = ["  whisper-bin-x64.zip: checksum does not match the lock; deleted, trying the next source",
           "could not download the GPU runtime (whisper-bin-x64.zip): no source served whisper-bin-x64.zip; it resumes, try again"]
    assert report.explain(log)["code"] == "RUNTIME-DOWNLOAD"
    assert report.explain(["could not download model.safetensors (check the connection and try again: it resumes)"])["code"] == "MODEL-DOWNLOAD"


def test_the_last_failure_wins():
    log = ["urlopen error timed out", "retrying", "ERROR: Unsupported URL: x"]
    assert report.explain(log)["code"] == "DL-UNSUPPORTED"


def test_redact_removes_what_is_personal():
    home, lib = str(Path.home()), Path.home() / "Movies" / "mandarin"
    text = "\n".join([
        f"$ {home}/code/pianpian/.venv/bin/python study.py https://www.bilibili.com/video/BV1xx?spm=123&token=SECRET",
        f"folder: {lib}/BV1xx",
        "[00:01.840 --> 00:19.880] 现在这个地方,我们可以往左走",
        "Cookie: SESSDATA=abc123",
        "contact me at someone@example.com",
    ])
    out = report.redact(text, lib)
    assert home not in out and "SECRET" not in out and "BV1xx" not in out
    # the link keeps its shape (kind of page, parameter names) so a failing shape can be seen, never the video or values
    assert "https://www.bilibili.com/video/…?spm=…&token=…" in out
    assert "<library>/<video>" in out and "BV1xx" not in out
    assert "现在这个地方" not in out and "SESSDATA" not in out and "<email>" in out


def test_redact_covers_a_windows_library_path():
    lib = Path(r"C:\Users\someone\Videos\Pianpian")         # a PosixPath keeps the backslashes literal
    out = report.redact(rf"folder: {lib}\BV1xx\zh.srt failed", lib)
    assert "<library>/<video>" in out and "someone" not in out and "BV1xx" not in out


@pytest.mark.parametrize("timestamp", ["00:01.840", "00:00:01.840"])
def test_transcripts_do_not_reach_the_report_url(timestamp):
    details = report.redact(f"[{timestamp} --> 00:00:19.880] 私人会议内容\nRuntimeError: translation failed")
    url = report.issue_url("owner/repo", "Problem", "JOB-FAILED", details, "test")
    shared = parse_qs(urlparse(url).query)["details"][0]
    assert shared == "RuntimeError: translation failed"


@pytest.mark.parametrize("home", [PureWindowsPath("C:/Users/report user"), PurePosixPath("/Users/report user")])
@pytest.mark.parametrize("title", ["private lesson", "teacher's private lesson", 'a "private" lesson', '''teacher's "private" lesson'''])
def test_known_paths_are_redacted_in_errors_commands_and_report_urls(monkeypatch, home, title):
    monkeypatch.setattr(report.Path, "home", lambda: home)
    monkeypatch.setattr(report.getpass, "getuser", lambda: "report user")
    lib = home / "Videos" / "Study library"
    video = lib / title / "private recording.srt"
    text = "\n".join([
        f"folder: {video.parent}",
        f"{video}: failed",
        str(FileNotFoundError(2, "No such file or directory", str(video))),
        str(subprocess.CalledProcessError(1, [str(home / "engine" / "python"), str(video)])),
        "RuntimeError: translation failed",
    ])
    details = report.redact(text, lib)
    url = report.issue_url("owner/repo", "Problem", "JOB-FAILED", details, "test")
    shared = parse_qs(urlparse(url).query)["details"][0]
    assert shared == details
    for private in ("report user", "Study library", "teacher", "private", "lesson", "recording.srt"):
        assert private not in shared
    assert shared.count("<library>/<video>") == 4
    assert "~/engine/python" in shared.replace("\\\\", "/").replace("\\", "/")
    assert "No such file or directory" in shared and "RuntimeError: translation failed" in shared


def test_issue_url_fills_the_bug_form_and_stays_short():
    details = "summary\n" * 4 + "\n".join(f"log line {i} " + "x" * 80 for i in range(400))
    url = report.issue_url("owner/repo", "Problem", "NET", details, "MacBook")
    q = parse_qs(urlparse(url).query)
    assert len(url) < 7500 and q["template"] == ["bug.yml"] and q["code"] == ["NET"]
    assert q["details"][0].startswith("summary") and "log line 399" in q["details"][0]   # the summary and the newest lines stay


def test_redact_covers_other_ways_windows_writes_a_path(monkeypatch):
    # forward slashes (as_posix, repr), another letter case, file:/// links, 8.3 short names, another drive
    monkeypatch.setattr(report.engine, "WINDOWS", True)
    monkeypatch.setattr(report.Path, "home", lambda: PureWindowsPath(r"C:\Users\Wang Wei"))
    monkeypatch.setattr(report.getpass, "getuser", lambda: "Wang Wei")
    for lib in (PureWindowsPath(r"C:\Users\Wang Wei\Videos\Pianpian"), PureWindowsPath(r"D:\My Videos\Pianpian 学习")):
        video = lib / "王老师的私人课" / "source.mp4"
        text = "\n".join([
            repr(video), video.as_posix(), str(video).lower(), video.as_posix().upper(),
            video.as_uri(), "file:///" + video.as_posix().replace(" ", "%20"), "Input #0, from 'file:" + video.as_posix() + "':",
            r"C:\Users\WANGWE~1\AppData\Local\Pianpian\engine\python.exe", r"c:\users\wang wei\AppData\x.log",
        ])
        out = report.redact(text, lib)
        for private in ("Wang", "wang", "WANG", "王老师", "私人", "Pianpian 学习", "My Videos", "%20Wei"):
            assert private not in out, (lib, private, out)
        assert out.count("<library>/<video>") == 7 and "AppData" in out


def test_system_line_uses_the_engine_platform_check(monkeypatch):
    monkeypatch.setattr(report.engine, "WINDOWS", True)
    monkeypatch.setattr(report.platform, "platform", lambda: "Windows-11-10.0.26200-SP0")
    assert report.system().startswith("Windows-11")
