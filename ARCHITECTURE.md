# How Pianpian fits together

```
macOS: Pianpian.app (launcher.py, pywebview/WebKit) · Windows: Pianpian.exe (launcher.py, pywebview/WebView2)
  └── server.py   127.0.0.1 only, Python standard library
        ├── serves   app.html · assets/ · the library folder (with byte ranges, so video can seek)
        └── runs     pipeline/study.py with the engine's Python   (one job at a time, live log)
                       └── yt-dlp · ffmpeg · srt_tool.py · the platform's backend (backend.py: SenseVoice, PLaMo)
```

`python3 server.py` (or `python server.py` on Windows) runs the same server in a browser tab, without
the window. `app.html` opened straight from disk still plays video files dropped on it; it only needs
the server to make subtitles.

## Two Python environments

- **The app** (`launcher.py`, `server.py`) needs only the standard library plus pywebview for the window.
- **The engine** runs the pipeline. It is the `runtime` dependency group in `pyproject.toml`: pypinyin,
  jieba, zhconv, yt-dlp and imageio-ffmpeg (a static ffmpeg, so no system ffmpeg is needed).
  These are the complete five runtime packages on both platforms. Speech, translation and model
  word-link inference are native; no MLX, llama-cpp-python, PyTorch, transformers or OCR packages
  are installed. Python still orchestrates the pipeline and creates the dictionary/pinyin/subtitle files.
- **Speech inference** uses the bundled `pianpian-sensevoice` CPU executable on both platforms. First
  run downloads SenseVoice Small Q8 and FSMN-VAD weights, not a compiler or GPU runtime. The shared
  `pipeline/sensevoice.py` adapter preserves the existing subtitle/word-timing output format.
- **The translation runtime** is not a Python package: `pipeline/runtimes.py` downloads pinned
  llama.cpp builds: Metal/CPU share one Mac archive; Windows defaults to CPU with optional CUDA or Vulkan
  into `<data>/runtime` (`$PIANPIAN_RUNTIME`) and checks every archive against its SHA-256.
  A translation GPU build that will not start is retried once with the CPU build (`pipeline/plamo.py`).
  Downloads come from GitHub; `PIANPIAN_GITHUB_MIRROR` is an opt-in prefix for slow networks.
  Each build's `.complete` records the tool, backend, release and archive SHA-256s. A changed pin makes
  the installed build stale; setup replaces the whole build folder so old DLLs do not survive an upgrade.
  A failed download leaves the old folder intact. Setup installs runtimes only when translation is selected.
  On Windows, a GPU choice also installs CPU tools for word links and startup fallback; both downloads
  count toward readiness and size. Setup passes its saved `accel` choice through `PIANPIAN_ACCEL`;
  an explicit environment override wins. Speech and model word-link generation stay on CPU. The
  bundled `pianpian-align` helper loads the CPU runtime's libllama and the same PLaMo GGUF; it adds no
  model download or Python ML dependency.

`engine.python()` picks the engine in this order: `$PIANPIAN_PYTHON`, the installed engine in
`<data>/engine` (`Scripts/python.exe` on Windows, `bin/python` on macOS), the repository's `.venv`
(`python dev.py engine`), then the Python running the server (source runs only).

## First run, updates and problems

