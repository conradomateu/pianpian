#!/usr/bin/env bash
# Turn one Bilibili / YouTube URL (or a local video) into study.mkv with
# selectable subtitle tracks: 中文 · Pinyin · 中文+Pinyin · English · all three.
#
#   ./study_video.sh "https://www.bilibili.com/video/BV..."           # public subs only
#   ./study_video.sh "https://www.bilibili.com/video/BV..." chrome    # use your Bilibili login
#   ./study_video.sh ~/Movies/clip.mp4
#   AUTO_EN=1 ./study_video.sh "https://..."      # also translate to English with a local model (Hy-MT2-1.8B)
#   HARDSUBS=1 ./study_video.sh "https://..."     # Chinese is burned into the picture: read it with
#                                                 # macOS OCR instead of Whisper (hardsubs_to_srt.py)
#
# Each video folder keeps its own state, which server.py also reads:
#   source.<ext>  title.txt  source.url  .hardsubs  .english-auto  .from-whisper  .split
#   zh.long.srt (as transcribed)  zh.srt (cut into short lines)  zh.pinyin.srt  zh.en.srt  zh.words.json  study.mkv
#   RESPLIT=1 SPLIT_MAX=12 ./study_video.sh .../source.mp4   # cut the lines shorter (0 = as transcribed)
#
# Re-run it after you drop an English translation (en.lines.txt) into the
# folder: it skips the finished steps and adds the English tracks.
#
# Needs: yt-dlp, ffmpeg, uv (all via Homebrew). Transcription only runs when the
# video has no Chinese subtitles, using mlx-whisper (Apple Silicon) via uvx.
# For personal study of videos you are allowed to watch; do not re-upload.
set -euo pipefail
export PYTHONWARNINGS=ignore::SyntaxWarning   # jieba 0.42 on Python 3.12+

SRC="${1:?usage: study_video.sh URL-or-file [browser-for-cookies]}"
BROWSER="${2:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOL=(uv run --quiet "$HERE/srt_tool.py")
MODEL="${WHISPER_MODEL:-mlx-community/whisper-large-v3-turbo}"

# ---------- 1. get the video (+ any Chinese subtitles it already has) ----------
if [[ -f "$SRC" ]]; then
  if [[ "$(basename "$SRC")" == source.* ]]; then
    WORK="$(cd "$(dirname "$SRC")" && pwd)"            # already inside a study folder: work there
  else
    WORK="$(dirname "$SRC")/$(basename "${SRC%.*}")_study"
    mkdir -p "$WORK"
    [[ -f "$WORK/source.${SRC##*.}" ]] || cp "$SRC" "$WORK/source.${SRC##*.}"
  fi
else
  ID="$(yt-dlp --print id --no-warnings --no-playlist ${BROWSER:+--cookies-from-browser "$BROWSER"} "$SRC" | head -1)"
  WORK="$PWD/$ID"
  mkdir -p "$WORK"
  if ! ls "$WORK"/source.* >/dev/null 2>&1; then
    # ai-zh = Bilibili's AI subtitles (usually only visible when logged in)
    # format: H.264 first, because AV1 does not play in every browser or player
    yt-dlp ${BROWSER:+--cookies-from-browser "$BROWSER"} \
      -f "bv*[height<=1080][vcodec^=avc]+ba/bv*[height<=1080]+ba/b" --merge-output-format mp4 \
      --write-subs --sub-langs "ai-zh,zh-Hans,zh-CN,zh,zh-Hant" --convert-subs srt \
      --print-to-file "%(title)s" "$WORK/title.txt" \
      --no-playlist -o "$WORK/source.%(ext)s" "$SRC"
  fi
  printf '%s\n' "$SRC" > "$WORK/source.url"
fi
cd "$WORK"
echo "folder: $WORK"
# remember "Chinese is in the picture" for later runs (rebuilds, the app)
[[ -n "${HARDSUBS:-}" ]] && touch .hardsubs
[[ -f .hardsubs ]] && HARDSUBS=1
VIDEO="$(ls source.* | grep -v -E '\.(srt|vtt|xml|json)$' | head -1)"

