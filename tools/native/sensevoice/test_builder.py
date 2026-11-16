"""Standard-library integrity checks, run by the native build's CTest."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("build_sensevoice", Path(__file__).resolve().parents[2] / "build_sensevoice.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuildIntegrity(unittest.TestCase):
    def test_patch_context_and_line_counts(self):
        change = "--- a/source\n+++ b/source\n@@ -1,2 +1,2 @@\n one\n-two\n+three\n"
        self.assertEqual(builder.apply_patch("one\ntwo\n", change), "one\nthree\n")
        with self.assertRaises(ValueError):
            builder.apply_patch("changed\ntwo\n", change)
        with self.assertRaises(ValueError):
            builder.apply_patch("one\ntwo\n", change.replace("-1,2", "-1,3"))

    def test_build_reads_unicode_sources_independently_of_windows_locale(self):
        scratch = builder.ROOT / "scratch" / "native-sensevoice"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            root = Path(folder)
            native, cache = root / "adapter", root / "cache"
            native.mkdir()
            lock = {"files": [], "funasr_commit": "a", "llama_commit": "b"}
            (native / "sources.lock.json").write_text(json.dumps(lock), encoding="utf-8")
            for name in ("runtime.patch", "timestamps.h", "cpu_dispatch.h", "cpu_dispatch_test.cpp", "CMakeLists.txt", "timestamps_test.cpp", "windows.manifest"):
                (native / name).write_text("", encoding="utf-8")
            upstream = cache / "upstream"
            fixtures = {"funasr/sensevoice/funasr-sensevoice/funasr-sensevoice.cpp": '// ▁中文\n',
                        "funasr/funasr-common/miniaudio.h": "This software is available as a choice\nlicense",
                        "funasr/LICENSE": "FunASR ©", "llama/LICENSE": "ggml ©"}
            for relative, text in fixtures.items():
                path = upstream / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            executable = cache / "build/bin/pianpian-sensevoice.exe"
            for profile in ("build", "build-avx2"):
                compiled = cache / profile / "bin/pianpian-sensevoice.exe"
                compiled.parent.mkdir(parents=True)
                compiled.write_bytes(b"fake binary " + profile.encode())
            original_read = Path.read_text

            def windows_read(path, encoding=None, **kwargs):
                return original_read(path, encoding=encoding or "cp1252", **kwargs)

            # Compilation is mocked; the regression is the real source/notice staging on a Windows locale.
            with patch.object(Path, "read_text", windows_read), \
                    patch.object(builder, "NATIVE", native), patch.object(builder.sys, "platform", "win32"), \
                    patch.object(builder.shutil, "which", return_value="cmake"), \
                    patch.object(builder.subprocess, "run"), \
                    patch.object(builder.subprocess, "check_output", return_value="test version"):
                output = builder.build(root / "output" / executable.name, cache_dir=cache)
            self.assertEqual(output.read_bytes(), b"fake binary build")
            optimized = output.with_name("pianpian-sensevoice-avx2.exe")
            self.assertEqual(optimized.read_bytes(), b"fake binary build-avx2")
            manifest = json.loads(output.with_name("build-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(set(manifest["variants"]), {"baseline", "avx2"})
            self.assertEqual(manifest["variants"]["avx2"]["sha256"], hashlib.sha256(optimized.read_bytes()).hexdigest())
            self.assertEqual((cache / "build/funasr-sensevoice.cpp").read_text(encoding="utf-8"), '// ▁中文\n')
            self.assertIn("FunASR ©", output.with_name("sensevoice-NOTICES.txt").read_text(encoding="utf-8"))

    def test_source_checksum_failure_never_promotes_download(self):
        entry = {"local": "model/source.cpp", "repo": "owner/repo", "commit": "0" * 40,
                 "path": "source.cpp", "size": 4, "sha256": hashlib.sha256(b"good").hexdigest()}
        scratch = builder.ROOT / "scratch" / "native-sensevoice"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            with patch.object(builder.urllib.request, "urlopen", side_effect=lambda *a, **k: io.BytesIO(b"evil")), \
                    patch.object(builder.time, "sleep"):
                with self.assertRaises(ValueError):
                    builder._fetch(entry, Path(folder))
            self.assertFalse((Path(folder) / entry["local"]).exists())
            with patch.object(builder.urllib.request, "urlopen", return_value=io.BytesIO(b"good")):
                builder._fetch(entry, Path(folder))
            with patch.object(builder.urllib.request, "urlopen", side_effect=AssertionError("cache must be reused")):
                builder._fetch(entry, Path(folder))
        with self.assertRaises(ValueError):
            builder._fetch({**entry, "local": "../escape"}, scratch)


if __name__ == "__main__":
    unittest.main()
