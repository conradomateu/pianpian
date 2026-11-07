"""The first-run setup's decisions: what counts as missing, and when the engine needs an update."""
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_HOME", str(tmp_path))
    for key in ("PIANPIAN_MODELS", "PIANPIAN_CACHE", "PIANPIAN_RUNTIME", "PIANPIAN_ACCEL"):
        monkeypatch.setenv(key, "")                           # recorded, so what the setup writes is undone afterwards
        monkeypatch.delenv(key)
    import engine
    return importlib.reload(engine)


def catalog(*ready):
    return [{"id": f"m{i}", "task": "", "about": "", "size": 1, "ready": r, "path": None} for i, r in enumerate(ready)]


def install_fake_python(monkeypatch, e, root):
    """A Python path for check() without needing a real venv (or a symlink privilege on Windows)."""
    import subprocess
    py = e.engine_python(root)
    py.parent.mkdir(parents=True)
    monkeypatch.setenv("PIANPIAN_PYTHON", str(py))
    monkeypatch.setattr(e.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0))
    return py


def test_skipped_model_is_not_asked_for_again(monkeypatch, tmp_path):
    e = fresh(monkeypatch, tmp_path)
    monkeypatch.setattr(e.models, "status", lambda: catalog(False, True))
    if e.WINDOWS:
        monkeypatch.setattr(e.runtimes, "status", lambda: {"ready": True, "size": 0, "label": "", "tools": {}})
    e.STATE.update(engine=True, current=True)
    assert e.SETUP.plan()["needed"]                           # first run: everything missing is offered
    e.save_config(models=["m1"])                              # m0 was left out
    assert not e.SETUP.plan()["needed"]
    e.save_config(models=["m0", "m1"])
    assert e.SETUP.plan()["needed"]


def test_engine_from_older_requirements_needs_an_update(monkeypatch, tmp_path):
    e = fresh(monkeypatch, tmp_path)
    eng = tmp_path / "engine"
    install_fake_python(monkeypatch, e, eng)
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


@pytest.mark.parametrize("windows", [False, True])
@pytest.mark.parametrize("overrides", [False, True])
def test_setup_relocates_app_paths_before_starting_downloads(monkeypatch, tmp_path, windows, overrides):
    e = fresh(monkeypatch, tmp_path)
    folders = {"PIANPIAN_MODELS": "models", "PIANPIAN_CACHE": "cache", "PIANPIAN_RUNTIME": "runtime"}
    if overrides:
        for key, folder in folders.items():
            monkeypatch.setenv(key, str(tmp_path / "explicit" / folder))
        importlib.reload(e)
    monkeypatch.setattr(e, "WINDOWS", windows)
    e.STATE.update(engine=True, current=True)
    seen = []
    monkeypatch.setattr(e.models, "status", lambda: seen.append(e.models.cache()) or [])
    monkeypatch.setattr(e.runtimes, "status", lambda: {"ready": True, "size": 0, "label": "runtime"})
    workers = []
    monkeypatch.setattr(e.Setup, "_run", lambda self: workers.append(dict(os.environ)))
    os.environ.update(e.pipeline_env())                       # same as server.start()
    e.SETUP.plan()                                            # same as opening the setup page
    dest = tmp_path / "another-disk"
    e.SETUP.start(None, str(dest), [])
    e.SETUP.thread.join(timeout=5)
    assert not e.SETUP.thread.is_alive() and len(workers) == 1
    expected_root = tmp_path / "explicit" if overrides else dest
    assert seen[-1] == expected_root / "models"               # catalog was checked after relocation
    for key, folder in folders.items():
        if key == "PIANPIAN_RUNTIME" and not windows:
            continue
        assert workers[0][key] == str(expected_root / folder)
    assert e.engine_dir() == dest / "engine"


