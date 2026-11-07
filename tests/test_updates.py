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
    monkeypatch.setattr(u.engine, "WINDOWS", False)              # this release has only the macOS files
    calls = []

    def fake(req, timeout):
        calls.append(req.full_url)
        body = {"tag_name": "pianpian-v0.3.0", "html_url": "https://github.com/x/y/releases/tag/pianpian-v0.3.0", "body": "- faster\n- nicer",
                "assets": [{"name": "Pianpian-macOS.zip", "browser_download_url": "https://example.com/Pianpian-macOS.zip"},
                           {"name": "Pianpian-macOS.dmg", "browser_download_url": "https://example.com/Pianpian-macOS.dmg"}]}
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(u, "urlopen", fake)
    first = u.check_app("0.2.0")
    assert first["version"] == "0.3.0" and first["download"].endswith("Pianpian-macOS.dmg")
    assert u.check_app("0.2.0") == first and len(calls) == 1     # the second time comes from updates.json
    assert u.check_app("0.3.0") is None                          # already on it


def test_windows_update_never_offers_a_mac_asset_even_from_cache(monkeypatch, tmp_path):
    u = fresh(monkeypatch, tmp_path)
    monkeypatch.setattr(u.engine, "WINDOWS", True)
    release = {"tag_name": "pianpian-v0.3.0", "html_url": "https://example.test/release",
               "assets": [{"name": "Pianpian-macOS.dmg", "browser_download_url": "https://example.test/mac.dmg"}]}
    monkeypatch.setattr(u, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(release).encode()))
    assert u.check_app("0.2.0")["download"] is None
    state = u._load()
    state["app"]["download"] = "https://example.test/mac.dmg"   # cache written by an earlier Windows build
    u._save(state)
    monkeypatch.setattr(u, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("cached result must not fetch")))
    result = u.check_app("0.2.0")
    assert result["download"] is None and result["url"] == release["html_url"]


def test_windows_gets_the_installer(monkeypatch, tmp_path):
    u = fresh(monkeypatch, tmp_path)
    monkeypatch.setattr(u.engine, "WINDOWS", True)

    def fake(req, timeout):
        body = {"tag_name": "pianpian-v0.3.0", "html_url": "https://github.com/x/y/releases/tag/pianpian-v0.3.0", "body": "",
                "assets": [{"name": "Pianpian-macOS.dmg", "browser_download_url": "https://example.com/Pianpian-macOS.dmg"},
                           {"name": "Pianpian-Windows.zip", "browser_download_url": "https://example.com/Pianpian-Windows.zip"},
                           {"name": "Pianpian-Windows-Setup.exe", "browser_download_url": "https://example.com/Pianpian-Windows-Setup.exe"}]}
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(u, "urlopen", fake)
    assert u.check_app("0.2.0")["download"].endswith("Pianpian-Windows-Setup.exe")


def test_windows_takes_the_zip_and_the_mac_keeps_its_cache(monkeypatch, tmp_path):
    u = fresh(monkeypatch, tmp_path)
    monkeypatch.setattr(u.engine, "WINDOWS", True)
    release = {"tag_name": "pianpian-v0.3.0", "html_url": "https://example.test/release",
               "assets": [{"name": "Pianpian-Windows.zip", "browser_download_url": "https://example.test/dl/Pianpian-Windows.zip"}]}
    monkeypatch.setattr(u, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(release).encode()))
    assert u.check_app("0.2.0")["download"] == "https://example.test/dl/Pianpian-Windows.zip"
    state = u._load()
    state["app"]["download"] = "https://example.test/dl/Pianpian-macOS.dmg"
    u._save(state)
    assert u.check_app("0.2.0")["download"] is None                # a Mac file cached by an older build is not offered
    monkeypatch.setattr(u.engine, "WINDOWS", False)                # the same cache read by the Mac build keeps its DMG
    assert u.check_app("0.2.0")["download"] == "https://example.test/dl/Pianpian-macOS.dmg"


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
