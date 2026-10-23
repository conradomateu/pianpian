"""The first-run setup's decisions: what counts as missing, and when the engine needs an update."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_HOME", str(tmp_path))
    monkeypatch.delenv("PIANPIAN_MODELS", raising=False)
    import engine
    return importlib.reload(engine)


def catalog(*ready):
    return [{"id": f"m{i}", "task": "", "about": "", "size": 1, "ready": r, "path": None} for i, r in enumerate(ready)]


def test_skipped_model_is_not_asked_for_again(monkeypatch, tmp_path):
    e = fresh(monkeypatch, tmp_path)
    monkeypatch.setattr(e.models, "status", lambda: catalog(False, True))
    e.STATE.update(engine=True, current=True)
    assert e.SETUP.plan()["needed"]                           # first run: everything missing is offered
    e.save_config(models=["m1"])                              # m0 was left out
    assert not e.SETUP.plan()["needed"]
    e.save_config(models=["m0", "m1"])
    assert e.SETUP.plan()["needed"]


def test_engine_from_older_requirements_needs_an_update(monkeypatch, tmp_path):
    e = fresh(monkeypatch, tmp_path)
    eng = tmp_path / "engine"
    (eng / "bin").mkdir(parents=True)
    (eng / "bin" / "python").symlink_to(sys.executable)
    monkeypatch.setattr(e, "CHECK", "pass")
    (eng / ".pianpian-requirements").write_text("old\n")
    assert e.check() == {"engine": True, "current": False}
    (eng / ".pianpian-requirements").write_text(e.requirements_id() + "\n")
    assert e.check() == {"engine": True, "current": True}


def test_settings_default_and_persist(monkeypatch, tmp_path):
    e = fresh(monkeypatch, tmp_path)
    assert e.config()["data"] == str(tmp_path)
    e.save_config(library=str(tmp_path / "videos"))
    assert e.config()["library"] == str(tmp_path / "videos")
    assert e.models_dir() == tmp_path / "models"


def test_the_packaged_app_never_writes_bytecode_into_itself(monkeypatch, tmp_path):
    """Writing .pyc files into Pianpian.app breaks its code signature, so inside the app Python must not."""
    monkeypatch.setenv("PIANPIAN_HOME", str(tmp_path))
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    import engine
    importlib.reload(engine)
    assert sys.dont_write_bytecode is True
    import os
    assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE")
    importlib.reload(engine)                                  # a checkout, not the app: bytecode is fine
    assert sys.dont_write_bytecode is False and "PYTHONDONTWRITEBYTECODE" not in os.environ