- `engine.py` holds the paths and settings (`~/Library/Application Support/Pianpian/config.json` on
  macOS, `%LOCALAPPDATA%\Pianpian\config.json` on Windows) and runs the setup that `setup.html` shows:
  Python 3.12 and the packages pinned with hashes in `pipeline/requirements.txt` (or
  `pipeline/requirements-windows.txt`), the native translation runtime, the dictionary, then the models you
  pick. Each source is timed against its mirror in mainland China and the faster one is used. The engine
  remembers which requirements it was installed from, so a release that changes them sends you back to
  the setup page, which then says "An update for Pianpian" and only fetches what changed (`uv pip sync`).
  Superseded Hy-MT2 selections map to PLaMo; missing new weights make setup necessary even when old
  weights are installed. Sync removes the former MLX dependency stack. Saved video files are preserved.
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
the window, the server, the pages, the pipeline scripts, both locks, `uv`, the native CPU speech helper,
the native word-link helper, and a `VERSION` file. The engine and the models
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
with PyInstaller 6.22.3 and pywebview 6.2.1; CI bundles uv 0.13.7. Both call
`tools/build_sensevoice.py` to compile pinned source with CMake and a C++17 compiler (Xcode command-line
tools on macOS, Visual Studio C++ tools on Windows). The helper is collected as a binary, so PyInstaller
checks its dependencies and signs it on macOS. It lives at `pipeline/bin/pianpian-sensevoice` or
`pipeline/bin/pianpian-sensevoice.exe`, beside `sensevoice-NOTICES.txt` and `build-manifest.json`.
Packaging fails if the notices are missing, and runs the packaged helper's `--help` before making the
archives. `tools/build_alignment.py` likewise builds the small `pianpian-align[.exe]` helper, which
loads the separately installed runtime's libllama. Startup checks do not validate model inference. End users do not need CMake, a compiler,
PyTorch or CUDA to run speech recognition. The Windows build needs Inno Setup 6
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
release-page link. `assets/site-os.js` shows the matching desktop download using browser platform hints. On phones/tablets
(including iPad desktop-style user agents), downloads stay hidden and the primary action opens the GitHub
repository to star it. Desktop users also have explicit GitHub star links. With JavaScript disabled,
GitHub and the platform availability message remain visible. Browser classification is a compatibility
hint, not a hardware test; links never star the repository automatically. Windows CI installs the hashed Windows engine lock
before running `dev.py check` with `UV_NO_SYNC=1`.

### Windows test history

