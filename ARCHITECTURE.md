# How Pianpian fits together

```
macOS: Pianpian.app (launcher.py, pywebview/WebKit) · Windows: Pianpian.exe (launcher.py, pywebview/WebView2)
  └── server.py   127.0.0.1 only, Python standard library
        ├── serves   app.html · assets/ · the library folder (with byte ranges, so video can seek)
        └── runs     pipeline/study.py with the engine's Python   (one job at a time, live log)
                       └── yt-dlp · ffmpeg · srt_tool.py · the platform's backend (backend.py: Whisper, OCR, Hy-MT2)
```

`python3 server.py` (or `python server.py` on Windows) runs the same server in a browser tab, without
the window. `app.html` opened straight from disk still plays video files dropped on it; it only needs
the server to make subtitles.

## Two Python environments

- **The app** (`launcher.py`, `server.py`) needs only the standard library plus pywebview for the window.
- **The engine** runs the pipeline. It is the `runtime` dependency group in `pyproject.toml`: pypinyin,
  jieba, zhconv, yt-dlp, imageio-ffmpeg (a static ffmpeg, so no system ffmpeg is needed), and on
  Windows RapidOCR. On macOS it adds mlx-whisper and mlx-lm; torch is left out on purpose (mlx-whisper
  lists it for a conversion tool the app never uses), which keeps that engine at about 700 MB. The
  Windows engine is about 460 MB (measured 24 Oct 2026) and installs neither MLX nor llama-cpp-python.
- **The Windows GPU runtime** is not a Python package: `pipeline/runtimes.py` downloads pinned
  whisper.cpp and llama.cpp Windows builds (CUDA for NVIDIA — the CUDA 12.4 builds, tested with driver
  591.74 — Vulkan for llama.cpp on other GPUs, CPU fallback) into `<data>/runtime` (`$PIANPIAN_RUNTIME`)
  and checks every archive against its SHA-256. whisper.cpp has no Vulkan asset in its official release
  yet, so Vulkan-only machines run speech on the CPU. A GPU build that won't start is retried once with
  the CPU build (`backend_win.py`). Downloads come from GitHub; `PIANPIAN_GITHUB_MIRROR` is an opt-in
  prefix for networks where GitHub is slow — there is no default proxy, because one would see the
  download whenever GitHub fails, and the SHA-256 pins are what keep the bytes safe.

`engine.python()` picks the engine in this order: `$PIANPIAN_PYTHON`, the installed engine in
`<data>/engine` (`Scripts/python.exe` on Windows, `bin/python` on macOS), the repository's `.venv`
(`uv sync --group runtime`), then the Python running the server.

## First run, updates and problems

- `engine.py` holds the paths and settings (`~/Library/Application Support/Pianpian/config.json` on
  macOS, `%LOCALAPPDATA%\Pianpian\config.json` on Windows) and runs the setup that `setup.html` shows:
  Python 3.12 and the packages pinned with hashes in `pipeline/requirements.txt` (or
  `pipeline/requirements-windows.txt`), the GPU runtime on Windows, the dictionary, then the models you
  pick. Each source is timed against its mirror in mainland China and the faster one is used. The engine
  remembers which requirements it was installed from, so a release that changes them sends you back to
  the setup page, which then says "An update for Pianpian" and only fetches what changed (`uv pip sync`).
  Explicit model/cache/runtime environment overrides are captured at app startup; app-derived paths
  follow the chosen data folder before setup checks the catalog or starts downloads.
- `updates.py` asks GitHub for the latest release at most once a day and shows a card in the library
  when there is a newer one, with this platform's file (the DMG on macOS, the installer on Windows) or the release page.
  yt-dlp is updated on its own at most once a week, and from the job card
  when a download fails because the site changed.
- `report.py` turns a failed job's log into a short code and a hint, and builds the Report link: GitHub's
  bug form filled in with redacted details (no home folder, file names, link paths, cookies or
  transcript). Opening the link sends those details to GitHub; Submit publishes the issue. Logs live in
  `~/Library/Logs/Pianpian` on macOS and `<data>\logs` on Windows.

## Packaging and releases

