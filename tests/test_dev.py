"""The test command must work before any local build has created scratch/."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dev  # noqa: E402


def test_pytest_temp_directory_works_in_a_fresh_checkout(monkeypatch, tmp_path):
    checkout = tmp_path / "fresh-checkout"
    checkout.mkdir()
    case = checkout / "test_tmp.py"
    case.write_text("def test_tmp(tmp_path):\n    assert tmp_path.is_dir()\n", encoding="utf-8")
    monkeypatch.setattr(dev, "ROOT", checkout)

    def run(*command):
        arguments = command[command.index("pytest") + 1:]
        subprocess.run([sys.executable, "-m", "pytest", *arguments, str(case)],
                       cwd=checkout, check=True, capture_output=True, text=True, timeout=30)

    monkeypatch.setattr(dev, "run", run)
    assert not (checkout / "scratch").exists()
    dev.test()
    assert (checkout / "scratch/pytest-check").is_dir()
