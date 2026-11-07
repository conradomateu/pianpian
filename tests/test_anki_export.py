"""Export boundary checks and real FFmpeg clips using generated audio, not third-party content."""
import json
import math
import shutil
import struct
import subprocess
import sys
import threading
import wave
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import anki_export  # noqa: E402
import engine  # noqa: E402
import server  # noqa: E402


@pytest.fixture
def media(tmp_path, monkeypatch):
    exe = shutil.which("ffmpeg")
    if not exe:
        pytest.skip("FFmpeg required for real audio extraction")
    monkeypatch.setattr(engine, "ffmpeg", lambda: exe)
    monkeypatch.setattr(engine, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(engine, "CONFIG", tmp_path / "settings" / "config.json")
    monkeypatch.setattr(engine, "SUPPORT", tmp_path / "settings")
    folder = tmp_path / "library" / "中文 café & sample"
    folder.mkdir(parents=True)
    with wave.open(str(folder / "source.wav"), "wb") as f:
        f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        f.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(3 * 16000)))
    words = {"cues": [{"s": 0, "e": 2, "w": [[["你好", "nǐhǎo", "hello"], ["，"], ["中文", "zhōngwén", "Chinese"]]]}]}
    (folder / "zh.words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    (folder / "zh.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\n你好，中文\n", encoding="utf-8")
    return folder


def request_data():
    return {"selection": {"cueStart": 0, "cueEnd": 0, "first": 0, "last": 0}, "start": .1, "end": .9,
            "expression": "你好", "pinyin": "nǐhǎo", "meaning": "hello", "sentence": "你好，中文", "translation": "Hello, Chinese",
            "deck": "Mandarin", "profile": "Test", "highlight": "jade"}


def test_preview_export_uses_same_bytes_and_survives_folder_rename(media, monkeypatch):
    data = request_data()
    preview = anki_export.preview(media, media.parent, data)
    path = anki_export.audio_path(preview["url"].rsplit("/", 1)[1])
    assert preview["duration"] == pytest.approx(.8)
    subprocess.run([engine.ffmpeg(), "-v", "error", "-i", str(path), "-f", "null", "-"], check=True, capture_output=True)
    sent = []

    class Client:
        def export(self, deck, fields, export_id, **kw):
            assert kw["highlight"] == "jade"
            assert kw["tones"] == {}
            sent.append((export_id, kw["media"], fields))
            return {"state": "added", "noteId": 42, "deck": deck}

    monkeypatch.setattr(anki_export, "client", Client)
    with pytest.raises(ValueError, match="Preview"):
        anki_export.export(media, media.parent, data)
    result = anki_export.export(media, media.parent, {**data, "preview": preview["url"]})
    assert result["noteId"] == 42 and sent[0][1][0][1] == path.read_bytes()
    assert sent[0][2]["Audio"] == f"[sound:{path.name}]"
    renamed = media.rename(media.with_name("renamed"))
    new_preview = anki_export.preview(renamed, renamed.parent, data)
    anki_export.export(renamed, renamed.parent, {**data, "preview": new_preview["url"], "meaning": "corrected", "update": True})
    assert sent[0][0] == sent[1][0]


def test_export_forwards_tones_with_trimmed_plain_fields_and_update(media, monkeypatch):
    data = request_data()
    tones = {"pinyin": [["nǐ", 3], ["hǎo", 3]], "expression": [["你", 3], ["好", 3]]}
    data.update(expression=" 你好\n", pinyin=" nǐhǎo ", tones=tones, update=True, highlight="none")
    data["preview"] = anki_export.preview(media, media.parent, data)["url"]

    class Client:
        def export(self, deck, fields, export_id, **kw):
            assert fields["Expression"] == "你好" and fields["Pinyin"] == "nǐhǎo"
            assert kw["tones"] is tones and kw["highlight"] == "none"
            assert kw["update"] is True and kw["expected_profile"] == "Test"
            return {"state": "updated", "noteId": 42, "deck": deck}

    monkeypatch.setattr(anki_export, "client", Client)
    assert anki_export.export(media, media.parent, data)["state"] == "updated"


@pytest.mark.parametrize("start,end", [(float("nan"), 1), (0, float("inf")), (True, 1), (-1, 1), (1, 1), (2, 1), (0, 999), (0, 4)])
def test_invalid_bounds_rejected(media, start, end):
    with pytest.raises(ValueError):
        anki_export.preview(media, media.parent, {**request_data(), "start": start, "end": end})


def test_selection_identity_and_source_checks(media, tmp_path):
    first = anki_export.selection_anchor(media, request_data()["selection"])
    second = anki_export.selection_anchor(media, {"cueStart": 0, "cueEnd": 0, "first": 2, "last": 2})
    assert anki_export.occurrence_id(media, first) != anki_export.occurrence_id(media, second)
    with pytest.raises(ValueError):
        anki_export.selection_anchor(media, {"cueStart": True, "cueEnd": 0, "first": 0, "last": 0})
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"private")
    with pytest.raises(ValueError, match="inside"):
        anki_export.source(outside, media.parent)
    for name in ("../source.wav", "x.mp3", "pianpian-../x.mp3"):
        with pytest.raises(ValueError):
            anki_export.audio_path(name)