`tools/build_app.py` (`dev.py build`) freezes `launcher.py` with PyInstaller into `dist/Pianpian.app`:
the window, the server, the pages, the pipeline scripts, both locks, `uv`, the OCR helper compiled
from `ocr_frames.swift`, and a `VERSION` file. About 110 MB, 27 MB zipped. The engine and the models
are not inside: the first run installs them. The bundle is signed ad hoc; without a paid Developer ID,
macOS asks once before opening it. Inside the app, `engine.python()` never falls back to
`sys.executable` (that would open a second window), and the server checks static paths by name,
because PyInstaller links the files from `Contents/Frameworks` into `Contents/Resources`.

`Pianpian-macOS.dmg` (the window with the arrow: `tools/dmg/`, built by dmgbuild, which lays the window out itself so it
works on a build server) is what people open and drag to Applications; `Pianpian-macOS.zip` is for updaters and package
managers. The build verifies the signature, and the app never writes `.pyc` files into itself (`engine.py`): that would
break the signature after the first run.

Releases: merging release-please's pull request tags a version and creates the GitHub release; then
`.github/workflows/app.yml` builds the app on an Apple Silicon runner and attaches
`Pianpian-macOS.dmg` and `Pianpian-macOS.zip`; the website and Mac update card prefer the DMG.
`.github/workflows/windows.yml` (`tools/build_app_windows.py`) does the same on windows-latest with
`Pianpian-Windows-Setup.exe` and `Pianpian-Windows.zip`. The installer is per-user (Inno Setup, no
admin) and does not bundle the WebView2 runtime — Windows 11 includes it, and the evergreen
bootstrapper link always serves the newest build, so a pinned hash would go stale. The update card
(`updates.py`) offers each platform only its own files (Windows: the installer, then the zip) and
links the release page when a release has none.

