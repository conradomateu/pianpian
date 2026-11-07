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
  whisper.cpp and llama.cpp Windows builds (CUDA for NVIDIA — the CUDA 12.4 builds were reported tested
  on 27 Oct 2026 with an RTX 4060 Laptop, driver 591.74 — Vulkan for llama.cpp on other GPUs, CPU fallback) into `<data>/runtime` (`$PIANPIAN_RUNTIME`)
  and checks every archive against its SHA-256. whisper.cpp has no Vulkan asset in its official release
  yet, so Vulkan-only machines run speech on the CPU. A GPU build that won't start is retried once with
  the CPU build (`backend_win.py`). Downloads come from GitHub; `PIANPIAN_GITHUB_MIRROR` is an opt-in
  prefix for networks where GitHub is slow — there is no default proxy, because one would see the
  download whenever GitHub fails, and the SHA-256 pins are what keep the bytes safe.
  Each build's `.complete` records the tool, backend, release and archive SHA-256s. A changed pin makes
  the installed build stale; setup downloads and unpacks a replacement before replacing the whole
  build folder, so old DLLs do not survive an upgrade. A failed download leaves the old folder intact.
  Setup saves its GPU choice as `accel` in the config and passes it to every Windows job through
  `PIANPIAN_ACCEL`; an explicit environment override wins. Vulkan still means CPU speech recognition.

`engine.python()` picks the engine in this order: `$PIANPIAN_PYTHON`, the installed engine in
`<data>/engine` (`Scripts/python.exe` on Windows, `bin/python` on macOS), the repository's `.venv`
(`python dev.py engine`), then the Python running the server (source runs only).

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
- **Repair:** setup recreates the engine only when its Python or `pyvenv.cfg` is missing, or the
  interpreter cannot launch or exits with an error on `python -c "pass"`. A slow interpreter probe
  timing out does not trigger deletion. Failed imports are repaired by package sync. A nonempty folder
  without a venv config or Pianpian requirements stamp is refused rather than deleted.
- **Moving data:** choosing a new data folder moves `models/`, `runtime/` and `cache/` when their
  destinations are empty and outside the source folders; explicit path overrides stay put. Setup
  recreates the engine in the new location because venv paths are absolute. Recognized old `engine/`
  and managed `python/` folders are offered under **Delete old files**, checked by default. A nonempty
  destination is not merged; the source stays. Cross-disk moves have not been tested. Changing the
  library setting selects a folder; it does not move existing videos.
- Settings stay in the support folder named above, even when the data folder changes. `save_config()`
  serializes read/merge/write operations across threads in the app process, then atomically replaces
  `config.json` with POSIX mode `0600` (owner read/write only). The optional AnkiConnect
  API key is stored there in clear text. Windows privacy depends on filesystem ACLs; these are neither
  set by that mode nor verified by the POSIX permissions test.
- `updates.py` asks GitHub for the latest release at most once a day and shows a card in the library
  when there is a newer one, with this platform's file (the DMG on macOS, the installer on Windows) or the release page.
  yt-dlp is updated on its own at most once a week, and from the job card
  when a download fails because the site changed.
- `report.py` turns a failed job's log into a short code and a hint, and builds the Report link: GitHub's
  bug form filled in with redacted details: filters remove home/library paths, known video names,
  link paths, cookies and recognized transcript lines. Redaction is pattern-based, not a guarantee
  against every tool's output format. Opening the link sends those details to GitHub; Submit publishes the issue. Logs live in
  `~/Library/Logs/Pianpian` on macOS and `%LOCALAPPDATA%\Pianpian\logs` on Windows; with
  `PIANPIAN_HOME`, settings and logs use that support folder. Changing the data folder does not move logs.

## Packaging and releases