def test_failed_retime_does_not_reuse_truncated_bounds(media, monkeypatch):
    words = media / "zh.words.json"
    original = json.loads(words.read_text())
    original["cues"][0]["k"] = [[[0, .1], 0, [.1, .2]]]
    words.write_text(json.dumps(original))
    (media / "zh.whisper.json").write_text("{}")
    monkeypatch.setattr(engine, "python", lambda: "missing-engine-executable")
    repaired = anki_export.study_words(media)
    assert "k" not in repaired["cues"][0]
    assert "k" in json.loads(words.read_text())["cues"][0]


def test_edited_subtitles_cannot_reuse_stale_word_identity(media):
    selection = {**request_data()["selection"], "sentence": "你好，中文", "expression": "你好"}
    original = anki_export.selection_anchor(media, selection)
    (media / "zh.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\n再见，中文\n", encoding="utf-8")
    with pytest.raises(ValueError, match="subtitles changed"):
        anki_export.selection_anchor(media, selection)
    with pytest.raises(ValueError, match="word data"):
        anki_export.selection_anchor(media, request_data()["selection"])
    sentence = anki_export.selection_anchor(media, {"cueStart": 0, "cueEnd": 0, "first": None, "last": None})
    assert sentence["text"] == "再见中文" and sentence != original


def test_resegmented_words_require_new_selection(media):
    selection = {**request_data()["selection"], "sentence": "你好，中文", "expression": "你好"}
    file = media / "zh.words.json"
    data = json.loads(file.read_text())
    data["cues"][0]["w"][0][:1] = [["你"], ["好"]]
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="selected words changed"):
        anki_export.selection_anchor(media, selection)


def test_cross_cue_selection_keeps_edited_middle_sentence(media):
    (media / "zh.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\n明天喝水\n\n3\n00:00:02,000 --> 00:00:03,000\n谢谢\n", encoding="utf-8")
    cues = [{"s": i, "e": i + 1, "w": [[[text]]]} for i, text in enumerate(["你好", "昨天喝茶", "谢谢"])]
    (media / "zh.words.json").write_text(json.dumps({"cues": cues}), encoding="utf-8")
    result = anki_export.selection_anchor(media, {"cueStart": 0, "cueEnd": 2, "first": 0, "last": 0,
        "sentence": "你好\n明天喝水\n谢谢", "expression": "你好\n明天喝水\n谢谢"})
    assert result == {"start": 0, "end": 8, "text": "你好明天喝水谢谢"}


def test_duration_rounding_cannot_reverse_interval(media, monkeypatch):
    monkeypatch.setattr(anki_export, "duration", lambda path: 3.14)
    assert anki_export.bounds(media / "source.wav", {"start": 2, "end": 3.144}) == (2, 3.14)
    with pytest.raises(ValueError, match="start must be before"):
        anki_export.bounds(media / "source.wav", {"start": 3.141, "end": 3.144})


def test_export_chooses_the_playing_video_over_audio_sidecar(media):
    (media / "source.mp3").touch()
    (media / "source.mp4").touch()
    assert anki_export.source(media, media.parent) == server.video_in(media)


def test_anki_http_requires_guard_and_returns_readable_validation(media, monkeypatch):
    monkeypatch.setitem(server.CFG, "library", media.parent)
    srv = server.LocalServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        data = {**request_data(), "id": media.name}
        for guarded, code, body in [(False, 403, data), (True, 400, {**data, "id": "../outside"}), (True, 400, [])]:
            req = Request(base + "/api/anki/preview", data=json.dumps(body).encode(), headers={"X-Kit": "1"} if guarded else {})
            with pytest.raises(HTTPError) as caught:
                urlopen(req)
            assert caught.value.code == code
        req = Request(base + "/api/anki/preview", data=json.dumps(data).encode(), headers={"X-Kit": "1"})
        result = json.load(urlopen(req))
        response = urlopen(Request(base + result["url"], headers={"Range": "bytes=0-3"}))
        assert response.status == 206 and len(response.read()) == 4
    finally:
        srv.shutdown()
        srv.server_close()


def test_windows_engine_executable_layout(tmp_path, monkeypatch):
    monkeypatch.delenv("PIANPIAN_PYTHON", raising=False)
    monkeypatch.setattr(engine, "WINDOWS", True)                # computed at import: patch the flag, not sys.platform
    monkeypatch.setattr(engine, "engine_dir", lambda: tmp_path)
    py = tmp_path / "Scripts" / "python.exe"
    py.parent.mkdir()
    py.touch()
    assert engine.python() == str(py)
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)
    ffmpeg = tmp_path / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries" / "ffmpeg-test.exe"
    ffmpeg.parent.mkdir(parents=True)
    ffmpeg.touch()
    ffmpeg.chmod(0o700)
    assert engine.ffmpeg() == str(ffmpeg)
