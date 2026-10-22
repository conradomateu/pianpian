# Pianpian 片片

*一天一片 · yì tiān yí piàn · a slice a day.* Watch Chinese videos with Chinese, pinyin and English subtitles that you can mix, resize and click, made on your Mac with local models.

**Status:** working prototype (local server + browser). The desktop app is planned in [`docs/plans/`](docs/plans/). macOS on Apple Silicon only for now.

## Start

```bash
python3 ~/code/pianpian/server.py
```

It opens http://127.0.0.1:8770/app.html. Ctrl+C stops it.

1. Paste a Bilibili or YouTube link. Leave "English too" ticked. Tick "burned into the picture" only if the Chinese is part of the image.
2. Wait for the job to finish (a 12-minute video took under 2 minutes), then watch.
3. Lines too long? Pick **Lines: 12 / 18 / 26** above the video and the cuts are redone from Whisper's word timings.
4. Wrong pinyin? Add the word to `pipeline/pinyin_fixes.txt` and press **Rebuild**.

The library is `~/Movies/mandarin`. Without the server, [`player.html`](player.html) plays a video and its `.srt` files dropped on it.

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
| `app.html` · `player.html` | The app (library + player) and the offline player |
| `assets/` | `kit.css` (design tokens), `kit.js` (theme, helpers), `player.js` (the subtitle player) |
| `pipeline/study_video.sh` | Link or file → subtitles → `study.mkv`. Calls the scripts below |
| `pipeline/srt_tool.py` | Pinyin, word lists, line splitting, LLM round-trip, track stacking |
| `pipeline/translate_srt.py` · `align_srt.py` | Local English translation, and English↔Chinese word links |
| `pipeline/hardsubs_to_srt.py` · `ocr_frames.swift` | OCR for burned-in Chinese (macOS Vision) |
| `pipeline/pinyin_fixes.txt` | Pinyin corrections, one word per line |
| `PLAN.md` | The prototype's pages and API |
| `docs/plans/` | Desktop app design and orchestration (CI, releases, updates, Windows) |
| `design/icons/` | Logo explorations. Chosen: `20-pianpian-watermelon.svg` (app) and `19-pianpian-mono.svg` (menu bar) |

Only download videos you may watch, and don't re-upload them.
