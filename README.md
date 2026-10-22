# Pianpian 片片

*一天一片 · yì tiān yí piàn · a slice a day.* Watch Chinese videos with Chinese, pinyin and English subtitles that you can mix, resize and click, made on your Mac with local models.

**Status:** working prototype. macOS on Apple Silicon only for now.

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

1. Paste a Bilibili or YouTube link. Leave "English too" ticked (under options).
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
- **Word links:** click a word in Chinese, pinyin or English and its partners light up, with the CC-CEDICT meaning, its HSK 3.0 level and its measure word. English is linked through the dictionary first and through the translation model's own vectors second.
- **Tone colours:** each pinyin syllable in its tone's colour (Subtitles ▾ → Tone colours).
- **Follow the voice:** the word being said lights up in every line and in the transcript, from Whisper's word timings (or spread evenly over the line when the subtitles came from elsewhere). Subtitles ▾ → Follow the voice, key K.
- **Tenses (optional, off by default):** the characters that set the time (了 过 没 在 着 会 要 快要, and time words) are underlined green (past), red (now) or pink (future); click one to see its rule (Grammar ▾ → Underline them in the subtitles, key G).
- **Grammar cheat sheet** (Grammar ▾): the word order (who · when · where · with/how · verb · what), the two ways to say the past (verb + 了, … + 了) and the future (要 / 会 + verb), plus 没, 过, 快要…了 and 在, each with a short example: the verb in red, time words in green, the verb's markers as a soft pink tag (watermelon colours), and every word with its pinyin above it. Found by rules on jieba's word tags, not by a person: when a rule can't tell (会 can mean "will" or "can"), it says "maybe".
- **Video level:** each video in the library shows an HSK level: the lowest level that covers 90% of its words.
- **Any video:** drop a video file on the window to watch it, or add it to the library to get its subtitles, even if it wasn't downloaded here.

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
| `pipeline/grammar.py` | Tense marks for the colours (tests in `tests/test_grammar.py`) |
| `pipeline/data/hsk3.json` | Word → HSK 3.0 level, from complete-hsk-vocabulary (MIT, `hsk3.LICENSE`) |
| `PLAN.md` | The prototype's screen and API |
| `design/icons/` | The logo: `20-pianpian-watermelon.svg` (app) and `19-pianpian-mono.svg` (one colour) |

## Development

```bash
python3 dev.py check     # lint + tests, the same as CI
python3 dev.py serve     # the app at http://127.0.0.1:8770
python3 dev.py app       # build Pianpian.app (macOS)
```

Commit messages and pull request titles start with `feat:`, `fix:`, `docs:` or `chore:`: release-please builds the changelog and the version from them.

## Licence and data

Pianpian is MIT licensed ([`LICENSE`](LICENSE)). It uses data from others, under their own terms:

- **HSK 3.0 word levels:** `pipeline/data/hsk3.json`, derived from [complete-hsk-vocabulary](https://github.com/drkameleon/complete-hsk-vocabulary) (MIT, [`hsk3.LICENSE`](pipeline/data/hsk3.LICENSE)).
- **CC-CEDICT** meanings (CC BY-SA 4.0), downloaded on first use, not shipped.
- **Models**, downloaded on first use, not shipped: Whisper large-v3-turbo (MIT) and Hy-MT2-1.8B by Tencent (check its licence before you share the app).

Only download videos you may watch, and don't re-upload them.