Website visits and Download clicks are counted by [Umami Cloud](https://cloud.umami.is) (no cookies): its script is in `site/index.html` only,
never in `app.html`, so the app itself sends nothing to it. Real download totals come from the release files' own counters
(`gh api repos/conradomateu/pianpian/releases`). Not tested: how many mainland China visitors the script reaches.

## Models

`pipeline/models.py` downloads the models once into `<data>/models` (`$PIANPIAN_MODELS`;
`~/.cache/pianpian/models` from the command line), pinned file by file in
`pipeline/models.lock.json` (`dev.py lock` targets both platforms; full regeneration on macOS is not tested). The lock has
a `darwin` and a `win32` section, and so do the catalog rows (`backend.NAME`); `models.default(task)`
picks this platform's model:

| | macOS | Windows |
|---|---|---|
| Speech | Whisper large-v3-turbo, MLX (1.6 GB) | `ggml-large-v3-turbo.bin` for whisper.cpp (1.6 GB) |
| Translation | Hy-MT2 1.8B 4-bit, MLX (1.0 GB) | `Hy-MT2-1.8B-Q4_K_M.gguf` for llama.cpp (1.1 GB) |

Each file comes from ModelScope first, which is fast from mainland China — the Windows models are
mirrored there under other ids (`OllmOne/whisper.cpp`, `Tencent-Hunyuan/Hy-MT2-1.8B-GGUF`; the pinned
files are byte-identical to Hugging Face's, checked 31 Oct 2026) — then Hugging Face, then
hf-mirror.com. Every file is checked against the size and SHA-256 in the lock. Stopped downloads
resume. A model already in the Hugging Face cache is used where it is. Progress goes to stdout as
`@progress {json}` lines. The Windows binaries are pinned separately in `pipeline/runtimes.py`
(release tag, size, SHA-256).

## The pipeline

`pipeline/study.py <link or file> [browser]` makes one study folder. Each step is skipped when its
output is newer than its inputs, so it can run again after `zh.srt` is fixed by hand.

1. **Video**: yt-dlp, H.264 first (AV1 does not play everywhere), plus the platform's Chinese
   subtitles if any. A browser name borrows that browser's Bilibili login for the AI subtitles.
2. **Chinese**: the platform's subtitles, else OCR when the Chinese is burned into the picture
   (macOS Vision; RapidOCR on Windows — not run there yet), else Whisper with word timestamps (MLX on
   macOS, whisper.cpp on Windows). `srt_tool.py split` cuts long lines at word boundaries.
3. **Pinyin and words**: pypinyin and jieba, with `pinyin_fixes.txt` on top. `zh.words.json` holds
   each word's pinyin, CC-CEDICT gloss, HSK level and measure words, the tense tags from `grammar.py`
   and Whisper's word times (for the spoken-word highlight).
4. **English**: `translate_srt.py` runs Hy-MT2 line by line (MLX on macOS, `llama-server` on Windows),
   with the title and the previous lines as context, so every English line keeps its Chinese line's
   timing. `align_srt.py` then links English words to Chinese words where the dictionary can't.
5. **study.mkv**: every track in one file, for IINA, mpv or VLC.

The model engines sit behind `pipeline/backend.py`, the only platform check in `pipeline/`:
`backend.impl()` is `backend_mac.py` (mlx-whisper, mlx-lm, macOS OCR) or `backend_win.py` (whisper.cpp,
llama.cpp's `llama-server`, RapidOCR) and gives three functions,
`transcribe()`, `translator()` (a context manager yielding `generate(prompt, temperature, max_tokens)`)
and `ocr()`. The steps above call those, so the prompt, the per-line loop and the line cutting are the
same for every engine. `tests/test_backend.py` has the checks a new backend reuses (the signature
test and the `assert_*` output helpers) and adds its own cases to.
`align_srt.py` reads the model's hidden states and is MLX only; elsewhere it stops and the dictionary
links stay.

## State

Everything lives in the video's folder, so the app and the command line always agree: `source.*`,
`title.txt`, `source.url`, `.hardsubs`, `.english-auto`, `.from-whisper`, `.split`, the `.srt` tracks,
`zh.words.json`, `zh.align.json`, `en.lines.txt` and `study.mkv`. The first Anki export adds
`.pianpian-source-id`, a UUID that moves with the folder. Jobs live in memory.

## Anki export

`assets/player.js` owns Chinese cue/token selection; `assets/anki.js` owns the editable draft in the
existing menu row. `anki_export.py` validates library paths, current transcript anchors and audio
intervals, extracts MP3 with FFmpeg, and calls `anki_connect.py` (stdlib, AnkiConnect legacy v6 over
127.0.0.1). Settings under `anki` in the app config hold the port, optional API key and last deck.
The status endpoint reports whether an Anki collection is usable, rather than guessing from installed apps.

The preview URL is required on export and must match the source path/size/mtime and exact interval.
Preview MP3s live in `engine.cache_dir()/anki`, limited to 128 files; clips are limited to 120 seconds.
The same bytes are uploaded to Anki. With raw Whisper data, old word timings are repaired in memory by
`srt_tool.py retime`; failure removes word bounds so the player offers sentence audio. User files stay intact.

`PianpianId` hashes the source UUID and normalized transcript character offsets/text. Editable meanings,
audio margins and folder names do not change it. An existing occurrence requires an explicit update.
Updates keep the note/card identities, scheduling, tags and deck; writes are serialized and never
automatically retried. A lost response is resolved by looking up that occurrence on the next attempt.
Anki's separate API calls are not transactional: profile checks run between calls, but a profile switch
during one call cannot be made atomic; an interrupted export may leave unused media.

The `Pianpian` note type has `PianpianId`, `Expression`, `Pinyin`, `Meaning`, `Sentence`, `Translation`,
`Audio` and `Source`. Text is HTML-escaped; the server generates the audio reference and optional
highlight spans from a fixed palette (`none`, `jade`, `coral`, `blue`, `gold`). Highlighting affects
Expression and literal matches in Sentence, without changing the note schema. Matching happens
before HTML escaping, so entities cannot be split by a selected word. Inline highlights inherit text color.
The player supplies optional `tones` segments for `pinyin` and `expression`: `[text, tone]`, where 0 is
plain and 1–5 use the same light/dark palette as `kit.css`. The server validates that segments reconstruct
their plain field exactly, then escapes them and adds fixed namespaced styles. Styles travel with the
fields, so existing note templates and user styling are not replaced. Pinyin colors default on; Chinese
colors are optional and also follow literal Expression matches in Sentence. Unaligned text stays plain.
Drafts survive API errors in the open page, not reloads or selection changes. Export is one-way.
The icon-only Anki menu opens a compact popover with a persistent selection header and save footer.
Its `open(anchor)` method is shared by the toolbar and pinned-word action (`onAnkiOpen`); dismissal
keeps the draft and pauses preview audio. Audio limits, text/color and connection controls are folded.
The extraction layer handles audio-only sources; the library UI still imports video. Windows executable
layout is unit-tested on macOS; execution on Windows remains untested.

## Server API

| Method | Path | Does |
|---|---|---|
| GET | `/api/status` | Version, library folder, engine ready or not, platform (`win32`/`darwin`), subtitle accelerator (CUDA/Vulkan/CPU or MLX), installed browsers, busy |
| GET | `/api/videos` | Library folders with title, link, HSK level and the tracks they have |
| GET | `/api/videos/<id>` | One video, plus its `zh.lines.txt` for translating by hand |
| GET | `/api/jobs` | Recent jobs with their state and the end of their log |
| POST | `/api/add` | `{url, browser, translate}`: download and make subtitles |
| PUT | `/api/import?name=…` | The body is a video file: copy it into the library and make subtitles |
| POST | `/api/videos/<id>/translate` | English from the local model, then rebuild |
| POST | `/api/videos/<id>/english` | `{text}`: save a hand-made `en.lines.txt`, then rebuild |
| POST | `/api/videos/<id>/split` | `{max}`: cut the lines again (0 = as transcribed) |
| POST | `/api/videos/<id>/rebuild` | Run the pipeline again |
| POST | `/api/videos/<id>/open` | Show the folder in Finder (macOS) or Explorer (Windows) |
| GET | `/api/anki/status` | Connection state, decks, profile and public connection settings |
| GET | `/api/anki/audio/<name>.mp3` | Cached preview with byte-range support |
| POST | `/api/anki/settings` | Save local port and optional API key; check connection |
| POST | `/api/anki/preview` | Validate selection and interval, extract original audio |
| POST | `/api/anki/export` | Add, detect an existing occurrence, or explicitly update it |
| POST | `/api/anki/open` | Open the exported note in Anki's browser |

Safety: the server listens on 127.0.0.1 only. Requests that change anything need an `X-Kit: 1`
header, so other websites can't start jobs. Video ids and paths are checked, and commands run
without a shell.

## The page

`app.html` is the only screen: library on the left (B), video and its menus in the middle, transcript
on the right (T). `assets/player.js` is the player, `assets/kit.css` the design tokens and
`assets/kit.js` small shared helpers. There is no framework and no build step.

### Playback state and loading

The shared player owns loading, buffering and retry feedback. The app owns library selection:
new selections cancel older requests. The video starts loading alongside the subtitles, dictionary
and alignment data; late study data is attached without restarting playback. A subtitle failure
offers a separate retry while the video remains playable. The player uses a separate 1280px-wide
`poster.jpg`; the library keeps its 480px-wide `thumb.jpg`. The local server generates either image
on demand from the video and caches it in the video folder. Buffering keeps the current frame visible.

Playback uses the browser's progressive MP4 support, with HTTP byte ranges on both GitHub Pages
and the local server. `preload="metadata"` hints at a small initial download; the browser decides
how much to buffer. The self-made demo has its MP4 index first (`faststart`) and ships both images.
New links still download through yt-dlp before processing; this does not stream an unfinished download.

Library playback positions and the last opened video are saved in browser local storage. Reopening
restores the last available video, paused; an explicit `#v=…&t=…` link takes precedence. The website
demo starts fresh. Dropped files are not reopened automatically because browser file access does
not survive a restart. If storage is unavailable, playback still works without memory.
`launcher.py` disables pywebview's private mode and supplies `engine.data_dir() / "webview"` for
persistent browser storage. Storage is origin-specific: the launcher's fallback port has separate
state. These changes use browser APIs and pywebview's cross-platform options; Windows native
behavior has not been tested.

Verified on 1 Nov 2026: Chrome browser regressions use the self-made demo and real clicks for
playback, word definitions, video selection and retry; they also check resume, timestamp links,
missing videos, blocked storage and overlapping selections. A separate macOS pywebview/WebKit
check saved 13.2 seconds, closed the window process, then restored 13.2 seconds paused in a new
process. Those browser regressions exercise buffer feedback with simulated media events.

Verified on 7 Nov 2026 with Chrome and the self-made demo: both the published site and the local
server answered head and tail byte ranges with 206. At 32 KB/s and 150 ms simulated latency,
playback started with roughly 4–5 of 44.8 seconds buffered. Throttling the local player to 1 byte/s
produced a real media stall, showed buffering feedback, and recovered when the limit was lifted.

On narrow screens the website measures its same-origin demo's content height, including open
menus, so the host page scrolls normally and only the transcript has a bounded scroll area.
The decorative window bar has its own class, separate from the shared sticky navigation style.
Verified on 1 Nov 2026 with Chrome at 320, 390 and 768 CSS pixels, including an actual dropdown
click and navigation stacking. Physical iPhone/Android browsers have not been tested.