@pytest.mark.parametrize("windows", [False, True])
@pytest.mark.parametrize("working", [False, True])
def test_relocation_installs_and_checks_the_destination_engine(monkeypatch, tmp_path, windows, working):
    e = fresh(monkeypatch, tmp_path)
    monkeypatch.delenv("PIANPIAN_PYTHON", raising=False)
    monkeypatch.setattr(e, "WINDOWS", windows)
    monkeypatch.setattr(e, "FROZEN", True)                     # no fallback to the checkout's interpreter
    old_py = e.engine_python(e.engine_dir())
    old_py.parent.mkdir(parents=True)
    old_py.touch()
    e.STATE.update(engine=True, current=True)
    os.environ.update(e.pipeline_env())
    monkeypatch.setattr(e.models, "status", lambda: [])
    monkeypatch.setattr(e.runtimes, "status", lambda: {"ready": True, "size": 0, "label": "runtime"})
    monkeypatch.setattr(e, "mirror_env", lambda: {})
    monkeypatch.setattr(e, "uv", lambda: "uv")
    calls = []

    def install(self, cmd, env, sid):
        calls.append(cmd)
        if cmd[1] == "venv":
            py = e.engine_python(Path(cmd[-1]))
            py.parent.mkdir(parents=True)
            py.touch()

    monkeypatch.setattr(e.Setup, "_exec", install)
    monkeypatch.setattr(e.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0 if working and Path(cmd[0]).is_file() else 1))
    dest = tmp_path / "another-disk"
    e.SETUP.start(None, str(dest), [])
    e.SETUP.thread.join(timeout=5)
    assert not e.SETUP.thread.is_alive()
    assert calls[0] == ["uv", "venv", "--python", "3.12", str(dest / "engine")]
    assert str(e.engine_python(dest / "engine")) in calls[1] and str(old_py) not in calls[1]
    assert e.SETUP.state == ("done" if working else "failed")
    if not working:
        assert "could not start after setup" in e.SETUP.error


def fake_setup(monkeypatch, e, working=lambda py: True):
    """[simulated] uv and the engine's Python: `uv venv` makes a python file, check() asks working(py)."""
    monkeypatch.delenv("PIANPIAN_PYTHON", raising=False)
    monkeypatch.setattr(e, "FROZEN", True)
    monkeypatch.setattr(e.models, "status", lambda: [])
    monkeypatch.setattr(e.runtimes, "status", lambda: {"ready": True, "size": 0, "label": "runtime"})
    monkeypatch.setattr(e.runtimes, "backend_for", lambda tool: "cpu")
    monkeypatch.setattr(e, "mirror_env", lambda: {})
    monkeypatch.setattr(e, "uv", lambda: "uv")
    calls = []

    def install(self, cmd, env, sid):
        calls.append(cmd)
        if cmd[1] == "venv":
            py = e.engine_python(Path(cmd[-1]))
            py.parent.mkdir(parents=True)
            py.touch()
            (Path(cmd[-1]) / "pyvenv.cfg").touch()

    monkeypatch.setattr(e.Setup, "_exec", install)
    monkeypatch.setattr(e.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0 if Path(cmd[0]).is_file() and working(Path(cmd[0])) else 1))
    return calls


def run_setup(e, *args, **kw):
    e.SETUP.start(*args, **kw)
    e.SETUP.thread.join(timeout=10)
    assert not e.SETUP.thread.is_alive()


@pytest.mark.parametrize("broken", ["cannot-start", "no-python"])
def test_setup_rebuilds_an_engine_that_cannot_start(monkeypatch, tmp_path, broken):
    # [simulated] engine/ is there but its Python is gone or won't start: the setup makes it again instead of
    # failing the same way on every retry (`uv venv` alone exits 2 on an existing folder, uv 0.13.7)
    e = fresh(monkeypatch, tmp_path)
    eng = e.engine_dir()
    py = e.engine_python(eng)
    py.parent.mkdir(parents=True)
    (eng / "pyvenv.cfg").touch()
    (eng / ".pianpian-requirements").write_text(e.requirements_id() + "\n")
    if broken == "cannot-start":
        py.write_text("old")                                  # the base interpreter it pointed to was removed
    # only this engine counts (a checkout's .venv would otherwise stand in for a missing one)
    calls = fake_setup(monkeypatch, e, working=lambda p: p == py and p.read_text() != "old")
    e.check()
    assert e.STATE["engine"] is False
    run_setup(e, None, None, [])
    assert calls[0] == ["uv", "venv", "--python", "3.12", str(eng)]
    assert e.SETUP.state == "done", e.SETUP.error
    assert py.read_text() == ""                               # made again, not the broken one


def test_setup_leaves_a_folder_that_is_not_its_engine(monkeypatch, tmp_path):
    e = fresh(monkeypatch, tmp_path)
    eng = e.engine_dir()
    eng.mkdir(parents=True)
    (eng / "notes.txt").write_text("mine")
    fake_setup(monkeypatch, e)
    run_setup(e, None, None, [])
    assert e.SETUP.state == "failed" and "is not Pianpian's engine" in e.SETUP.error
    assert (eng / "notes.txt").read_text() == "mine"


