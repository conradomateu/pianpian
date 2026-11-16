"""The acceptance runner must reject incomplete packaged-pipeline outputs."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_acceptance", ROOT / "tools" / "check_native_pipeline.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def test_acceptance_timeout_stops_windows_descendants_before_waiting(monkeypatch):
    process = MagicMock()
    process.__enter__.return_value = process
    process.pid = 42
    process.communicate.side_effect = [subprocess.TimeoutExpired(["pipeline"], 1), (None, None)]
    process.poll.return_value = 0
    start, stop = MagicMock(return_value=process), MagicMock()
    monkeypatch.setattr(a.sys, "platform", "win32")
    monkeypatch.setattr(a.subprocess, "Popen", start)
    monkeypatch.setattr(a.subprocess, "run", stop)
    with pytest.raises(subprocess.TimeoutExpired):
        a.run_checked(["pipeline"], timeout=1)
    stop.assert_called_once_with(["taskkill", "/F", "/T", "/PID", "42"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    assert start.call_args.kwargs["start_new_session"] is False
    assert process.communicate.call_count == 2


def test_acceptance_preserves_output_and_nonzero_errors():
    with pytest.raises(subprocess.CalledProcessError) as failure:
        a.run_checked([sys.executable, "-c", "print('native failed'); raise SystemExit(7)"],
                      timeout=30, stdout=subprocess.PIPE, text=True)
    assert failure.value.returncode == 7 and failure.value.output.strip() == "native failed"


def outputs(tmp_path):
    (tmp_path / "zh.whisper.json").write_text(json.dumps({"model": "SenseVoiceSmall-Q8"}), encoding="utf-8")
    words = {"version": 2, "cues": [{"s": 0, "e": 1, "w": [[["猫", "māo", "cat"]]], "k": [[[0.1, 0.5]]]}]}
    (tmp_path / "zh.words.json").write_text(json.dumps(words), encoding="utf-8")
    links = {"version": 1, "model": a.MODEL, "layer": 7, "cues": [[[0, 3, 0, 1, 0.9]]]}
    (tmp_path / "zh.align.json").write_text(json.dumps(links), encoding="utf-8")
    (tmp_path / "study.mkv").write_bytes(b"mock video")
    def read(path):
        return [("1", "00:00:00,000 --> 00:00:01,000", {"zh.srt": "猫", "zh.pinyin.srt": "māo", "zh.en.srt": "cat"}[path.name])]
    return read


def test_native_acceptance_requires_complete_word_times_and_model_links(tmp_path):
    read = outputs(tmp_path)
    result = a.validate_outputs(tmp_path, read, lambda data, duration: [{"words": [1]}], 1)
    assert result == {"cues": 1, "speech_segments": 1, "word_intervals": 1, "bilingual_links": 1}
    (tmp_path / "zh.align.json").write_text(json.dumps({"version": 1, "model": a.MODEL, "layer": 7, "cues": [[]]}))
    with pytest.raises(RuntimeError, match="No bilingual"):
        a.validate_outputs(tmp_path, read, lambda *args: [1], 1)


@pytest.mark.parametrize("failure", ["model", "timing", "offset", "count"])
def test_native_acceptance_rejects_incomplete_outputs(tmp_path, failure):
    read = outputs(tmp_path)
    if failure in ("model", "offset"):
        path = tmp_path / "zh.align.json"
        value = json.loads(path.read_text())
        if failure == "model":
            value["model"] = "old-model"
        else:
            value["cues"][0][0][1] = 200
    else:
        path = tmp_path / "zh.words.json"
        value = json.loads(path.read_text())
        if failure == "timing":
            value["cues"][0]["k"] = [[[0.9, 0.2]]]
        else:
            value["cues"] = []
    path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError):
        a.validate_outputs(tmp_path, read, lambda *args: [1], 1)
