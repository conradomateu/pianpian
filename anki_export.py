"""Local media selection and Anki export. No collection paths or platform-specific commands."""
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

import engine
from anki_connect import AnkiError as AnkiError, Client

VIDEO_EXT = (".mp4", ".m4v", ".mkv", ".webm", ".mov")
MEDIA_EXT = {*VIDEO_EXT, ".mp3", ".m4a", ".wav", ".ogg", ".flac", ".opus"}
MAX_CLIP = 120
_LOCK = threading.RLock()
_WORDS = {}
_DURATIONS = {}


def client():
    cfg = engine.config().get("anki", {})
    return Client(port=cfg.get("port", 8765), key=cfg.get("key", ""))


def status():
    cfg = engine.config().get("anki", {})
    return {**client().status(), "port": cfg.get("port", 8765), "hasKey": bool(cfg.get("key")), "deck": cfg.get("deck", "")}


def settings(data):
    port = data.get("port", 8765)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Port must be an integer from 1 to 65535.")
    if "key" in data and (not isinstance(data["key"], str) or len(data["key"]) > 1024):
        raise ValueError("Invalid AnkiConnect API key.")
    with _LOCK:
        cfg = {**engine.config().get("anki", {}), "port": port}
        if "key" in data:
            cfg["key"] = data["key"]
        engine.save_config(anki=cfg)
    return status()


def study_words(folder):
    """Repair old punctuation timings in memory, without rewriting a learner's study files."""
    words, raw = folder / "zh.words.json", folder / "zh.whisper.json"
    stamp = (words.stat().st_mtime_ns, raw.stat().st_mtime_ns if raw.exists() else 0)
    with _LOCK:
        cached = _WORDS.get(str(words))
        if cached and cached[0] == stamp:
            return cached[1]
        data = json.loads(words.read_text(encoding="utf-8"))
        if raw.exists() and raw.resolve().is_relative_to(folder.resolve()):   # a link out of the folder is ignored
            try:
                result = engine.run([engine.python(), str(engine.HERE / "pipeline" / "srt_tool.py"), "retime", str(words),
                                         "--whisper", str(raw)], capture_output=True, text=True, encoding="utf-8", timeout=30, check=True,
                                        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", **engine.pipeline_env()},
                                        creationflags=engine.NO_WINDOW)
                data = json.loads(result.stdout)
            except (OSError, subprocess.SubprocessError, ValueError):
                # Old word bounds can truncate speech; sentence preview remains available without the engine.
                for cue in data.get("cues", []):
                    cue.pop("k", None)
        if len(_WORDS) >= 32:
            _WORDS.pop(next(iter(_WORDS)))
        _WORDS[str(words)] = (stamp, data)
        return data


def source(entry, library):
    """Resolve a selected library source, never a client-supplied filesystem path."""
    root = library.resolve()
    if not entry.resolve().is_relative_to(root):
        raise ValueError("The source must be inside the library.")
    candidates = [entry] if entry.is_file() else sorted(entry.glob("source.*"), key=lambda p: (p.suffix.lower() not in VIDEO_EXT, p.name))
    path = next((p for p in candidates if p.is_file() and p.suffix.lower() in MEDIA_EXT), None)
    if path is None or not path.resolve().is_relative_to(root):
        raise ValueError("No accessible source media in this library item.")
    return path


def _fingerprint(path):
    st = path.stat()
    return str(path.resolve()), st.st_size, st.st_mtime_ns


def _ffmpeg():
    exe = engine.ffmpeg()
    if not exe:
        raise ValueError("FFmpeg is unavailable. Finish engine setup before exporting audio.")
    return exe


