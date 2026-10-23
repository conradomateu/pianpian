# AGENTS.md: Pianpian 片片

Instructions for AI coding agents (Claude Code, Codex, OpenCode…). `CLAUDE.md` imports this file, so keep project instructions **here** and nowhere else.

## What this is

A Mandarin study app: a video becomes Chinese + pinyin + English subtitles you can click, all made on the Mac with local models. A local Python server and one page, in a native window (pywebview), shipped as `Pianpian.app`; the pipeline runs in its own engine environment, installed on first run.
- How it fits together (engine, setup, updates, reports, packaging, API): [`ARCHITECTURE.md`](ARCHITECTURE.md). What users see: [`README.md`](README.md).

## Load-bearing facts

| | |
|---|---|
| Check | `python3 dev.py check` (ruff + node --check + pytest), the same as CI (`.github/workflows/ci.yml`) |
| Run | `python3 server.py` → http://127.0.0.1:8770/app.html (`--no-browser` for agents). Dev app: `python3 dev.py app` → `~/Applications/Pianpian.app` (runs this checkout, port 8771). Release build: `python3 dev.py build` → `dist/Pianpian.app` + zip. Website: `python3 dev.py preview` → http://127.0.0.1:8765 |
| Library | One folder per video (default `~/Movies/Pianpian/<video>/`, set in the first-run setup): `source.mp4`, `zh.srt`, `zh.pinyin.srt`, `zh.en.srt`, `zh.words.json`, `zh.align.json`, `study.mkv`. Demo: `demo/library/` (`tools/demo/make_demo.py`) |
| Models | Whisper `mlx-community/whisper-large-v3-turbo` · Hy-MT2 `mlx-community/Hy-MT2-1.8B-4bit`, pinned in `pipeline/models.lock.json`; the app keeps them in `<data>/models`, and also uses `~/.cache/mandarin-kit/models/` and the Hugging Face cache · CC-CEDICT in `~/.cache/mandarin-kit/` |
| Platform | macOS Apple Silicon only today (MLX, Vision OCR). Windows is planned: keep new code platform-neutral (see Rules) |
| Network | Many users are in mainland China, where PyPI, GitHub and Hugging Face are slow or blocked. The app times each source against its mirror (`engine.mirrors()`); models come from ModelScope first. For development there, set `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple` |
| Name | Pianpian 片片 (piànpiàn, "piece by piece"). Tagline 一天一片. Domain planned: pianpian.app. Logo: `design/icons/20-pianpian-watermelon.svg` |

## How the code fits

- `server.py`: stdlib HTTP server on 127.0.0.1 (`LocalServer`, which skips a slow reverse DNS lookup). One job queue, byte-range video streaming, an `X-Kit: 1` header guard on POSTs (CSRF) and path checks on every file it serves (by name: inside the app, files are links).
- `engine.py` (paths, settings, first-run setup), `updates.py` (new version, yt-dlp), `report.py` (hints and redacted reports): standard library only, shared by the server and the app.
- `pipeline/study.py` runs the steps with the engine's Python (`engine.python()`: the installed engine, or this repo's `.venv` from `python3 dev.py engine`). Each step is skipped when its output is newer than its inputs. The engine's packages are pinned in `pipeline/requirements.txt` (`python3 dev.py lock`).
- `assets/player.js` is the player (`SubPlayer.mount`); its menus are `<details class="dd">` and `app.html` adds the Video menu through `player.extra`. Word links come from `zh.words.json` (dictionary) and `zh.align.json` (model vectors).
- **One screen only** (`app.html`), laid out like a desktop app: a library panel on the left, the video with one row of dropdowns in the middle, a transcript panel on the right. Both panels are the same component (`.panel` + a fixed `.ptoggle` in its top corner, `setPanel()`, keys B and T). Don't add pages, a nav bar or a title bar; new controls go into a dropdown.
- Folding uses `Kit.flip` (FLIP: change the layout at once, glide with transforms). Anything that scrolls must not clip content while it glides (the `gliding` class).
- Motion uses `--ease` in `kit.css`, animates `width`/`opacity`/`transform` (not grid tracks, which jump), and is switched off by `prefers-reduced-motion`.
- No build step and no frameworks: `app.html` must open from disk.
- `zh.words.json` v2 (made by `srt_tool.py words`): each Chinese word is `[zh, pinyin, meaning, HSK level (0 = not listed), measure words]`, each cue has `g` (per line: `[[char index, tag], …]` from `pipeline/grammar.py`) and, for Whisper videos, `k` (per line, `[start, end]` per word, 0 if unknown), the file has `hsk` (the video's level). Change the format and you must regenerate it for every video.
- Grammar tags are heuristics: add a sentence to `tests/test_grammar.py` for every rule you change (`uv run --with jieba --with pytest pytest tests/`).

## Rules

1. **Never present inference as fact.** Say what was tested, on what and when, and mark the rest "not tested" or "to check", in the code comments, the docs and the UI.
2. **Keep `core` logic free of platform code.** Path handling, OCR, "reveal in Finder" and model engines live behind small interfaces so a Windows version can swap them. No hard-coded `~/Library` paths outside `engine.py`.
3. **Models are swappable.** A new model means a catalog entry and, if needed, an adapter that passes the engine's contract tests. Don't call a specific model from UI code.
4. **Don't ship other people's content.** No Bilibili videos, textbook material or AnkiWeb decks in the repo, screenshots or tests. Use the self-made demo library.
5. **Pinyin fixes go in `pipeline/pinyin_fixes.txt`**, not in code.
6. **Prefer absolute dates** (22 Oct 2026), never "next week".
7. **Commits:** `feat:` / `fix:` / `docs:` / `chore:` prefixes (release-please reads them, and `python3 dev.py version` previews the version they will make: `fix:` → patch, `feat:` → minor, `feat!:` or a `BREAKING CHANGE:` line → major, minor while the version starts with 0; `docs:` `chore:` `style:` `refactor:` `test:` `build:` `ci:` make no release by themselves; a `Release-As: 0.1.1` line at the end of a message forces the number). No personal data in messages, and no AI co-author trailers. Plans and handoff notes stay out of the repository.
8. **Test runs live in `scratch/`** (git-ignored, inside the project): throwaway homes, downloaded videos and builds under test. Not in `/tmp`, which gets cleaned; never commit what is in there.
9. **Verify UI changes in a real browser**, with a real click and not only a JS call. The video control bar once swallowed clicks on subtitle words.

Personal, machine-specific notes go in `CLAUDE.local.md` (git-ignored), not here.
