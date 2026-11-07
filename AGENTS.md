# AGENTS.md: Pianpian 片片

Instructions for AI coding agents (Claude Code, Codex, OpenCode…). `CLAUDE.md` imports this file, so keep project instructions **here** and nowhere else.

## What this is

A Mandarin study app: a video becomes Chinese + pinyin + English subtitles you can click, all made on your own computer with local models. A local Python server and one page, in a native window (pywebview), packaged as `Pianpian.app` on macOS and a per-user `Pianpian-Windows-Setup.exe` installer on Windows; the pipeline runs in its own engine environment, installed on first run.
- How it fits together (engine, setup, updates, reports, packaging, API): [`ARCHITECTURE.md`](ARCHITECTURE.md). What users see: [`README.md`](README.md).

## Load-bearing facts

| | |
|---|---|
| Check | `python3 dev.py check` (macOS/Linux) or `python dev.py check` (Windows): ruff + node --check + pytest, the same as CI (`.github/workflows/ci.yml`) |
| Run | `python3 server.py` / `python server.py` → http://127.0.0.1:8770/app.html (`--no-browser` for agents). Dev app: `python3 dev.py app` (`~/Applications/Pianpian.app`) on macOS; `python dev.py app` (launcher.py) on Windows, port 8771. Release build: `python3 dev.py build` → `dist/Pianpian.app` + zip (macOS); `python dev.py build` → `dist/Pianpian-Windows-Setup.exe` + zip (Windows, needs Inno Setup 6). Website: `python3 dev.py preview` → http://127.0.0.1:8766 (8765 is AnkiConnect) |
| Library | One folder per video (default `~/Movies/Pianpian/<video>/` on macOS, `%USERPROFILE%\Videos\Pianpian\<video>` on Windows; set in the first-run setup): `source.mp4`, `zh.srt`, `zh.pinyin.srt`, `zh.en.srt`, `zh.words.json`, `zh.align.json`, `study.mkv`. Demo: `demo/library/` (`tools/demo/make_demo.py`) |
| Models | macOS: Whisper `mlx-community/whisper-large-v3-turbo` · Hy-MT2 `mlx-community/Hy-MT2-1.8B-4bit`. Windows: `ggerganov/whisper.cpp` `ggml-large-v3-turbo.bin` · `tencent/Hy-MT2-1.8B-GGUF` `Q4_K_M`. Pinned by platform in `pipeline/models.lock.json`; the app keeps them in `<data>/models`, and also uses `~/.cache/mandarin-kit/models/` and the Hugging Face cache · CC-CEDICT in `<data>/cache` in the app (`PIANPIAN_CACHE`), `~/.cache/mandarin-kit/` by default from the CLI |
| Windows runtime | whisper.cpp `b5454` and llama.cpp `b11851` prebuilt Windows x64 archives, pinned by size/SHA-256 in `pipeline/runtimes.py`; `.complete` records release and hashes, pin changes replace the whole build. Setup saves `accel` for jobs; CUDA for NVIDIA, Vulkan for llama.cpp on other GPUs, CPU fallback. Data defaults to `%LOCALAPPDATA%\Pianpian`; settings/logs stay there when data moves. Engine: `<data>\engine`. Earlier Windows 11 25H2/RTX 4060 reports do not validate the current integration: [test history](ARCHITECTURE.md#windows-test-history). Windows 10 is untested; installer rejects ARM64; no Vulkan-whisper build |
| Platform | macOS Apple Silicon (MLX, Vision OCR) and Windows x64 (whisper.cpp, llama.cpp, RapidOCR). Keep platform code behind `engine.py` (app side) and `pipeline/backend.py` (pipeline side) — see Rules |
| Network | Many users are in mainland China, where PyPI, GitHub and Hugging Face are slow or blocked. The app times each source against its mirror (`engine.mirrors()`); models come from ModelScope first (the Windows models are mirrored there under other ids), then Hugging Face, then hf-mirror.com; runtime binaries from GitHub, with `PIANPIAN_GITHUB_MIRROR` as an opt-in prefix. For development there, set `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple` |
| Name | Pianpian 片片 (piànpiàn, "piece by piece"). Tagline 一天一片. Domain planned: pianpian.app. Logo: `design/icons/20-pianpian-watermelon.svg` |

## How the code fits

- `server.py`: stdlib HTTP server on 127.0.0.1 (`LocalServer`, which skips a slow reverse DNS lookup). One job queue, byte-range streaming, local `Host` checks against DNS rebinding, `X-Kit: 1` on POST/PUT. Cross-origin status exposes only `ok`/`version`; app assets are checked by name (bundle links), library files by resolved path. Setup and queued pipeline/downloader jobs exclude each other (409 on conflict).
- `engine.py` (paths, settings, first-run setup, browsers, reveal-in-folder), `updates.py` (new version, yt-dlp), `report.py` (hints and redacted reports): standard library only, shared by the server and the app. App data and settings paths live in `engine.py`; it defines `WINDOWS`, the one platform check on the app side.
- `pipeline/study.py` runs the steps with the engine's Python (`engine.python()`: the installed engine, or this repo's `.venv` from `python3 dev.py engine` / `python dev.py engine`). Each step is skipped when its output is newer than its inputs. The engine's packages are pinned in `pipeline/requirements.txt` (macOS) and `pipeline/requirements-windows.txt`; `python dev.py lock` targets both platforms; full lock regeneration on macOS is not tested. The model engines sit behind `pipeline/backend.py` (`backend.impl()`: `transcribe`, `translator`, `ocr`, optional `align` on macOS; `backend_mac.py`, `backend_win.py`), the only platform check in `pipeline/`. The pipeline never imports `engine.py`; values travel through `engine.pipeline_env()` (`PIANPIAN_MODELS`, `PIANPIAN_CACHE`, Windows `PIANPIAN_RUNTIME` and `PIANPIAN_ACCEL`).
- Setup recreates a broken interpreter/venv, not one whose imports fail or startup probe times out; package sync repairs imports. Data-folder changes move downloads into empty destinations and recreate the engine, offering recognized old engine/Python folders for cleanup. Library selection does not move videos. Config writes use `0600` on POSIX; Windows ACL privacy is not established by that mode.
- On Windows, `pipeline/runtimes.py` downloads and verifies the pinned whisper.cpp and llama.cpp builds (a GPU build that won't start is retried once on the CPU build); `backend_win.py` turns whisper.cpp's JSON into the same `zh.whisper.json`, starts `llama-server` for Hy-MT2 and runs RapidOCR. Do not fetch an executable without a pinned size and SHA-256.
- `assets/player.js` is the player (`SubPlayer.mount`); its menus are `<details class="dd">` and `app.html` adds the Video menu through `player.extra`. Word links come from `zh.words.json` (dictionary) and `zh.align.json` (model vectors).
- **One screen only** (`app.html`), laid out like a desktop app: a library panel on the left, the video with one row of dropdowns in the middle, a transcript panel on the right. Both panels are the same component (`.panel` + a fixed `.ptoggle` in its top corner, `setPanel()`, keys B and T). Don't add pages, a nav bar or a title bar; new controls go into a dropdown.
- Website demo only: at ≤600 CSS pixels, `html.demo` hides library/toggles/menus, shows three subtitle switches, the transcript below the video and a dismissible word sheet. Keep this simplified UI scoped to the demo; physical phone browsers remain untested.
- Folding uses `Kit.flip` (FLIP: change the layout at once, glide with transforms). Anything that scrolls must not clip content while it glides (the `gliding` class).
- Motion uses `--ease` in `kit.css`, animates `width`/`opacity`/`transform` (not grid tracks, which jump), and is switched off by `prefers-reduced-motion`.
- No build step and no frameworks: `app.html` must open from disk.
- `zh.words.json` v2 (made by `srt_tool.py words`): each Chinese word is `[zh, pinyin, meaning, HSK level (0 = not listed), measure words]`, each cue has `g` (per line: `[[char index, tag], …]` from `pipeline/grammar.py`) and, for Whisper videos, `k` (per line, `[start, end]` per word, 0 if unknown), the file has `hsk` (the video's level). Change the format and you must regenerate it for every video.
- `srt_tool.segment_words()` refines unknown jieba compounds with CC-CEDICT; pinyin, word JSON and macOS model alignment share it. Keep their boundaries and freshness dependencies together when changing segmentation. Retain the demo's `zh.whisper.json` so regenerated words keep spoken timings.
- Grammar tags are heuristics: add a sentence to `tests/test_grammar.py` for every rule you change (`uv run --with jieba --with pytest pytest tests/`).

## Rules

1. **Never present inference as fact.** Say what was tested, on what and when, and mark the rest "not tested" or "to check", in the code comments, the docs and the UI.
2. **Keep `core` logic free of platform code.** Path handling, OCR, reveal-in-folder and model engines live behind small interfaces shared by the macOS and Windows implementations. No hard-coded `~/Library` paths outside `engine.py`.
3. **Models are swappable.** A new model means a catalog entry (`pipeline/models.py`, with its `platform`) and, if needed, a backend module checked by `tests/test_backend.py` (the signature test, the `assert_*` output helpers, and its own cases). Don't call a specific model from UI code.
4. **Don't ship other people's content.** No Bilibili videos, textbook material or AnkiWeb decks in the repo, screenshots or tests. Use the self-made demo library.
5. **Pinyin fixes go in `pipeline/pinyin_fixes.txt`**, not in code.
6. **Prefer absolute dates** (22 Oct 2026), never "next week".
7. **Commits:** `feat:` / `fix:` / `docs:` / `chore:` prefixes (release-please reads them, and `python3 dev.py version` previews the version they will make: `fix:` → patch, `feat:` → minor, `feat!:` or a `BREAKING CHANGE:` line → major, minor while the version starts with 0; `docs:` `chore:` `style:` `refactor:` `test:` `build:` `ci:` make no release by themselves; a `Release-As: 0.1.1` line at the end of a message forces the number). No personal data in messages, and no AI co-author trailers. Plans and handoff notes stay out of the repository.
8. **Test runs live in `scratch/`** (git-ignored, inside the project): throwaway homes, downloaded videos and builds under test. Not in `/tmp`, which gets cleaned; never commit what is in there.
9. **Verify UI changes in a real browser**, with a real click and not only a JS call. The video control bar once swallowed clicks on subtitle words.

Personal, machine-specific notes go in `CLAUDE.local.md` (git-ignored), not here.
