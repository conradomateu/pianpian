"""The native speech output must preserve the player's existing word-time contract."""
import copy
import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import sensevoice  # noqa: E402
import srt_tool  # noqa: E402


def transcript():
    return {'segments': [{'start': 0.1, 'end': 1.0, 'text': '你好，世界。', 'words': [
        {'word': '你好，', 'start': 0.1, 'end': 0.4}, {'word': '世界。', 'start': 0.6, 'end': 0.9}]}]}


def inputs(tmp_path):
    audio = tmp_path / 'audio.wav'
    with wave.open(str(audio), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000); f.writeframes(b'\0' * 32000)
    executable = tmp_path / 'native'
    executable.touch()
    for name in (sensevoice.MODEL, sensevoice.VAD):
        (tmp_path / name).write_bytes(b'pinned separately by models.py')
    return audio, executable


def test_native_output_keeps_chinese_pinyin_word_times_and_uses_cpu(monkeypatch, tmp_path):
    audio, executable = inputs(tmp_path)
    def native(cmd, **kwargs):
        assert cmd[cmd.index('--backend') + 1] == 'cpu'
        assert '--json' in cmd and '--vad' in cmd
        assert kwargs['check'] and kwargs['encoding'] == 'utf-8'
        return subprocess.CompletedProcess(cmd, 0, json.dumps(transcript(), ensure_ascii=False))
    monkeypatch.setenv('PIANPIAN_ACCEL', 'cuda')
    monkeypatch.setattr(sensevoice.subprocess, 'run', native)
    srt, words = tmp_path / 'zh.srt', tmp_path / 'zh.whisper.json'
    sensevoice.transcribe(audio, str(tmp_path), srt, words, executable)
    assert srt_tool.read_srt(srt)[0][2] == '你好，世界。'
    assert ''.join(c for c, _, _ in srt_tool.char_times(words)) == '你好，世界。'
    cues = [{'w': [[['你好'], ['世界']]]}]
    srt_tool.spoken_times(cues, words)
    assert cues[0]['k'] == [[[0.1, 0.4], [0.6, 0.9]]]


@pytest.mark.parametrize('fault', ['nan', 'outside', 'overlap', 'missing', 'uncovered', 'wrong_type'])
def test_bad_native_alignment_is_rejected(fault):
    data = copy.deepcopy(transcript())
    segment = data['segments'][0]
    if fault == 'nan': segment['words'][0]['start'] = float('nan')
    if fault == 'outside': segment['end'] = 1.2
    if fault == 'overlap': segment['words'][1]['start'] = 0.2
    if fault == 'missing': segment['words'] = []
    if fault == 'uncovered': segment['words'][0]['word'] = '好，'
    if fault == 'wrong_type': segment['start'] = True
    with pytest.raises(ValueError):
        sensevoice.validate(data, 1.0)


@pytest.mark.parametrize('result', [None, {'segments': []}, {'segments': [{'start': 0, 'end': 1, 'text': '你好'}]}])
def test_failed_empty_or_incomplete_inference_preserves_previous_outputs(monkeypatch, tmp_path, result):
    audio, executable = inputs(tmp_path)
    srt, words = tmp_path / 'zh.srt', tmp_path / 'zh.whisper.json'
    srt.write_text('old subtitles'); words.write_text('old timing')
    def native(cmd, **kwargs):
        if result is None:
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps(result))
    monkeypatch.setattr(sensevoice.subprocess, 'run', native)
    with pytest.raises((ValueError, RuntimeError, subprocess.CalledProcessError)):
        sensevoice.transcribe(audio, str(tmp_path), srt, words, executable)
    assert srt.read_text() == 'old subtitles' and words.read_text() == 'old timing'


def test_missing_native_helper_is_actionable_and_never_downloaded(tmp_path):
    with pytest.raises(RuntimeError, match='dev.py native'):
        sensevoice.transcribe(tmp_path/'absent.wav', str(tmp_path), tmp_path/'srt', tmp_path/'json', tmp_path/'missing')
