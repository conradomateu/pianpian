"""Guard the complete installer graph, including transitive dependencies."""
import re
from pathlib import Path

import pytest


@pytest.mark.parametrize("filename", ["requirements.txt", "requirements-windows.txt"])
def test_engine_lock_contains_only_the_five_shared_pipeline_packages(filename):
    lock = Path(__file__).resolve().parents[1] / "pipeline" / filename
    packages = set(re.findall(r"^([a-z0-9_-]+)==", lock.read_text(), re.MULTILINE))
    assert packages == {"imageio-ffmpeg", "jieba", "pypinyin", "yt-dlp", "zhconv"}
    # Check generated locks: inspecting only direct dependencies would miss these downloads.
    forbidden = {"mlx-whisper", "openai-whisper", "numba", "llvmlite", "tiktoken", "torch", "torchaudio", "triton", "rapidocr-onnxruntime"}
    assert not packages & forbidden
    assert not any(name.startswith(("nvidia-", "cuda-", "cupy")) for name in packages)