`tools/build_app.py` (`dev.py build`) freezes `launcher.py` with PyInstaller into `dist/Pianpian.app`:
the window, the server, the pages, the pipeline scripts, both locks, `uv`, the OCR helper compiled
from `ocr_frames.swift`, and a `VERSION` file. Measured on 7 Nov 2026: 57 MB of files (bundle links counted once), 27 MB zipped. The engine and the models
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
`Pianpian-Windows-Setup.exe` and `Pianpian-Windows.zip`. Both build scripts use an isolated uv environment
with PyInstaller 6.22.3 and pywebview 6.2.1; CI bundles uv 0.13.7. The Windows build needs Inno Setup 6
for the installer; without it (or with `--no-installer`) it produces the app folder and zip only.
The installer is per-user (no admin), allows x64 Windows 10 or newer, and rejects ARM64 and 32-bit Windows.
It replaces `{app}\_internal` on upgrade and checks the `PianpianApp` mutex held by the frozen app,
which also refuses a second instance. Engine, models and user data live outside the installation folder;
uninstalling the app leaves them there. WebView2 is required but not bundled — Windows 11 normally
includes it; Windows 10 users may need to install it separately. The update card
(`updates.py`) offers each platform only its own files (Windows: the installer, then the zip) and
links the release page when a release has none.

Each platform's release workflow rebuilds the website after uploading its files. `tools/build_site.py`
reads release assets at build time: it offers the Windows installer only when attached, otherwise a
release-page link. `assets/site-os.js` orders and emphasizes download links using browser platform hints;
this is a compatibility hint, not a hardware test. Windows CI installs the hashed Windows engine lock
before running `dev.py check` with `UV_NO_SYNC=1`.

### Windows test history

These are reports for earlier builds, **not acceptance of the current integrated build**:

