"""Local AnkiConnect v6 client. Callers supply plain text except trusted Audio.

Text is escaped here before optional palette highlights and tones are added.
No write is retried: a lost response is resolved by looking up PianpianId on
the next export. Profile checks cannot make separate Anki API calls atomic.
"""
import base64
import html
import http.client
import json
import re
import threading


MODEL = "Pianpian"
FIELDS = ["PianpianId", "Expression", "Pinyin", "Meaning", "Sentence", "Translation", "Audio", "Source"]
HIGHLIGHTS = {"jade": "14,138,99", "coral": "222,59,38", "blue": "42,113,190", "gold": "176,127,16"}
# Stored with fields so existing note types need no template or stylesheet changes.
TONE_STYLE = "<style>" + "".join(
    f".pianpian-tone-{tone}{{color:{light}}}"
    f".nightMode .pianpian-tone-{tone},.night_mode .pianpian-tone-{tone}{{color:{dark}}}"
    for tone, (light, dark) in enumerate(zip(
        ("#C2352C", "#A86500", "#1B7A50", "#2B5FA6", "#8A7F74"),
        ("#FF7B70", "#F5B23C", "#46D39A", "#79B0FF", "#9A9086"),
    ), 1)
) + "</style>"
SETUP = "Open Anki Desktop and a profile, install AnkiConnect (add-on code 2055492159), then restart Anki and retry."
_WRITE_LOCK = threading.Lock()


class AnkiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _api_error(message):
    lower = message.lower()
    if any(word in lower for word in ("api key", "apikey", "authentication", "unauthorized", "forbidden")):
        return AnkiError("auth", "AnkiConnect rejected the API key. Enter the key from its configuration and retry.")
    if any(word in lower for word in ("collection is not", "collection not", "no collection", "collection unavailable", "profile is not")):
        return AnkiError("no_collection", "Open a profile in Anki Desktop and retry.")
    if "unsupported" in lower or "unknown action" in lower:
        return AnkiError("unsupported", "Update AnkiConnect and restart Anki; Pianpian requires its version 6 API.")
    return AnkiError("error", f"AnkiConnect: {message}")


def _filename(name):
    if not isinstance(name, str) or not name or name in (".", "..") or re.search(r'[\x00-\x1f/\\<>:"\[\]]', name):
        raise AnkiError("error", "Anki returned or was given an unsafe media filename.")
    return name