# ---------- 2. Chinese subtitles: reuse the platform's, else transcribe ----------
# The full-length subtitles are kept as zh.long.srt; zh.srt is that cut into short lines
# (SPLIT_MAX Chinese characters, default 18; 0 keeps them as they are). RESPLIT=1 re-cuts.
SPLIT_MAX="${SPLIT_MAX:-$(cat .split 2>/dev/null || echo 18)}"
transcribe() {
  echo "transcribing with $MODEL"
  ffmpeg -loglevel error -y -i "$VIDEO" -vn -ac 1 -ar 16000 audio.wav
  # the Simplified-Chinese prompt nudges Whisper away from Traditional output;
  # condition-on-previous-text False avoids repetition loops on long audio;
  # word timestamps let the long lines be cut exactly where each word is said
  uvx --from mlx-whisper mlx_whisper audio.wav --model "$MODEL" --language zh \
    --initial-prompt "以下是普通话的句子，使用简体中文。" \
    --condition-on-previous-text False --word-timestamps True \
    --output-format all --output-name zh --output-dir .
  mv zh.srt zh.long.srt; mv zh.json zh.whisper.json; rm -f zh.txt zh.vtt zh.tsv audio.wav
  touch .from-whisper
}
if [[ ! -f zh.srt ]]; then
  EXISTING="$(ls source.*.srt 2>/dev/null | grep -v danmaku | head -1 || true)"
  if [[ -n "$EXISTING" ]]; then
    echo "using the platform's subtitles: $EXISTING"
    cp "$EXISTING" zh.long.srt
  elif [[ -n "${HARDSUBS:-}" ]]; then
    echo "Chinese is burned into the picture — reading it with macOS OCR (check zh.srt afterwards)"
    python3 "$HERE/hardsubs_to_srt.py" "$VIDEO" zh.long.srt --crop 0.15 --fps 4
  else
    echo "no Chinese subtitles found"
    transcribe
  fi
  RESPLIT=1
elif [[ -n "${RESPLIT:-}" ]]; then
  [[ -f zh.long.srt ]] || cp zh.srt zh.long.srt       # folders made before lines were cut
  # Whisper folders made before word timestamps: transcribe again, so the cuts are exact
  [[ -f .from-whisper && ! -f zh.whisper.json ]] && transcribe
  # older Whisper folders have no marker: the 25-second lines give them away
  [[ ! -f .from-whisper && ! -f .hardsubs && ! -f zh.whisper.json ]] && ! ls source.*.srt >/dev/null 2>&1 && transcribe
  if [[ -f en.lines.txt ]]; then                      # the line numbers change, so the English is redone
    mv en.lines.txt en.lines.before-split.txt; rm -f zh.en.srt
    AUTO_EN=1
  fi
fi
if [[ -n "${RESPLIT:-}" ]]; then
  echo "cutting into lines of at most $SPLIT_MAX characters"
  WORDS_ARG=(); [[ -f zh.whisper.json ]] && WORDS_ARG=(--words zh.whisper.json)
  "${TOOL[@]}" split zh.long.srt --max "$SPLIT_MAX" ${WORDS_ARG[@]+"${WORDS_ARG[@]}"} -o zh.srt
  printf '%s\n' "$SPLIT_MAX" > .split
fi

# ---------- 3. pinyin tracks + a translation worksheet ----------
# (redone whenever zh.srt is newer, so a corrected zh.srt never leaves stale pinyin behind)
# (also redone when pinyin_fixes.txt changes)
fresh() { [[ "$1" -nt zh.srt && "$1" -nt "$HERE/pinyin_fixes.txt" ]]; }
fresh zh.pinyin.srt || "${TOOL[@]}" pinyin zh.srt
[[ zh.lines.txt -nt zh.srt ]] || "${TOOL[@]}" export zh.srt
fresh zh.words.json || "${TOOL[@]}" words zh.srt                # word ↔ pinyin pairs for the player

