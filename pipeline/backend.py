"""The swappable model interface, with a shared native implementation on Mac and Windows.

    backend.NAME                 "darwin" (also on Linux, where CI runs the tests) or "win32"
    backend.impl().transcribe(audio, model_dir, srt, words_json)
    backend.impl().translator(model_dir)  -> context manager yielding generate(prompt, temperature, max_tokens)
    backend.impl().align(zh_srt, en_srt)  -> writes zh.align.json with the shared native PLaMo aligner

This is the only platform check in pipeline/: models.py picks its catalog rows and lock section by NAME,
and the scripts call impl() for the engine. What every backend keeps to:
- transcribe leaves only srt and words_json behind (zh.whisper.json's shape: tests/test_backend.py);
- generate receives a complete PFML3 prompt; the shared runtime returns only the translation;
- a failing engine raises (CalledProcessError, OSError) or exits with one line; study.py reports it.
impl() imports the module on first use, so the native backend imports models.py (through
runtimes.py, for its downloads) can't make an import cycle with models.py, which imports this file.
"""
import sys
from importlib import import_module

NAME = "win32" if sys.platform == "win32" else "darwin"


def impl():
    """Both platforms use the same models and process protocol."""
    return import_module("backend_native")


def native_binary(name: str) -> str:
    return name + ".exe" if NAME == "win32" else name