@pytest.mark.parametrize("windows", [False, True])
def test_a_new_data_folder_takes_the_downloads_along(monkeypatch, tmp_path, windows):
    # [simulated] the models, runtime and dictionary move with the data folder (no 4 GB download again);
    # the old engine and Python can't move (absolute paths): they stay, offered for the opt-in cleanup only
    e = fresh(monkeypatch, tmp_path)
    monkeypatch.setattr(e, "WINDOWS", windows)
    old = e.data_dir()
    for f in ("models/org__model/.complete", "runtime/whisper-cpu/.complete", "cache/cedict.txt",
              "engine/.pianpian-requirements", "python/cpython-3.12/bin/python"):
        (old / f).parent.mkdir(parents=True, exist_ok=True)
        (old / f).write_text("x")
    fake_setup(monkeypatch, e)
    new = tmp_path / "another-disk"
    (new / "models").mkdir(parents=True)                      # an empty folder is no reason to download again
    run_setup(e, None, str(new), [])
    assert e.SETUP.state == "done", e.SETUP.error
    for f in ("models/org__model/.complete", "runtime/whisper-cpu/.complete", "cache/cedict.txt"):
        assert (new / f).exists() and not (old / f).exists()
    assert (old / "engine" / ".pianpian-requirements").exists() and (new / "engine").is_dir()
    os.environ.update(e.pipeline_env())
    left = {o["name"]: o["path"] for o in e.SETUP.plan()["old"] if " in " in o["name"]}
    assert left == {f"engine in {old}": str(old / "engine"), f"python in {old}": str(old / "python")}
    run_setup(e, None, None, [])                              # no cleanup asked for: nothing deleted
    assert (old / "engine").exists() and (old / "python").exists()
    run_setup(e, None, None, [], cleanup=True)
    assert not (old / "engine").exists() and not (old / "python").exists()
    assert e.config()["moved_from"] == [] and (old / "config.json").exists()


def test_moving_back_never_offers_the_engine_in_use(monkeypatch, tmp_path):
    e = fresh(monkeypatch, tmp_path)
    fake_setup(monkeypatch, e)
    old, new = e.data_dir(), tmp_path / "b"
    run_setup(e, None, str(new), [])
    run_setup(e, None, str(old), [])
    assert e.config()["moved_from"] == [str(new)]
    assert all(not o["path"].startswith(str(old / "engine")) for o in e.SETUP.plan()["old"])


def test_the_setup_keeps_the_gpu_choice_for_the_jobs(monkeypatch, tmp_path):
    # [simulated] the GPU probes (up to 35 s) run once at setup; every job gets the answer as PIANPIAN_ACCEL
    e = fresh(monkeypatch, tmp_path)
    monkeypatch.setattr(e, "WINDOWS", True)
    e.STATE.update(engine=True, current=True)
    monkeypatch.setattr(e.models, "status", lambda: [])
    monkeypatch.setattr(e.runtimes, "status", lambda: {"ready": True, "size": 0, "label": "runtime"})
    monkeypatch.setattr(e.Setup, "_run", lambda self: setattr(self, "state", "done"))
    probes = []
    monkeypatch.setattr(e.runtimes, "backend_for", lambda tool: probes.append(tool) or "cuda")
    assert "PIANPIAN_ACCEL" not in e.pipeline_env()
    run_setup(e, None, None, [])
    assert e.config()["accel"] == "cuda" and e.pipeline_env()["PIANPIAN_ACCEL"] == "cuda" and len(probes) == 1
    assert os.environ["PIANPIAN_ACCEL"] == "cuda"            # the server process too: its /api/status needs no probe
    monkeypatch.setitem(e.PATH_OVERRIDES, "PIANPIAN_ACCEL", "cpu")   # yours wins, and is not probed or saved
    run_setup(e, None, None, [])
    assert e.pipeline_env()["PIANPIAN_ACCEL"] == "cpu" and len(probes) == 1 and e.config()["accel"] == "cuda"
    monkeypatch.setattr(e, "WINDOWS", False)
    assert "PIANPIAN_ACCEL" not in e.pipeline_env()


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
