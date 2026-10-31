# How Pianpian fits together

```
Pianpian.app (launcher.py, pywebview window)
  └── server.py   127.0.0.1 only, Python standard library
        ├── serves   app.html · assets/ · the library folder (with byte ranges, so video can seek)
        └── runs     pipeline/study.py with the engine's Python   (one job at a time, live log)
                       └── yt-dlp · ffmpeg · srt_tool.py · the platform's backend (backend.py: Whisper, OCR, Hy-MT2)
```

`python3 server.py` runs the same server in a browser tab, without the window. `app.html` opened
straight from disk still plays video files dropped on it; it only needs the server to make subtitles.

## Two Python environments

- **The app** (`launcher.py`, `server.py`) needs only the standard library plus pywebview for the window.
- **The engine** runs the pipeline. It is the `runtime` dependency group in `pyproject.toml`: pypinyin,
  jieba, zhconv, yt-dlp, imageio-ffmpeg (a static ffmpeg, so Homebrew is not needed), mlx-whisper and
  mlx-lm. torch is left out on purpose (mlx-whisper lists it for a conversion tool the app never uses),
  which keeps the engine at about 700 MB.

`engine.python()` picks the engine in this order: `$PIANPIAN_PYTHON`, the installed engine in
`~/Library/Application Support/Pianpian/engine`, the repository's `.venv` (`uv sync --group runtime`),
then the Python running the server.

## First run, updates and problems

- `engine.py` holds the paths and settings (`~/Library/Application Support/Pianpian/config.json`) and runs
  the setup that `setup.html` shows: Python 3.12 and the packages pinned with hashes in
  `pipeline/requirements.txt`, the dictionary, then the models you pick. Each source is timed against its
  mirror in mainland China and the faster one is used. The engine remembers which requirements it was
  installed from, so a release that changes them sends you back to the setup page, which then says
  "An update for Pianpian" and only fetches what changed (`uv pip sync`).
- `updates.py` asks GitHub for the latest release at most once a day and shows a card in the library
  when there is a newer one. yt-dlp is updated on its own at most once a week, and from the job card
  when a download fails because the site changed.
- `report.py` turns a failed job's log into a short code and a hint, and builds the Report link: GitHub's
  bug form filled in with redacted details (no home folder, file names, link paths, cookies or
  transcript). Nothing is sent until the person presses Submit on GitHub. Logs live in
  `~/Library/Logs/Pianpian`.

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
`Pianpian-macOS.zip`, which the website's Download button and the in-app update card point at.

Website visits and Download clicks are counted by [Umami Cloud](https://cloud.umami.is) (no cookies): its script is in `site/index.html` only,
never in `app.html`, so the app itself sends nothing to it. Real download totals come from the release files' own counters
(`gh api repos/conradomateu/pianpian/releases`). Not tested: how many mainland China visitors the script reaches.

## Models

`pipeline/models.py` downloads the two models once into `<data>/models` (`$PIANPIAN_MODELS`;
`~/.cache/pianpian/models` from the command line): Whisper large-v3-turbo (1.6 GB) and Hy-MT2 1.8B 4-bit (1.0 GB), pinned file by file
in `pipeline/models.lock.json` (`dev.py lock`). Catalog rows and lock sections are per platform
(`backend.NAME`), and `models.default(task)` picks this platform's model. Each file comes
from ModelScope first, which is fast from mainland China, then Hugging Face, and is checked against the
size and SHA-256 Hugging Face publishes. Stopped downloads resume. A model already in the Hugging Face
cache is used where it is. Progress goes to stdout as `@progress {json}` lines.

## The pipeline

`pipeline/study.py <link or file> [browser]` makes one study folder. Each step is skipped when its
output is newer than its inputs, so it can run again after `zh.srt` is fixed by hand.

1. **Video**: yt-dlp, H.264 first (AV1 does not play everywhere), plus the platform's Chinese
   subtitles if any. A browser name borrows that browser's Bilibili login for the AI subtitles.
2. **Chinese**: the platform's subtitles, else macOS OCR when the Chinese is burned into the picture,
   else Whisper with word timestamps. `srt_tool.py split` cuts long lines at word boundaries.
3. **Pinyin and words**: pypinyin and jieba, with `pinyin_fixes.txt` on top. `zh.words.json` holds
   each word's pinyin, CC-CEDICT gloss, HSK level and measure words, the tense tags from `grammar.py`
   and Whisper's word times (for the spoken-word highlight).
4. **English**: `translate_srt.py` runs Hy-MT2 line by line, with the title and the previous lines as
   context, so every English line keeps its Chinese line's timing. `align_srt.py` then links English
   words to Chinese words where the dictionary can't.
5. **study.mkv**: every track in one file, for IINA, mpv or VLC.

The model engines sit behind `pipeline/backend.py`, the only platform check in `pipeline/`:
`backend.impl()` is `backend_mac.py` (mlx-whisper, mlx-lm, macOS OCR) and gives three functions,
`transcribe()`, `translator()` (a context manager yielding `generate(prompt, temperature, max_tokens)`)
and `ocr()`. The steps above call those, so the prompt, the per-line loop and the line cutting are the
same for every engine. `tests/test_backend.py` has the checks a new backend reuses (the signature
test and the `assert_*` output helpers) and adds its own cases to.
`align_srt.py` reads the model's hidden states and is MLX only; elsewhere it stops and the dictionary
links stay.

## State

Everything lives in the video's folder, so the app and the command line always agree: `source.*`,
`title.txt`, `source.url`, `.hardsubs`, `.english-auto`, `.from-whisper`, `.split`, the `.srt` tracks,
`zh.words.json`, `zh.align.json`, `en.lines.txt` and `study.mkv`. Jobs live in memory.

## Server API

| Method | Path | Does |
|---|---|---|
| GET | `/api/status` | Version, library folder, engine ready or not, installed browsers, busy |
| GET | `/api/videos` | Library folders with title, link, HSK level and the tracks they have |
| GET | `/api/videos/<id>` | One video, plus its `zh.lines.txt` for translating by hand |
| GET | `/api/jobs` | Recent jobs with their state and the end of their log |
| POST | `/api/add` | `{url, browser, translate}`: download and make subtitles |
| PUT | `/api/import?name=…` | The body is a video file: copy it into the library and make subtitles |
| POST | `/api/videos/<id>/translate` | English from the local model, then rebuild |
| POST | `/api/videos/<id>/english` | `{text}`: save a hand-made `en.lines.txt`, then rebuild |
| POST | `/api/videos/<id>/split` | `{max}`: cut the lines again (0 = as transcribed) |
| POST | `/api/videos/<id>/rebuild` | Run the pipeline again |
| POST | `/api/videos/<id>/open` | Show the folder in Finder |

Safety: the server listens on 127.0.0.1 only. Requests that change anything need an `X-Kit: 1`
header, so other websites can't start jobs. Video ids and paths are checked, and commands run
without a shell.

## The page

`app.html` is the only screen: library on the left (B), video and its menus in the middle, transcript
on the right (T). `assets/player.js` is the player, `assets/kit.css` the design tokens and
`assets/kit.js` small shared helpers. There is no framework and no build step.
