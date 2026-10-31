"""Paths work for anyone: no one's home folder, % in folder names, the Hugging Face cache where people keep it."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "pipeline")]


def test_percent_in_a_folder_is_not_a_template():
    import study
    assert study.literal(Path("100% 中文")) == "100%% 中文"


def test_hugging_face_cache_follows_hf_home(monkeypatch, tmp_path):
    import models
    repo = "someone/tiny"
    snap = tmp_path / "hub" / "models--someone--tiny" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    (snap / "weights.npz").write_bytes(b"x")
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert models.hf_cached(repo, None) == snap


def test_the_app_tells_the_pipeline_where_its_data_is(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_HOME", str(tmp_path))
    monkeypatch.delenv("PIANPIAN_MODELS", raising=False)
    monkeypatch.delenv("PIANPIAN_CACHE", raising=False)
    import importlib
    import engine
    importlib.reload(engine)
    env = engine.pipeline_env()
    expected = {"PIANPIAN_MODELS": str(tmp_path / "models"), "PIANPIAN_CACHE": str(tmp_path / "cache")}
    if engine.WINDOWS:
        expected["PIANPIAN_RUNTIME"] = str(tmp_path / "runtime")
    assert env == expected


def test_no_personal_paths_in_what_ships():
    shipped = [*ROOT.glob("*.py"), *ROOT.glob("*.html"), *(ROOT / "pipeline").glob("*.py"), *(ROOT / "assets").glob("*")]
    for f in shipped:
        text = f.read_text(encoding="utf-8", errors="ignore")
        assert "/Users/" not in text and "~/code/" not in text, f