These reports distinguish earlier releases from **acceptance of the current integrated build**:

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
- **16 Nov 2026, compact build `d43a8b2`:** [Windows CI](https://github.com/conradomateu/pianpian/actions/runs/43745206869)
  compiled the installer and launched packaged SenseVoice. The 44.8-second demo reached six of eight
  speech segments before the 1,200-second integration timeout. Translation/alignment were not reached.
  The subsequent change adds a safely selected AVX2 helper, adaptive CPU threads (also for VAD),
  and a smaller graph metadata arena. Its Windows speed and output still require CI acceptance.
  `tools/check_sensevoice.py` now records short baseline/optimized comparisons, the full demo and silence,
  with separate logs and timings before the full pipeline test. Timeout cleanup stops descendant processes.

As of **7 Nov 2026**, the integrated app, revised installer, engine repair/data migration and security
changes have not been exercised natively on Windows. The integration reports use macOS Apple Silicon
tests, including simulated Windows paths/processes. The SenseVoice/PLaMo integration added on 16 Nov 2026
has not passed full Windows acceptance (see the timeout above). OCR extraction has been removed. Anki export, Windows 10, AMD/Intel Vulkan
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
| Speech | SenseVoice Small Q8 + FSMN-VAD (0.256 GB), native CPU | Same weights and native CPU implementation (0.256 GB) |
| Translation | PLaMo 0.8B Q3_K_M GGUF (486 MB), llama.cpp Metal/CPU | Same weights, llama.cpp CPU by default; optional CUDA/Vulkan |

SenseVoice, FSMN-VAD and PLaMo come from pinned Hugging Face revisions with hf-mirror.com fallback;
no ModelScope mirrors are configured for these files. Every file is checked against the size and
SHA-256 in the lock. Stopped downloads resume. A matching model in the Hugging Face cache is used
where it is. Progress goes to stdout as `@progress {json}` lines. Native translation binaries are pinned
separately in `pipeline/runtimes.py`. Hy-MT2 is no longer a selectable model or an inference fallback;
its former IDs only identify saved selections that must migrate to PLaMo.

PLaMo is distributed under the [PLaMo Community License](https://huggingface.co/pfnet/plamo-3-translate-0.8b-GGUF#license),
not the app's MIT license. Refer to the model's license for commercial-use terms.

Windows packaging also includes the three app-local Microsoft C++ runtime DLLs required by the
pinned llama.cpp binaries. They come from the build machine's Visual Studio x64 redistributable
folder, with a provenance/hash manifest; setup places them beside each native runtime. Missing or
changed DLLs are repaired from the app without downloading the model/runtime again. This avoids
requiring a separate system-wide Visual C++ installation. Their servicing follows Pianpian updates.

### Compact installation accounting

Pinned artifact sizes on 16 Nov 2026:

| Component | macOS ARM64 | Windows x64 |
|---|---:|---:|
| SenseVoice Q8 + FSMN-VAD | 255,928,832 bytes | 255,928,832 bytes |
| PLaMo Q3_K_M | 486,385,856 bytes | 486,385,856 bytes |
| **All model weights** | **742,314,688 bytes** | **742,314,688 bytes** |
| Native translation archive (default) | 16,244,820 bytes | 24,172,821 bytes |
| Five Python package artifacts | 44,567,849 bytes | 54,700,782 bytes |

Models, default runtime and package artifacts total **803,127,357 bytes on Mac** and
**821,188,291 bytes on Windows**, **before Python itself, the dictionary, installer and retries**.
The native speech and word-link helpers are bundled in the desktop app. Optional Windows CUDA archives
total **663,873,465 bytes**, or Vulkan **36,970,920 bytes**, in addition to the CPU tools used for word
links and startup fallback. No CUDA Toolkit is required or downloaded. Mac Metal/CPU share one archive.
These are component sizes, not measured clean-install transfers or peak disk use. Setup separates
model/runtime downloads from Python/package downloads and estimated installed engine space.
WebView2 is a separate Microsoft download when absent on Windows.

A fresh five-package Mac engine was installed on 16 Nov 2026 and occupied **105,702,916 logical bytes**,
excluding its shared Python interpreter; filesystem allocation and caches can differ. Windows package
sizes come from artifact metadata, not a Windows installation. The Mac self-made demo completed with
nine subtitle cues, Chinese word times, pinyin, English, 41 model word links and a six-track study video.
The small development checks do not establish general translation quality or alignment parity with the
former model. Native Windows execution remains untested.

Setup detects Windows GPU availability in a background request without changing the selection. It checks
NVIDIA driver >=551.61, initializes the installed driver with `cuInit`/`cuDeviceGetCount`, and checks
pinned app-owned CUDA runtime stamps. If llama-server is installed, `--list-devices` must report a CUDA
device before device visibility is confirmed. Driver/device enumeration does not prove model inference.
With no compatible NVIDIA driver, detection may report a device from `vulkaninfo`; its absence is
inconclusive. Existing compatible app-managed runtimes are reused; arbitrary system CUDA libraries are not.

Setup can clean superseded app-owned model folders after their replacements are ready. Shared Hugging
Face caches are left alone. Existing video subtitles and timing files remain readable.

### SenseVoice timing contract

The native helper uses VAD for speech segmentation and estimates token intervals from the ASR output.
`pipeline/sensevoice.py` adapts these to subtitle segments and word intervals consumed by line cutting,
pinyin, word highlighting and Anki export. `zh.whisper.json` remains the compatibility filename even
for SenseVoice output. Times are estimates, not manually annotated boundaries. Preserve raw results
when investigating timing problems; structural checks alone cannot establish temporal accuracy.
The current native Windows build and inference remain untested.

### PLaMo word-link contract

`align_srt.py` sends each Chinese/English subtitle pair to the bundled `pianpian-align` helper. It loads
the same translation GGUF through pinned libllama on CPU and extracts layer-7 hidden states. Token byte
offsets map vectors back to the dictionary's Chinese word boundaries and English words. Mutual nearest
word vectors supply `zh.align.json` links; dictionary matches continue to take priority in the player.
The output format stays compatible with existing libraries. All cues are validated before existing links
are replaced. No second neural model or Python ML stack is installed.

The middle layer was checked on six self-authored sentences on Mac, and the demo produced 41 links.
This is a heuristic, not a guarantee that every link is correct or evidence of equal quality to the former
alignment model. CPU alignment uses the same path regardless of the translation accelerator.

### Optional Windows speed comparison

Open **Resources → Models & acceleration** in the player to return to setup. Its **Compare CPU / CUDA speed** button queues `pipeline/acceleration.py` through the normal
job worker, so setup cannot replace models/runtimes during a comparison. It never downloads models,
runtimes or a CUDA Toolkit, and never changes the saved acceleration. Already installed CUDA builds
run once with GPU work disabled and once with GPU work enabled. Missing prerequisites are reported
per model; there are no guessed speed multipliers.

SenseVoice and word-link generation are CPU-only, so the comparison includes translation only.
PLaMo uses the installed `llama-bench`
with 256 input / 32 output synthetic tokens, two warm runs, and estimates 100 subtitles with that same
token budget. This is a throughput estimate, not a translation-quality test or a guarantee for subtitle
lengths/context in real videos. Downloads, pinyin and app overhead are excluded. CUDA model-buffer/offload
diagnostics are required before a speedup is reported; detecting a GPU alone is insufficient. The test
has a 10-minute deadline. Logs stay under `<data>/cache/benchmark`; results appear in the job log.

The CLI flags/diagnostics use pinned llama.cpp b11851. Detection, benchmark parsing, queue exclusion and real browser clicks are tested on macOS with
simulated Windows responses. Native Windows benchmark execution remains **not tested**. The Windows
bundle explicitly includes stdlib `ctypes` for the driver probe; no additional Python package is added.

## The pipeline

`pipeline/study.py <link or file> [browser]` makes one study folder. Each step is skipped when its
output is newer than its inputs, so it can run again after `zh.srt` is fixed by hand.

1. **Video**: yt-dlp, H.264 first (AV1 does not play everywhere), plus the platform's Chinese
   subtitles if any. A browser name borrows that browser's Bilibili login for the AI subtitles.
2. **Chinese**: the platform's subtitle tracks, otherwise SenseVoice on CPU with estimated word timestamps
   on both platforms. Burned-in text is not extracted. `srt_tool.py split` cuts long lines at word boundaries.
3. **Pinyin and words**: pypinyin and dictionary-refined jieba segmentation, with `pinyin_fixes.txt` on top. `zh.words.json` holds
   each word's pinyin, CC-CEDICT gloss, HSK level and measure words, the tense tags from `grammar.py`
   and the speech recognizer's word times (for the spoken-word highlight).
4. **English**: `translate_srt.py` runs PLaMo Q3 line by line through shared native `llama-server`,
   with PFML3 prompts containing the title and preceding lines as context. Every English line keeps
   its Chinese timing. On both platforms, `align_srt.py` adds model links where the dictionary cannot.
5. **study.mkv**: every track in one file, for IINA, mpv or VLC.

`srt_tool.segment_words()` keeps known CC-CEDICT words whole and splits unknown Chinese jieba
compounds into the longest dictionary parts, preserving unmatched text: `今天天气` becomes `今天 天气`.
Pinyin overrides and V一V constructions stay whole; without the dictionary, jieba's boundaries remain.
Pinyin tracks, word JSON and model alignment share these boundaries. This is a greedy dictionary
heuristic, not a linguistic parser; it can also split names or reduplications absent from the dictionary.

The model engines sit behind `pipeline/backend.py`, the only platform check in `pipeline/`:
`backend.impl()` loads `backend_native.py` on both platforms; it delegates to shared `sensevoice.py`,
`plamo.py` and `align_srt.py`. The interfaces are `transcribe()`, `translator()` (a context manager yielding
`generate(prompt, temperature, max_tokens)`) and `align(zh_srt, en_srt)`. Prompts, per-line translation,
word segmentation and alignment are shared. `tests/test_backend.py` checks their signatures and output
contracts. The old MLX implementation has been removed.

## State

Everything lives in the video's folder, so the app and the command line always agree: `source.*`,
`title.txt`, `source.url`, `.english-auto`, `.from-whisper`, `.split`, the `.srt` tracks,
`zh.words.json`, `zh.align.json`, `zh.whisper.json` when transcribed, `en.lines.txt` and `study.mkv`.
Older folders may retain `.hardsubs` from the removed OCR path; their saved subtitles are not deleted.
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
The same bytes are uploaded to Anki. With raw ASR timing data, old word timings are repaired in memory by
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
| GET / POST | `/api/setup` | Setup plan/progress; start setup with library/data folders, model choices, acceleration and cleanup option |
| GET | `/api/setup-gpu` | Read-only GPU/driver probe; downloads nothing and does not change saved settings |
| POST | `/api/setup-benchmark` | Queue an optional offline CPU/CUDA comparison using installed models/runtimes; results in `/api/jobs` |
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