- **24 Oct 2026:** demo pipeline on Windows 11 Pro 25H2, Ryzen 9 7940HS, 16 GB RAM, RTX 4060 Laptop
  8 GB, driver 591.74. This predates the rewritten integration; see [PR #11](https://github.com/conradomateu/pianpian/pull/11).
- **7 Nov 2026, source:** Windows 11 25H2 build 26200, Ryzen 9 7940HS, RTX 4060 Laptop, driver 591.74;
  `8db674f` plus `c7fe9d4`, `30548ce` and `92fc4f1`. Reported: clean-checkout launch, a Chinese-filename
  job through the native window, forced GPU startup failures retrying on CPU without leftover processes,
  no console flashes during jobs, and YouTube merging with the engine's ffmpeg. On a 16.5-minute Mandarin
  talk, whisper.cpp `-mc 0` repeated less than default context; both lacked punctuation.
- **7 Nov 2026, earlier installer:** Windows 11 25H2 x64; build, silent per-user install without admin,
  installed WebView2 window/server launch and uninstall were reported successful. The installer wizard
  and SmartScreen warning were not exercised. This predates the x64-only gate, upgrade cleanup, mutex
  and isolated pinned build changes. The full first-run setup console watch was still pending.

As of **7 Nov 2026**, the integrated app, revised installer, engine repair/data migration and security
changes have not been exercised natively on Windows. The integration reports use macOS Apple Silicon
tests, including simulated Windows paths/processes. RapidOCR, Anki export, Windows 10, AMD/Intel Vulkan
inference and mainland-China Windows first-run downloads remain untested. Windows ARM64 is unsupported.

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
   (macOS Vision; RapidOCR on Windows — not tested there as of 7 Nov 2026), else Whisper with word timestamps (MLX on
   macOS, whisper.cpp on Windows). `srt_tool.py split` cuts long lines at word boundaries.
3. **Pinyin and words**: pypinyin and dictionary-refined jieba segmentation, with `pinyin_fixes.txt` on top. `zh.words.json` holds
   each word's pinyin, CC-CEDICT gloss, HSK level and measure words, the tense tags from `grammar.py`
   and Whisper's word times (for the spoken-word highlight).
4. **English**: `translate_srt.py` runs Hy-MT2 line by line (MLX on macOS, `llama-server` on Windows),
   with the title and the previous lines as context, so every English line keeps its Chinese line's
   timing. On macOS, `align_srt.py` then links English words to Chinese words where the dictionary can't.
5. **study.mkv**: every track in one file, for IINA, mpv or VLC.

`srt_tool.segment_words()` keeps known CC-CEDICT words whole and splits unknown Chinese jieba
compounds into the longest dictionary parts, preserving unmatched text: `今天天气` becomes `今天 天气`.
Pinyin overrides and V一V constructions stay whole; without the dictionary, jieba's boundaries remain.
Pinyin tracks, word JSON and macOS model alignment share these boundaries. This is a greedy dictionary
heuristic, not a linguistic parser; it can also split names or reduplications absent from the dictionary.

The model engines sit behind `pipeline/backend.py`, the only platform check in `pipeline/`:
`backend.impl()` is `backend_mac.py` (mlx-whisper, mlx-lm, macOS OCR) or `backend_win.py` (whisper.cpp,
llama.cpp's `llama-server`, RapidOCR) and requires three functions,
`transcribe()`, `translator()` (a context manager yielding `generate(prompt, temperature, max_tokens)`)
and `ocr()`. The steps above call those, so the prompt, the per-line loop and the line cutting are the
same for every engine. `tests/test_backend.py` has the checks a new backend reuses (the signature
test and the `assert_*` output helpers) and adds its own cases to.
The optional `align(zh_srt, en_srt)` capability exists only in `backend_mac.py`, which runs
`align_srt.py` to read MLX hidden states. `study.py` skips that step on backends without it, including
Windows; dictionary links remain available. Running `align_srt.py` directly without MLX exits with a message.

## State

Everything lives in the video's folder, so the app and the command line always agree: `source.*`,
`title.txt`, `source.url`, `.hardsubs`, `.english-auto`, `.from-whisper`, `.split`, the `.srt` tracks,
`zh.words.json`, `zh.align.json`, `zh.whisper.json` when transcribed, `en.lines.txt` and `study.mkv`.
The self-made demo retains its original `zh.whisper.json` timing source so word-data regeneration can
reuse spoken timings without retranscription. The first Anki export adds `.pianpian-source-id`, a UUID
that moves with the folder. Jobs live in memory.

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
| GET | `/api/status` | Local status: version, library, engine readiness, platform, accelerator, browsers, busy; foreign origins get only `ok`/`version` |
| GET / POST | `/api/setup` | Setup plan/progress; start setup with library/data folders, model choices and cleanup option |
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

Safety: the server listens on 127.0.0.1 only and accepts only `Host: 127.0.0.1:<bound port>` or
`Host: localhost:<bound port>`; other or missing hosts get 403, including DNS-rebinding names.
POST and PUT require `X-Kit: 1`; cross-origin preflights do not grant that header. `/api/status`
with a foreign `Origin` (including `null` from disk) returns only `ok` and `version` with CORS enabled.
Same-origin requests, or requests without `Origin`, get full status without CORS headers.
Library entries and served files must resolve inside the library root; links leading out are excluded.
The root itself may be a link. App assets are checked by path components and extension instead of
resolving their bundle links. Windows device names and trailing dots/spaces are refused. Commands run
without a shell. Setup and queued pipeline/downloader jobs exclude each other under one lock (409
on conflict). Each import reserves a case-folded destination and registers from before its unique temporary
copy until its job is queued; concurrent aliases get a numbered name and setup returns 409 throughout.
Anki requests run outside this queue, but preview/export, word retiming and cached-audio serving register
under the same exclusion lock: setup cannot start while any is active, and they return 409 while setup runs.
Each operation unregisters even on failure; the lock is not held during audio processing or network requests.

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

### Phone-sized website demo

At **600 CSS pixels or narrower**, only the website demo (`html.demo`) replaces the menu row with
中文 / Pinyin / English switches, hides the library and panel toggles, and keeps the transcript under
the video in a bounded scroll area. Tapping or keyboard-activating a word pauses playback, opens a word
sheet and focuses its close button. Close or Escape returns focus to that word, or Play if unavailable.
The switches use the existing subtitle-track state. The local app keeps its regular menus. At every
width, the demo opens paused on its first Chinese cue unless a timestamp or playback already takes precedence.
The website sizes its same-origin iframe from the demo content so the outer page can scroll normally.
On short viewports, the parent page scrolls only as needed to reveal the sheet or returning focus clear
of the sticky header. The sheet remains inside the iframe, covering part of the transcript while open.

Reported for the phone-demo changes on **7 Nov 2026**: headless Chrome on macOS with touch emulation,
including a 390 × 480 CSS-pixel viewport, exercised real taps, keyboard focus restoration, sheet
visibility and reduced motion. Desktop clicks checked toolbar/footer hit targets. These are browser
checks, not physical-device tests. iPhone Safari, Android browsers and native fullscreen remain untested;
fullscreen checks cover button dispatch with the native API stubbed.
