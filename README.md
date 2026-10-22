# Pianpian 片片

*一天一片 · yì tiān yí piàn · a slice a day.* Watch Chinese videos with Chinese, pinyin and English subtitles that you can mix, resize and click, made on your Mac with local models.

**Status:** working prototype (local server + browser). The desktop app is planned in [`docs/plans/`](docs/plans/). macOS on Apple Silicon only for now.

## Start

```bash
python3 ~/code/pianpian/server.py
```

It opens http://127.0.0.1:8770/app.html. Ctrl+C stops it.

**Or as an app, in its own window** (proof of concept, this Mac only):

```bash
tools/make_app.sh
```

It builds `Pianpian.app` with the watermelon icon into `~/Applications`. Double-click it: the server runs inside and closing the window quits it. The app runs the code in this folder, so changes show up the next time you open it. It still needs uv, ffmpeg and yt-dlp installed, so it is not yet something to send to another Mac. Log: `~/Library/Logs/Pianpian/launcher.log`.

1. Paste a Bilibili or YouTube link. Leave "English too" ticked. Tick "burned into the picture" only if the Chinese is part of the image.
2. Wait for the job to finish (a 12-minute video took under 2 minutes), then watch.
3. Lines too long? **Video ▾ → Lines: 12 / 18 / 26**, and the cuts are redone from Whisper's word timings.
4. Wrong pinyin? Add the word to `pipeline/pinyin_fixes.txt` and press **Video ▾ → Rebuild**.

The library is `~/Movies/mandarin`. Everything is one screen: the library on the left (key B), the transcript on the right (key T), each folding away with the button in its top corner, and the video in the middle with one row of menus under it (Subtitles, Playback, Video, Resources). Drop a video and its `.srt` files on the window to watch them without adding them; that also works with `app.html` opened from disk, with the server off.

## What it does

- **Subtitles:**
  - Chinese comes from the platform, from Whisper (large-v3-turbo, MLX) or from macOS OCR of burned-in text.
  - Pinyin comes from pypinyin + jieba, corrected by `pinyin_fixes.txt`.
  - English comes from Hy-MT2-1.8B (MLX, about 1 GB, downloaded the first time).
- **Player:** any mix of tracks, each with its own size, colour and blur. Pause after a line, loop, change speed, go fullscreen.
- **Word links:** click a word in Chinese, pinyin or English and its partners light up, with the CC-CEDICT meaning. English is linked through the dictionary first and through the translation model's own vectors second.

## Files

| Path | What it is |
|---|---|
| `server.py` | Local server (standard library only): serves the pages and the library, runs one job at a time |
| `launcher.py` | The app in its own window: the server inside, a native macOS window (pywebview) |
| `tools/make_app.sh` · `tools/svg2png.swift` | Build `Pianpian.app` (icon from the SVG, small Python environment, bundle) |
| `app.html` | The whole app on one screen: library, player, menus, files dropped from disk |
| `player.html` | Only forwards old links to `app.html` |
| `assets/` | `kit.css` (design tokens), `kit.js` (theme, helpers), `player.js` (the subtitle player) |
| `pipeline/study_video.sh` | Link or file → subtitles → `study.mkv`. Calls the scripts below |
| `pipeline/srt_tool.py` | Pinyin, word lists, line splitting, LLM round-trip, track stacking |
| `pipeline/translate_srt.py` · `align_srt.py` | Local English translation, and English↔Chinese word links |
| `pipeline/hardsubs_to_srt.py` · `ocr_frames.swift` | OCR for burned-in Chinese (macOS Vision) |
| `pipeline/pinyin_fixes.txt` | Pinyin corrections, one word per line |
| `PLAN.md` | The prototype's screen and API |
| `docs/plans/` | Desktop app design and orchestration (CI, releases, updates, Windows) |
| `design/icons/` | Logo explorations. Chosen: `20-pianpian-watermelon.svg` (app) and `19-pianpian-mono.svg` (menu bar) |

Only download videos you may watch, and don't re-upload them.
