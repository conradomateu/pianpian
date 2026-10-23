"""Problem reports: the hints match real failures, and nothing personal survives redaction."""
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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


def test_issue_url_fills_the_bug_form_and_stays_short():
    details = "summary\n" * 4 + "\n".join(f"log line {i} " + "x" * 80 for i in range(400))
    url = report.issue_url("owner/repo", "Problem", "NET", details, "MacBook")
    q = parse_qs(urlparse(url).query)
    assert len(url) < 7500 and q["template"] == ["bug.yml"] and q["code"] == ["NET"]
    assert q["details"][0].startswith("summary") and "log line 399" in q["details"][0]   # the summary and the newest lines stay