def duration(path):
    stamp = _fingerprint(path)
    if stamp not in _DURATIONS:
        result = engine.run([_ffmpeg(), "-nostdin", "-hide_banner", "-i", str(path)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                                creationflags=engine.NO_WINDOW)
        match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if not match or "Audio:" not in result.stderr:
            raise ValueError("This source has no readable audio track.")
        value = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
        if not math.isfinite(value) or value <= 0:
            raise ValueError("The source audio duration is unavailable.")
        if len(_DURATIONS) >= 128:
            _DURATIONS.clear()
        _DURATIONS[stamp] = value
    return _DURATIONS[stamp]


def bounds(path, data):
    values = [data.get("start"), data.get("end")]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError("Choose finite start and end times in seconds.")
    start, end = (round(v, 3) for v in values)
    if start < 0 or end <= start:
        raise ValueError("The audio end must be after its start, and start must be zero or later.")
    if end - start > MAX_CLIP:
        raise ValueError(f"Select an audio clip of at most {MAX_CLIP} seconds.")
    if end > duration(path) + .05:
        raise ValueError("The audio selection extends beyond the source. Adjust its end.")
    end = min(end, duration(path))
    if end <= start:
        raise ValueError("The audio start must be before the end of the source.")
    return start, end


def cache_dir():
    folder = engine.cache_dir() / "anki"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def clip_name(path, start, end):
    key = json.dumps([_fingerprint(path), start, end, "mp3-v1"], ensure_ascii=False)
    return "pianpian-" + hashlib.sha256(key.encode()).hexdigest() + ".mp3"


def audio_path(name):
    if not re.fullmatch(r"pianpian-[0-9a-f]{64}\.mp3", name):
        raise ValueError("Invalid audio preview.")
    path = cache_dir() / name
    if not path.is_file():
        raise FileNotFoundError("Preview expired. Preview the audio again.")
    return path


def render_clip(path, start, end):
    with _LOCK:
        folder = cache_dir()
        dest = folder / clip_name(path, start, end)
        if not dest.exists():
            with tempfile.TemporaryDirectory(dir=folder) as tmp:
                output = Path(tmp) / "clip.mp3"
                result = engine.run([_ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-i", str(path),
                    "-t", f"{end-start:.3f}", "-map", "0:a:0", "-vn",
                    "-map_metadata", "-1", "-c:a", "libmp3lame", "-q:a", "2", str(output)], capture_output=True, timeout=60, creationflags=engine.NO_WINDOW)
                if result.returncode or not output.exists() or output.stat().st_size == 0:
                    raise ValueError("Could not extract this audio. Check the selected times and source file.")
                os.replace(output, dest)
            for old in sorted(folder.glob("pianpian-*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)[128:]:
                old.unlink(missing_ok=True)
        return dest


def _cue_words(entry):
    words = json.loads((entry / "zh.words.json").read_text(encoding="utf-8"))["cues"] if (entry / "zh.words.json").is_file() else []
    text = (entry / "zh.srt").read_text(encoding="utf-8-sig")
    cues = []
    def seconds(value):
        match = re.search(r"(?:(\d+):)?(\d+):(\d+(?:[.,]\d+)?)", value)
        return int(match[1] or 0) * 3600 + int(match[2]) * 60 + float(match[3].replace(",", ".")) if match else None

    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = block.splitlines()
        marker = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if marker is not None:
            start, end = map(seconds, lines[marker].split("-->", 1))
            value = re.sub(r"<[^>]+>|\{\\[^}]*\}", "", "\n".join(lines[marker + 1:])).strip()
            if start is None or end is None or not value:
                continue
            # Match the player's time/text lookup, never index stale word data by the new SRT's cue number.
            mid = (start + end) / 2
            word = next((w for w in reversed(words) if w["s"] <= mid), None)
            tokens = word["w"] if word and word["e"] > mid and "".join(value.split()) == "".join(
                "".join(p[0] for line in word["w"] for p in line).split()) else None
            cues.append({"w": tokens or [[[value]]], "text": value, "linked": tokens is not None})
    return cues


def selection_anchor(entry, selection):
    """Character offsets survive resegmentation; edited fields and audio margins do not change identity."""
    if not entry.is_dir() or not isinstance(selection, dict):
        raise ValueError("Select words or a sentence from a processed library item.")
    if any(key in selection and not isinstance(selection[key], str) for key in ("sentence", "expression")):
        raise ValueError("Invalid selection text.")
    cues = _cue_words(entry)
    a, b, first, last = (selection.get(k) for k in ("cueStart", "cueEnd", "first", "last"))
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (a, b)) or not 0 <= a <= b < len(cues):
        raise ValueError("The selected subtitle no longer exists. Select it again.")
    if "sentence" in selection and selection["sentence"] != "\n".join(c["text"] for c in cues[a:b + 1]):
        raise ValueError("The subtitles changed. Reload the video and select the words again.")
    rows = [[word[0] for line in cue["w"] for word in line] for cue in cues]
    if first is None and last is None:
        first, last = 0, len(rows[b]) - 1
    elif any(isinstance(x, bool) or not isinstance(x, int) for x in (first, last)):
        raise ValueError("Invalid word selection.")
    elif not cues[a]["linked"] or not cues[b]["linked"]:
        raise ValueError("The word data no longer matches the subtitles. Reload and select a full sentence.")
    if not 0 <= first < len(rows[a]) or not 0 <= last < len(rows[b]) or (a == b and first > last):
        raise ValueError("The selected words changed. Select them again.")
    clean = lambda text: "".join(c for c in text if c.isalnum())
    prefix = clean("".join(w for row in rows[:a] for w in row) + "".join(rows[a][:first]))
    chosen = "".join("".join(rows[i][first if i == a else 0:last + 1 if i == b else len(rows[i])]) for i in range(a, b + 1))
    if "expression" in selection and "".join(selection["expression"].split()) != "".join(chosen.split()):
        raise ValueError("The selected words changed. Reload the video and select them again.")
    text = clean(chosen)
    if not text:
        raise ValueError("Select at least one word.")
    return {"start": len(prefix), "end": len(prefix) + len(text), "text": text}


def occurrence_id(entry, anchor):
    marker = entry / ".pianpian-source-id"
    with _LOCK:
        if not marker.exists():
            with marker.open("x", encoding="utf-8") as f:
                f.write(str(uuid.uuid4()))
        identity = str(uuid.UUID(marker.read_text(encoding="utf-8").strip()))
    return hashlib.sha256(json.dumps([identity, anchor], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def preview(entry, library, data):
    path = source(entry, library)
    selection_anchor(entry, data.get("selection"))
    start, end = bounds(path, data)
    output = render_clip(path, start, end)
    return {"url": "/api/anki/audio/" + output.name, "start": start, "end": end, "duration": end - start}


def export(entry, library, data):
    path = source(entry, library)
    anchor = selection_anchor(entry, data.get("selection"))
    start, end = bounds(path, data)
    name = clip_name(path, start, end)
    if data.get("preview") != "/api/anki/audio/" + name:
        raise ValueError("The audio changed. Preview this selection before sending it to Anki.")
    audio = audio_path(name)
    fields = {}
    for key in ("expression", "pinyin", "meaning", "sentence", "translation"):
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > 20000:
            raise ValueError(f"Invalid {key} field (maximum 20,000 characters).")
        fields[key.title()] = value.strip()
    if not fields["Expression"]:
        raise ValueError("The Chinese expression cannot be empty.")
    deck, profile = data.get("deck"), data.get("profile")
    if not isinstance(deck, str) or not deck.strip() or len(deck) > 250:
        raise ValueError("Choose an existing deck or enter a new deck name.")
    if not isinstance(profile, str) or not profile:
        raise ValueError("Connect to Anki before sending this selection.")
    if not isinstance(data.get("update", False), bool):
        raise ValueError("Invalid update request.")
    title = (entry / "title.txt").read_text(encoding="utf-8").strip() if (entry / "title.txt").exists() else entry.name
    fields.update(Audio=f"[sound:{name}]", Source=f"{title} · {start:.3f}–{end:.3f} s")
    with _LOCK:
        result = client().export(deck.strip(), fields, occurrence_id(entry, anchor), update=data.get("update", False),
                                 expected_profile=profile, media=[(name, audio.read_bytes())], highlight=data.get("highlight", "none"),
                                 tones=data.get("tones", {}))
        if result.get("state") in ("added", "updated"):
            engine.save_config(anki={**engine.config().get("anki", {}), "deck": deck.strip()})
        return result


def open_note(data):
    if not isinstance(data.get("profile"), str) or not data["profile"]:
        raise ValueError("Connect to Anki before opening a note.")
    note_id = data.get("noteId")
    if isinstance(note_id, bool) or not str(note_id).isdigit():
        raise ValueError("Invalid Anki note ID.")
    client().open_note(int(note_id), expected_profile=data["profile"])
    return {"ok": True}
