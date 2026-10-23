"""Updates: versions compare right, GitHub is asked at most once a day, outdated models are found."""
import importlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "pipeline")]


def fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_HOME", str(tmp_path))
    import engine
    import updates
    importlib.reload(engine)
    return importlib.reload(updates)


def test_versions():
    import updates
    assert updates.newer("0.10.0", "0.9.3") and updates.newer("v1.0.0", "0.99.0")
    assert not updates.newer("0.2.0", "0.2.0") and not updates.newer("0.1.9", "0.2.0")
    assert not updates.newer("9.9.9", "dev")                   # a developer's checkout is never nagged
    # release-please names tags after the package: the number is what counts
    assert updates.clean_version("pianpian-v0.2.0") == "0.2.0" and updates.clean_version("v1.0.0") == "1.0.0"
    assert updates.newer(updates.clean_version("pianpian-v0.2.0"), "0.1.0")


def test_github_is_asked_once_a_day(monkeypatch, tmp_path):
    u = fresh(monkeypatch, tmp_path)
    calls = []

    def fake(req, timeout):
        calls.append(req.full_url)
        body = {"tag_name": "pianpian-v0.3.0", "html_url": "https://github.com/x/y/releases/tag/pianpian-v0.3.0", "body": "- faster\n- nicer",
                "assets": [{"name": "Pianpian-macOS.zip", "browser_download_url": "https://example.com/Pianpian-macOS.zip"}]}
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(u, "urlopen", fake)
    first = u.check_app("0.2.0")
    assert first["version"] == "0.3.0" and first["download"].endswith("Pianpian-macOS.zip")
    assert u.check_app("0.2.0") == first and len(calls) == 1     # the second time comes from updates.json
    assert u.check_app("0.3.0") is None                          # already on it


def test_outdated_models_are_found(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANPIAN_MODELS", str(tmp_path))
    import models
    old = tmp_path / "someone__retired-model"
    old.mkdir()
    (old / "weights.safetensors").write_bytes(b"x" * 10)
    names = [m["name"] for m in models.unused()]
    assert names == ["someone/retired-model"]
    assert models.remove_unused() == 10 and not old.exists()


def test_lock_pins_every_catalog_model():
    import models
    lock = models.lock()
    assert {m["id"] for m in models.CATALOG} <= set(lock)
    for entry in lock.values():
        assert entry["files"] and all(f["sha256"] and f["size"] and f.get("modelscope") for f in entry["files"])