class Client:
    def __init__(self, port=8765, key=""):
        if type(port) is not int or not 1 <= port <= 65535:
            raise AnkiError("error", "AnkiConnect port must be a number between 1 and 65535.")
        if not isinstance(key, str):
            raise AnkiError("auth", "AnkiConnect API key must be text.")
        self.port = port
        self.key = key
        self.timeout = 10

    def _call(self, action, **params):
        # HTTPConnection uses neither proxy environment variables nor redirects.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        payload = {"action": action, "version": 6, "params": params}
        if self.key:
            payload["key"] = self.key
        try:
            connection.request("POST", "/", json.dumps(payload).encode("utf-8"), {"Content-Type": "application/json"})
            response = connection.getresponse()
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError("oversized response")
            data = json.loads(body)
            if not isinstance(data, dict) or set(data) != {"result", "error"}:
                raise ValueError("invalid response")
            if data["error"] is not None and not isinstance(data["error"], str):
                raise ValueError("invalid error")
            error = _api_error(data["error"]) if data["error"] is not None else None
            if response.status != 200:
                if response.status in (401, 403) and error and error.code == "auth":
                    raise error
                raise AnkiError("wrong_service", "This port did not respond as AnkiConnect. Check the port in AnkiConnect's configuration.")
            if error:
                raise error
            return data["result"]
        except TimeoutError as exc:
            raise AnkiError("unavailable", f"AnkiConnect timed out. {SETUP} The operation may have completed. Retry to check for the existing note; no write was automatically retried.") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise AnkiError("unavailable", f"Cannot reach AnkiConnect at 127.0.0.1:{self.port}. {SETUP} If an export was interrupted, retry to check whether the note was saved.") from exc
        except (ValueError, UnicodeError) as exc:
            raise AnkiError("wrong_service", "This port returned an invalid AnkiConnect response. Check the configured port.") from exc
        finally:
            connection.close()

    def _profile(self, expected=None):
        profile = self._call("getActiveProfile")
        if not isinstance(profile, str) or not profile:
            raise AnkiError("no_collection", "Open a profile in Anki Desktop and retry.")
        if expected is not None and profile != expected:
            raise AnkiError("profile_changed", "The active Anki profile changed. Refresh the connection and choose the destination again.")
        return profile

    def _write(self, profile, action, **params):
        self._profile(profile)
        return self._call(action, **params)

    def status(self):
        try:
            version = self._call("version")
            if type(version) is not int:
                raise AnkiError("wrong_service", "This port does not identify itself as AnkiConnect.")
            if version < 6:
                raise _api_error("unsupported version")
            profile = self._profile()
            decks = self._call("deckNames")
            if not isinstance(decks, list) or not all(isinstance(deck, str) for deck in decks):
                raise AnkiError("wrong_service", "AnkiConnect returned an invalid deck list.")
            self._profile(profile)
            return {"state": "connected", "message": f"Connected to Anki · {profile}", "decks": sorted(decks), "profile": profile}
        except AnkiError as exc:
            return {"state": "error" if exc.code == "profile_changed" else exc.code, "message": str(exc), "decks": [], "profile": None}

    def _schema(self):
        fields = self._call("modelFieldNames", modelName=MODEL)
        if not isinstance(fields, list) or fields[:1] != [FIELDS[0]] or not all(name in fields for name in FIELDS):
            raise AnkiError("schema", "The existing Pianpian note type has incompatible fields. Rename it in Anki so Pianpian can create its own note type, then retry.")

    def _existing(self, export_id):
        ids = self._call("findNotes", query=f'"PianpianId:{export_id}" OR "tag:pianpian::id::{export_id}"')
        if not isinstance(ids, list) or not all(type(note_id) is int and note_id > 0 for note_id in ids):
            raise AnkiError("wrong_service", "AnkiConnect returned invalid note IDs.")
        if not ids:
            return None
        notes = self._call("notesInfo", notes=ids)
        if not isinstance(notes, list) or len(notes) != len(ids):
            raise AnkiError("error", "Could not verify the existing Anki note. Refresh and retry.")
        matches = []
        for note in notes:
            if not isinstance(note, dict) or not isinstance(note.get("fields"), dict):
                raise AnkiError("error", "The existing Anki note disappeared. Refresh and retry.")
            identity_field = note["fields"].get("PianpianId", {})
            if not isinstance(identity_field, dict) or not isinstance(note.get("tags", []), list):
                raise AnkiError("wrong_service", "AnkiConnect returned invalid note fields or tags.")
            identity = identity_field.get("value")
            tagged = f"pianpian::id::{export_id}" in note.get("tags", [])
            if identity != export_id:
                if tagged:
                    raise AnkiError("identity", "This note's PianpianId was edited in Anki. Restore it before updating.")
                continue  # Anki field searches can also match longer values.
            if note.get("modelName") != MODEL or type(note.get("noteId")) is not int:
                raise AnkiError("schema", "This PianpianId belongs to a different note type. Resolve the conflict in Anki before exporting.")
            matches.append(note)
        if len(matches) > 1:
            raise AnkiError("identity", "More than one Anki note has this PianpianId. Resolve the duplicates in Anki before updating.")
        return matches[0] if matches else None

    def export(self, deck, fields, export_id, *, update=False, expected_profile=None, media=(), highlight="none", tones={}):
        """Add or explicitly update one occurrence; existing notes keep cards/tags/decks.

        Audio is trusted markup generated by the caller, never raw UI values.
        All other values, including Source, are plain text. Media are (basename, bytes) pairs.
        Tone segments reconstruct the exact plain field; omitted keys leave it uncolored.
        """
        if not isinstance(deck, str) or not deck.strip():
            raise AnkiError("error", "Choose or enter an Anki deck name.")
        if not isinstance(export_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", export_id):
            raise AnkiError("error", "Invalid Pianpian export identity.")
        if not isinstance(fields, dict) or any(name not in FIELDS or not isinstance(value, str) for name, value in fields.items()):
            raise AnkiError("error", "Anki fields must contain text with Pianpian field names.")
        if not fields.get("Expression", "").strip():
            raise AnkiError("error", "Enter an expression before exporting.")
        if type(update) is not bool:
            raise AnkiError("error", "Updating an Anki note requires explicit confirmation.")
        if not isinstance(highlight, str) or highlight not in ("none", *HIGHLIGHTS):
            raise AnkiError("error", "Choose a highlight color from Pianpian's palette.")
        if not isinstance(tones, dict) or any(key not in ("pinyin", "expression") for key in tones):
            raise AnkiError("error", "Tone metadata must contain only pinyin or expression segments.")
        values = {name: fields.get(name, "") if name == "Audio" else html.escape(fields.get(name, "")).replace("\n", "<br>") for name in FIELDS}
        colored = set()
        for key, parts in tones.items():
            if not isinstance(parts, list) or len(parts) > 20000:
                raise AnkiError("error", "Tone segments must be an array of at most 20,000 text/tone pairs.")
            length = 0
            for part in parts:
                if (not isinstance(part, list) or len(part) != 2 or not isinstance(part[0], str)
                        or type(part[1]) is not int or not 0 <= part[1] <= 5):
                    raise AnkiError("error", "Each tone segment must contain plain text and an integer tone from 0 to 5.")
                length += len(part[0])
                if length > 20000:
                    raise AnkiError("error", "Tone text must contain at most 20,000 characters.")
            name = key.title()
            if "".join(text for text, tone in parts) != fields.get(name, ""):
                raise AnkiError("error", f"Tone segments must reproduce the {key} field exactly.")
            rendered = []
            for text, tone in parts:
                text = html.escape(text).replace("\n", "<br>")
                if tone and text:
                    text = f'<span class="pianpian-tone-{tone}">{text}</span>'
                    colored.add(name)
                rendered.append(text)
            values[name] = "".join(rendered)
        if highlight != "none":
            rgb = HIGHLIGHTS[highlight]
            values["Expression"] = f'<span style="background-color:rgba({rgb},.18);border-bottom:2px solid rgb({rgb});color:inherit">{values["Expression"]}</span>'
        if highlight != "none" or "Expression" in colored:
            # Split plain text before escaping, so matching cannot cut through HTML entities.
            parts = fields.get("Sentence", "").split(fields["Expression"])
            values["Sentence"] = values["Expression"].join(html.escape(part).replace("\n", "<br>") for part in parts)
            if "Expression" in colored and len(parts) > 1:
                colored.add("Sentence")
        for name in colored:
            values[name] = TONE_STYLE + values[name]
        values["PianpianId"] = export_id
        media = list(media)
        for name, content in media:
            _filename(name)
            if not isinstance(content, bytes):
                raise AnkiError("error", "Anki media must contain file bytes.")
        with _WRITE_LOCK:
            profile = self._profile(expected_profile)
            existing = self._existing(export_id)
            note_id = existing["noteId"] if existing else None
            if existing:
                cards = existing.get("cards")
                if not isinstance(cards, list) or not cards or not all(type(card) is int and card > 0 for card in cards):
                    raise AnkiError("error", "The existing Anki note has no usable cards. Check it in Anki before updating.")
                info = self._call("cardsInfo", cards=cards[:1])
                if not isinstance(info, list) or len(info) != 1 or not isinstance(info[0], dict) or not isinstance(info[0].get("deckName"), str):
                    raise AnkiError("error", "Could not determine the existing note's deck. Refresh and retry.")
                deck = info[0]["deckName"]
            if note_id is not None and not update:
                self._profile(profile)
                return {"state": "exists", "noteId": note_id, "deck": deck}
            models = self._call("modelNames")
            if not isinstance(models, list) or not all(isinstance(name, str) for name in models):
                raise AnkiError("wrong_service", "AnkiConnect returned an invalid note type list.")
            if MODEL not in models:
                self._write(profile, "createModel", modelName=MODEL, inOrderFields=FIELDS,
                            css=".card { font-family: Arial, sans-serif; font-size: 24px; line-height: 1.5; text-align: center; padding: 24px; }\n.zh { font-size: 32px; }",
                            cardTemplates=[{
                    "Name": "Comprehension", "Front": '<div class="zh" lang="zh">{{Expression}}</div>{{Audio}}',
                    "Back": '{{FrontSide}}<hr id=answer><div>{{Pinyin}}</div><div>{{Meaning}}</div><br><div class="zh" lang="zh">{{Sentence}}</div><div>{{Translation}}</div><br><small>{{Source}}</small>',
                }])
            self._schema()
            if note_id is None:
                self._write(profile, "createDeck", deck=deck)
            for name, content in media:
                stored = self._write(profile, "storeMediaFile", filename=name, data=base64.b64encode(content).decode("ascii"), deleteExisting=False)
                stored = _filename(stored)
                values["Audio"] = values["Audio"].replace(f"[sound:{name}]", f"[sound:{stored}]")
            if note_id is not None:
                self._write(profile, "updateNoteFields", note={"id": note_id, "fields": values})
                state = "updated"
            else:
                note_id = self._write(profile, "addNote", note={"deckName": deck, "modelName": MODEL, "fields": values,
                    "options": {"allowDuplicate": False, "duplicateScope": "collection"},
                    "tags": ["pianpian", f"pianpian::id::{export_id}"]})
                if type(note_id) is not int or note_id <= 0:
                    raise AnkiError("error", "Anki did not confirm the new note. Retry to check whether it was saved.")
                state = "added"
            return {"state": state, "noteId": note_id, "deck": deck}

    def open_note(self, note_id, expected_profile=None):
        if type(note_id) is not int or note_id <= 0:
            raise AnkiError("error", "Invalid Anki note ID.")
        profile = self._profile(expected_profile)
        self._write(profile, "guiBrowse", query=f"nid:{note_id}")
        return {"ok": True}
