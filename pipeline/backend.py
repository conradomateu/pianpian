"""The model engines behind the pipeline, one module per platform (AGENTS.md rule 3).

    backend.NAME                 "darwin" (also on Linux, where CI runs the tests) or "win32"
    backend.impl().transcribe(audio, model_dir, srt, words_json)
    backend.impl().translator(model_dir)  -> context manager yielding generate(prompt, temperature, max_tokens)
    backend.impl().ocr(frames_dir)        -> one "name<TAB>text" line per frame, in frame order

This is the only platform check in pipeline/: models.py picks its catalog rows and lock section by NAME,
and the scripts call impl() for the engine. What every backend keeps to:
- transcribe leaves only srt and words_json behind (zh.whisper.json's shape: tests/test_backend.py);
- generate gets the user message text and applies its own chat template and sampling values;
- a failing engine raises (CalledProcessError, OSError) or exits with one line; study.py reports it.
impl() imports the module on first use, so a backend that imports models.py (a Windows one will, for its
downloads) can't make an import cycle with models.py, which imports this file.
"""
import sys
from importlib import import_module

NAME = "win32" if sys.platform == "win32" else "darwin"


def impl():
    """The engine module for this platform: backend_mac (MLX, Apple Vision), or backend_win once it exists."""
    return import_module("backend_win" if NAME == "win32" else "backend_mac")
