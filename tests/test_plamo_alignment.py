"""Word-link byte offsets, native output validation and preservation of existing results."""
import copy
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import align_srt as a  # noqa: E402


def frame(zh="猫", en="The cat."):
    raw = a.alignment_prompt(zh, en).encode()
    # One byte per token exercises UTF-8 characters split across multiple native tokens.
    return {"tokens": [{"piece": [b]} for b in raw], "vectors": [[1.0] + [0.0] * 1535 for b in raw]}


def test_multibyte_tokens_keep_character_offsets_and_exclude_grammar_words():
    assert a.word_links("猫", "The cat.", frame()) == [[4, 7, 0, 1, 1.0]]


@pytest.mark.parametrize("bad", ["coverage", "byte", "nan", "shape", "count"])
def test_native_hidden_states_are_validated_before_linking(bad):
    value = copy.deepcopy(frame())
    if bad == "coverage":
        value["tokens"][0]["piece"] = [88]
    elif bad == "byte":
        value["tokens"][0]["piece"] = [True]
    elif bad == "nan":
        value["vectors"][0][0] = float("nan")
    elif bad == "shape":
        value["vectors"][0].pop()
    else:
        value["vectors"].pop()
    with pytest.raises(ValueError):
        a.word_links("猫", "The cat.", value)


def test_failed_native_alignment_keeps_existing_links(monkeypatch, tmp_path):
    zh, en, out = (tmp_path / name for name in ("zh.srt", "zh.en.srt", "zh.align.json"))
    zh.write_text("1\n00:00:00,000 --> 00:00:01,000\n猫\n", encoding="utf-8")
    en.write_text("1\n00:00:00,000 --> 00:00:01,000\nThe cat.\n", encoding="utf-8")
    out.write_text("keep existing links")
    helper = tmp_path / "bin" / a.backend.native_binary("pianpian-align")
    helper.parent.mkdir()
    helper.touch()
    helper.with_name("alignment-build-manifest.json").write_text(json.dumps({"llama_release": a.runtimes.RELEASES["llama"]}))
    monkeypatch.setattr(a, "__file__", str(tmp_path / "align_srt.py"))
    monkeypatch.setattr(a, "ensure_model", lambda repo: str(tmp_path))
    monkeypatch.setattr(a, "model_file", lambda folder: tmp_path / "model.gguf")
    monkeypatch.setattr(a.runtimes, "ensure", lambda *args: str(tmp_path / "llama-server"))
    tempdir = a.tempfile.TemporaryDirectory
    monkeypatch.setattr(a.tempfile, "TemporaryDirectory", lambda **kw: tempdir(dir=tmp_path, **kw))

    class Proc:
        stdin = io.StringIO()
        stdout = io.StringIO(json.dumps({"tokens": [], "vectors": []}) + "\n")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def poll(self):
            return 0
    monkeypatch.setattr(a.subprocess, "Popen", lambda *args, **kwargs: Proc())
    with pytest.raises(ValueError):
        a.align(zh, en, out)
    assert out.read_text() == "keep existing links"
    assert not out.with_suffix(".json.part").exists()
