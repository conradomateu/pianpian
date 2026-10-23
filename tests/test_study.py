"""The pipeline's retry rule: temporary failures are tried again, real ones are not."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "pipeline")]
import study  # noqa: E402


def test_what_counts_as_temporary():
    for text in ("ERROR: [BiliBili] x: Unable to download webpage: HTTP Error 412: Precondition Failed", "HTTP Error 503: Service Unavailable",
                 "HTTP Error 429: Too Many Requests", "The read operation timed out", "Connection reset by peer"):
        assert study.TRANSIENT.search(text), text
    for text in ("ERROR: Unsupported URL: https://example.com", "HTTP Error 404: Not Found", "Video unavailable", "No video formats found!",
                 "ERROR: [BiliBili] This video requires login"):
        assert not study.TRANSIENT.search(text), text


def test_retries_then_gives_up_and_never_retries_a_real_error(monkeypatch, capsys):
    monkeypatch.setattr(study.time, "sleep", lambda s: None)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "ERROR: HTTP Error 412: Precondition Failed")
    monkeypatch.setattr(study.subprocess, "run", fake_run)
    try:
        study.ytdlp_out(["yt-dlp", "x"])
        raise AssertionError("should have failed")
    except subprocess.CalledProcessError:
        pass
    assert len(calls) == study.TRIES and "trying again" in capsys.readouterr().out

    calls.clear()
    monkeypatch.setattr(study.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), subprocess.CompletedProcess(cmd, 1, "", "ERROR: Unsupported URL"))[1])
    try:
        study.ytdlp_out(["yt-dlp", "x"])
    except subprocess.CalledProcessError:
        pass
    assert len(calls) == 1                                       # an unsupported link is not going to get better


def test_succeeds_on_a_later_try(monkeypatch):
    monkeypatch.setattr(study.time, "sleep", lambda s: None)
    answers = [subprocess.CompletedProcess([], 1, "", "HTTP Error 412"), subprocess.CompletedProcess([], 0, "2008926\n", "")]
    monkeypatch.setattr(study.subprocess, "run", lambda cmd, **kw: answers.pop(0))
    assert study.ytdlp_out(["yt-dlp", "x"]).split()[0] == "2008926"


def test_streaming_retry_with_a_real_process(monkeypatch, tmp_path, capsys):
    """A stand-in for yt-dlp that answers 412 twice and then works: the output must reach the log live, and it must succeed."""
    monkeypatch.setattr(study.time, "sleep", lambda s: None)
    counter = tmp_path / "n"
    script = ("import pathlib,sys; f=pathlib.Path(sys.argv[1]); n=int(f.read_text()) if f.exists() else 0; f.write_text(str(n+1)); "
              "print('[download]  50.0% of 1MiB'); "
              "(print('ERROR: [BiliBili] x: Unable to download webpage: HTTP Error 412: Precondition Failed'), sys.exit(1)) if n < 2 else print('done')")
    study.ytdlp_stream([sys.executable, "-c", script, str(counter)])
    out = capsys.readouterr().out
    assert counter.read_text() == "3" and out.count("trying again") == 2 and out.rstrip().endswith("done")