# ---------- 3b. English from a local model (AUTO_EN=1), unless there is one already ----------
# FORCE_EN=1 replaces an existing translation. Written to a .part file first, so a failed
# run never loses the English you had.
if [[ -n "${AUTO_EN:-}" ]] && [[ ! -f en.lines.txt || -n "${FORCE_EN:-}" ]]; then
  echo "translating with a local model (translate_srt.py)"
  uv run --quiet "$HERE/translate_srt.py" zh.srt -o en.lines.txt.part
  mv en.lines.txt.part en.lines.txt
  touch .english-auto
fi

# ---------- 4. English, once en.lines.txt exists ----------
if [[ -f en.lines.txt ]] && [[ ! -f zh.en.srt || en.lines.txt -nt zh.en.srt || zh.srt -nt zh.en.srt ]]; then
  "${TOOL[@]}" import zh.srt en.lines.txt
fi
if [[ -f zh.en.srt ]]; then
  "${TOOL[@]}" stack zh.srt zh.pinyin.srt zh.en.srt -o zh.trilingual.srt
  # the same pinyin + English, lifted clear of Chinese that is burned into the picture
  "${TOOL[@]}" ass zh.pinyin.srt zh.en.srt -o zh.pinyin-en.ass --margin-v 190
  # English word ↔ Chinese word links from the translation model (the player's hover links)
  if ! [[ zh.align.json -nt zh.en.srt && zh.align.json -nt zh.srt ]]; then
    uv run --quiet "$HERE/align_srt.py" zh.srt zh.en.srt || echo "word links skipped (align_srt.py failed)"
  fi
fi

# ---------- 5. package: one MKV, every track selectable in IINA / mpv / VLC ----------
TRACKS=(zh.srt zh.pinyin.srt zh.zh-pinyin.srt)
NAMES=("中文" "Pinyin" "中文 + Pinyin")
LANGS=(chi chi chi)
if [[ -f zh.en.srt ]]; then
  TRACKS+=(zh.en.srt zh.trilingual.srt zh.pinyin-en.ass)
  NAMES+=("English" "中文 + Pinyin + English" "Pinyin + English (raised, for burned-in Chinese)")
  LANGS+=(eng chi chi)
fi
# on by default: the raised track when HARDSUBS=1 (Chinese is part of the picture), else the three-line track
DEFAULT=2
for i in "${!NAMES[@]}"; do
  if [[ -n "${HARDSUBS:-}" && "${NAMES[$i]}" == Pinyin\ +\ English* ]]; then DEFAULT=$i; fi
  if [[ -z "${HARDSUBS:-}" && "${NAMES[$i]}" == "中文 + Pinyin + English" ]]; then DEFAULT=$i; fi
done

ARGS=(-loglevel error -y -i "$VIDEO")
for t in "${TRACKS[@]}"; do ARGS+=(-i "$t"); done
ARGS+=(-map 0:v -map 0:a)
for i in "${!TRACKS[@]}"; do ARGS+=(-map "$((i + 1))"); done
ARGS+=(-c:v copy -c:a copy -c:s srt)
for i in "${!TRACKS[@]}"; do
  [[ "${TRACKS[$i]}" == *.ass ]] && ARGS+=(-c:s:$i ass)
  ARGS+=(-metadata:s:s:$i "language=${LANGS[$i]}" -metadata:s:s:$i "title=${NAMES[$i]}" -disposition:s:$i 0)
done
ARGS+=(-disposition:s:$DEFAULT default study.mkv)
ffmpeg "${ARGS[@]}"

echo
echo "done: $WORK/study.mkv  (${#TRACKS[@]} subtitle tracks)"
if [[ ! -f zh.en.srt ]]; then
  echo "next: translate $WORK/zh.lines.txt with the 'Subtitle translator' prompt,"
  echo "      save the reply as $WORK/en.lines.txt, and run this script again."
fi
