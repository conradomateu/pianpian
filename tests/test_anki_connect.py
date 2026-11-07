"""AnkiConnect contracts against an isolated loopback fake; no personal Anki data."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
from pathlib import Path
import re
import socket
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import anki_connect as anki


class Collection:
    def __init__(self):
        self.profile = "Study"
        self.decks = ["Default"]
        self.fields = None
        self.notes = {}
        self.calls = []
        self.media = {}
        self.failure = None
        self.after = lambda action: None
        self.lose_add_response = False
        self.key = ""
        self.http_status = 200
        self.raw = None

    def call(self, request):
        action, params = request["action"], request["params"]
        self.calls.append((action, deepcopy(params)))
        assert request["version"] == 6
        if request.get("key", "") != self.key:
            return {"result": None, "error": "valid api key must be provided"}
        if self.failure:
            return {"result": None, "error": self.failure}
        if action == "version":
            result = 6
        elif action == "getActiveProfile":
            result = self.profile
        elif action == "deckNames":
            result = self.decks
        elif action == "modelNames":
            result = [anki.MODEL] if self.fields else []
        elif action == "modelFieldNames":
            result = self.fields
        elif action == "createModel":
            self.fields = params["inOrderFields"]
            result = {"name": anki.MODEL}
        elif action == "findNotes":
            assert '"PianpianId:' in params["query"] and '"tag:pianpian::id::' in params["query"]
            identity = params["query"].split(':', 1)[1].split('"', 1)[0]
            result = [nid for nid, note in self.notes.items() if identity in note["fields"]["PianpianId"]["value"]
                      or f"pianpian::id::{identity}" in note["tags"]]
        elif action == "notesInfo":
            result = [self.notes[nid] for nid in params["notes"]]
        elif action == "cardsInfo":
            result = [{"cardId": card, "deckName": note["deck"]} for card in params["cards"]
                      for note in self.notes.values() if card in note["cards"]]
        elif action == "createDeck":
            self.decks.append(params["deck"])
            result = len(self.decks)
        elif action == "storeMediaFile":
            assert params["deleteExisting"] is False
            assert set(params) == {"filename", "data", "deleteExisting"}
            result = "stored-" + params["filename"]
            self.media[result] = base64.b64decode(params["data"])
        elif action == "addNote":
            note = params["note"]
            assert note["options"] == {"allowDuplicate": False, "duplicateScope": "collection"}
            result = 1000 + len(self.notes)
            self.notes[result] = {"noteId": result, "modelName": note["modelName"], "tags": note["tags"],
                                  "fields": {name: {"value": value} for name, value in note["fields"].items()},
                                  "cards": [9000 + result], "due": 42, "deck": note["deckName"]}
        elif action == "updateNoteFields":
            note = self.notes[params["note"]["id"]]
            note["fields"].update({name: {"value": value} for name, value in params["note"]["fields"].items()})
            result = None
        elif action == "guiBrowse":
            result = [9000]
        else:
            raise AssertionError(action)
        self.after(action)
        return {"result": result, "error": None}


@pytest.fixture
def service():
    collection = Collection()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps(collection.call(request)).encode() if collection.raw is None else collection.raw
            if request["action"] == "addNote" and collection.lose_add_response:
                collection.lose_add_response = False
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            self.send_response(collection.http_status)
            self.send_header("Location", "https://example.invalid/must-not-follow")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield collection, anki.Client(server.server_port)
    server.shutdown()
    server.server_close()
    thread.join()


def test_status_is_usable_authenticated_collection(service, monkeypatch):
    collection, client = service
    monkeypatch.setenv("HTTP_PROXY", "http://example.invalid:9876")
    assert client.status() == {"state": "connected", "message": "Connected to Anki · Study", "decks": ["Default"], "profile": "Study"}
    collection.key = "secret"
    assert client.status()["state"] == "auth"
    client.key = "secret"
    assert client.status()["state"] == "connected"
    collection.failure = "collection is not available"
    assert client.status()["state"] == "no_collection"
    collection.failure = "unsupported action"
    assert client.status()["state"] == "unsupported"


@pytest.mark.parametrize("body,status", [(b"<html>another service</html>", 200), (b"{}", 200),
                                        (b'{"result": 6, "error": null}', 302), (b"", 401),
                                        (b'{"error": "Only this local demo session can execute examples."}', 403),
                                        (b'{"result": null, "error": "Only this local demo session can execute examples."}', 403)])
def test_wrong_service_and_redirect_not_followed(service, body, status):
    collection, client = service
    collection.raw, collection.http_status = body, status
    assert client.status()["state"] == "wrong_service"


@pytest.mark.parametrize("status", [200, 401, 403])
def test_known_anki_auth_error_requires_valid_envelope(service, status):
    collection, client = service
    collection.raw = b'{"result": null, "error": "valid api key must be provided"}'
    collection.http_status = status
    assert client.status()["state"] == "auth"


def test_closed_port_gives_truthful_setup_instructions():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    status = anki.Client(port).status()
    assert status["state"] == "unavailable"
    assert "Open Anki Desktop" in status["message"] and "2055492159" in status["message"]


def test_add_escape_upload_and_explicit_update_preserve_identity(service):
    collection, client = service
    fields = {"Expression": '<img src=x onerror="alert(1)">你好', "Pinyin": "nǐ & hǎo", "Meaning": "line1\nline2",
              "Sentence": "<script>oops</script>", "Translation": '"quoted"',
              "Audio": "[sound:clip.mp3]", "Source": '<img src=x onerror="alert(1)">标题 & 视频 · 00:01–00:03'}
    result = client.export("新牌组::Video", fields, "occurrence-1", expected_profile="Study", media=[("clip.mp3", b"mp3-bytes")])
    assert result == {"state": "added", "noteId": 1000, "deck": "新牌组::Video"}
    assert collection.decks[-1] == "新牌组::Video" and collection.fields == anki.FIELDS
    assert collection.media == {"stored-clip.mp3": b"mp3-bytes"}
    note = collection.notes[1000]
    assert note["fields"]["Expression"]["value"] == '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;你好'
    assert note["fields"]["Pinyin"]["value"] == "nǐ &amp; hǎo"
    assert note["fields"]["Meaning"]["value"] == "line1<br>line2"
    assert note["fields"]["Sentence"]["value"] == "&lt;script&gt;oops&lt;/script&gt;"
    assert note["fields"]["Audio"]["value"] == "[sound:stored-clip.mp3]"
    assert note["fields"]["Source"]["value"] == '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;标题 &amp; 视频 · 00:01–00:03'
    note["tags"].append("user::keep")
    before = deepcopy(note)
    collection.calls.clear()
    assert client.export("Other", {"Expression": "changed"}, "occurrence-1") == {"state": "exists", "noteId": 1000, "deck": "新牌组::Video"}
    assert note == before
    assert {action for action, _ in collection.calls} <= {"getActiveProfile", "findNotes", "notesInfo", "cardsInfo"}
    assert client.export("Other", {"Expression": "changed"}, "occurrence-1", update=True)["state"] == "updated"
    assert {key: value for key, value in note.items() if key != "fields"} == {key: value for key, value in before.items() if key != "fields"}
    assert note["fields"]["Expression"]["value"] == "changed"
    assert "Other" not in collection.decks
    assert client.export("Other", {"Expression": "changed"}, "occurrence-2")["state"] == "added"
    assert len(collection.notes) == 2


def test_schema_conflict_prevents_every_write(service):
    collection, client = service
    collection.fields = ["Expression", "PianpianId"]
    with pytest.raises(anki.AnkiError, match="incompatible fields"):
        client.export("New deck", {"Expression": "你好"}, "id", media=[("clip.mp3", b"audio")])
    assert collection.decks == ["Default"] and not collection.notes and not collection.media


def test_highlight_escapes_text_and_updates_without_changing_cards(service):
    collection, client = service
    fields = {"Expression": "公园", "Sentence": "去公园，公园很好。<script>bad</script>", "Pinyin": "gōngyuán"}
    result = client.export("Default", fields, "colored", highlight="jade")
    note = collection.notes[result["noteId"]]
    before = deepcopy(note)
    assert note["fields"]["Sentence"]["value"].count("<span ") == 2
    assert "&lt;script&gt;" in note["fields"]["Sentence"]["value"]
    assert "color:inherit" in note["fields"]["Expression"]["value"]
    assert note["fields"]["Pinyin"]["value"] == "gōngyuán"
    assert client.export("Default", fields, "colored", highlight="blue")["state"] == "exists"
    assert note == before
    client.export("Default", fields, "colored", update=True, highlight="none")
    assert note["fields"]["Expression"]["value"] == "公园"
    assert {k: v for k, v in note.items() if k != "fields"} == {k: v for k, v in before.items() if k != "fields"}


def test_highlight_never_matches_inside_html_entities(service):
    collection, client = service
    result = client.export("Default", {"Expression": "lt", "Sentence": "< lt"}, "entities", highlight="coral")
    assert collection.notes[result["noteId"]]["fields"]["Sentence"]["value"].startswith('&lt; <span ')


@pytest.mark.parametrize("highlight", ["none", *anki.HIGHLIGHTS])
def test_tones_preserve_escaped_text_and_literal_sentence_matches(service, highlight):
    collection, client = service
    expression = '你<&\n"好'
    fields = {"Expression": expression, "Pinyin": 'nǐ &\nhǎo <img src=x>',
              "Sentence": f'<script>before</script> {expression}，{expression}!'}
    tones = {"expression": [['你<', 3], ['&\n"', 0], ['好', 3]],
             "pinyin": [['nǐ', 3], [' &\n', 0], ['hǎo', 3], [' <img src=x>', 0]]}
    original = deepcopy(tones)
    client.export("Default", fields, "tones", tones=tones, highlight=highlight)
    stored = collection.notes[1000]["fields"]
    for name, plain in fields.items():
        value = stored[name]["value"]
        assert value.startswith(anki.TONE_STYLE) and value.count("<style>") == 1
        content = value.removeprefix(anki.TONE_STYLE)
        assert html.unescape(re.sub(r"<[^>]*>", "", content.replace("<br>", "\n"))) == plain
        assert "<script>" not in content and "<img " not in content
    assert stored["Expression"]["value"].count('class="pianpian-tone-3"') == 2
    assert stored["Sentence"]["value"].count('class="pianpian-tone-3"') == 4
    assert stored["Sentence"]["value"].count("background-color:") == (0 if highlight == "none" else 2)
    assert tones == original


def test_tone_palette_matches_kit_light_dark_and_is_scoped(service):
    collection, client = service
    kit = (Path(__file__).resolve().parents[1] / "assets" / "kit.css").read_text()
    parts = [[str(tone), tone] for tone in range(1, 6)]
    client.export("Default", {"Expression": "你好", "Pinyin": "12345"}, "palette", tones={"pinyin": parts})
    value = collection.notes[1000]["fields"]["Pinyin"]["value"]
    for tone, light, dark in [(1, "#C2352C", "#FF7B70"), (2, "#A86500", "#F5B23C"), (3, "#1B7A50", "#46D39A"),
                              (4, "#2B5FA6", "#79B0FF"), (5, "#8A7F74", "#9A9086")]:
        assert f"--tone{tone}:{light}" in kit and f"--tone{tone}:{dark}" in kit
        assert f".pianpian-tone-{tone}{{color:{light}}}" in value
        assert f".nightMode .pianpian-tone-{tone},.night_mode .pianpian-tone-{tone}{{color:{dark}}}" in value
        assert f'<span class="pianpian-tone-{tone}">{tone}</span>' in value
    assert collection.notes[1000]["fields"]["Expression"]["value"] == "你好"
    assert collection.notes[1000]["fields"]["Sentence"]["value"] == ""


def test_tones_never_match_entities_or_style_uncolored_fields(service):
    collection, client = service
    fields = {"Expression": "lt", "Sentence": "< lt\n&", "Pinyin": "plain &\ntext"}
    client.export("Default", fields, "entities-tone", tones={"expression": [["lt", 1]], "pinyin": [[fields["Pinyin"], 0]]})
    stored = collection.notes[1000]["fields"]
    assert stored["Sentence"]["value"] == anki.TONE_STYLE + '&lt; <span class="pianpian-tone-1">lt</span><br>&amp;'
    assert stored["Pinyin"]["value"] == "plain &amp;<br>text"
    client.export("Default", {**fields, "Sentence": "< without match"}, "no-match", tones={"expression": [["lt", 1]]})
    assert collection.notes[1001]["fields"]["Sentence"]["value"] == "&lt; without match"


def test_tone_toggles_update_only_fields_of_existing_note_type(service):
    collection, client = service
    collection.fields = anki.FIELDS[:]  # Existing user note type, with its own templates/styles.
    fields = {"Expression": "你好", "Pinyin": "nǐ hǎo", "Sentence": "你好！"}
    tones = {"expression": [["你", 3], ["好", 3]], "pinyin": [["nǐ", 3], [" ", 0], ["hǎo", 3]]}
    client.export("Default", fields, "toggle", highlight="jade")
    note = collection.notes[1000]
    note["tags"].append("user::keep")
    note["history"] = [{"ease": 3, "interval": 7}]
    original = deepcopy(note)
    assert client.export("Other", fields, "toggle", tones=tones)["state"] == "exists"
    assert note == original
    for enabled, highlight in [(tones, "jade"), (tones, "none"), ({"pinyin": tones["pinyin"]}, "coral"), ({}, "none")]:
        collection.calls.clear()
        result = client.export("Other", fields, "toggle", tones=enabled, highlight=highlight, update=True)
        assert result == {"state": "updated", "noteId": 1000, "deck": "Default"}
        assert {k: v for k, v in note.items() if k != "fields"} == {k: v for k, v in original.items() if k != "fields"}
        assert {action for action, _ in collection.calls} <= {
            "getActiveProfile", "findNotes", "notesInfo", "cardsInfo", "modelNames", "modelFieldNames", "updateNoteFields"}
        for name in ("Expression", "Pinyin", "Sentence"):
            value = note["fields"][name]["value"]
            assert ("<style>" in value) == (("expression" if name == "Sentence" else name.lower()) in enabled)
        assert ("background-color:" in note["fields"]["Expression"]["value"]) == (highlight != "none")
    assert all(note["fields"][name]["value"] == text for name, text in fields.items())


@pytest.mark.parametrize("tones", [
    None, [], "pinyin", {"sentence": []}, {"Pinyin": []}, {"pinyin": None}, {"pinyin": {}},
    {"pinyin": [["nǐ", True]]}, {"pinyin": [["nǐ", 3.0]]}, {"pinyin": [["nǐ", "3"]]},
    {"pinyin": [["nǐ", -1]]}, {"pinyin": [["nǐ", 6]]}, {"pinyin": [["nǐ", None]]},
    {"pinyin": [[42, 3]]}, {"pinyin": [["nǐ"]]}, {"pinyin": [["nǐ", 3, "extra"]]},
    {"pinyin": [("nǐ", 3)]}, {"pinyin": []}, {"pinyin": [[" nǐ", 3]]},
    {"pinyin": [["<b>nǐ</b>", 3]]}, {"pinyin": [["x" * 20001, 1]]},
    {"pinyin": [["x" * 10001, 1], ["y" * 10000, 2]]}, {"pinyin": [["", 0]] * 20001},
    {"pinyin": [["nǐ", 3]], "expression": [["wrong", 1]]},
])
def test_invalid_tones_rejected_before_every_anki_request(service, tones):
    collection, client = service
    with pytest.raises(anki.AnkiError, match="[Tt]one"):
        client.export("Default", {"Expression": "你", "Pinyin": "nǐ"}, "bad-tone", tones=tones,
                      media=[("clip.mp3", b"audio")], update=True)
    assert not collection.calls


@pytest.mark.parametrize("highlight", ['red;position:fixed', '<img src=x>', {}, None])
def test_invalid_highlight_rejected_before_any_anki_request(service, highlight):
    collection, client = service
    with pytest.raises(anki.AnkiError, match="palette"):
        client.export("Default", {"Expression": "你好"}, "bad-color", highlight=highlight)
    assert not collection.calls


def test_profile_change_blocks_writes_and_open(service):
    collection, client = service
    with pytest.raises(anki.AnkiError) as failure:
        client.export("New", {"Expression": "你好"}, "id", expected_profile="Other")
    assert failure.value.code == "profile_changed"
    assert not collection.fields
    collection.fields = anki.FIELDS[:]
    collection.after = lambda action: setattr(collection, "profile", "Other") if action == "modelFieldNames" else None
    with pytest.raises(anki.AnkiError) as failure:
        client.export("New", {"Expression": "你好"}, "id", expected_profile="Study")
    assert failure.value.code == "profile_changed"
    assert not collection.notes and collection.decks == ["Default"]
    with pytest.raises(anki.AnkiError):
        client.open_note(1000, expected_profile="Study")
    assert "guiBrowse" not in [action for action, _ in collection.calls]
    assert client.open_note(1000, expected_profile="Other") == {"ok": True}
    assert collection.calls[-1] == ("guiBrowse", {"query": "nid:1000"})


def test_lost_add_response_next_attempt_finds_note_without_write_retry(service):
    collection, client = service
    collection.lose_add_response = True
    with pytest.raises(anki.AnkiError) as failure:
        client.export("Default", {"Expression": "你好"}, "id")
    assert failure.value.code == "unavailable"
    assert len(collection.notes) == 1
    assert client.export("Default", {"Expression": "你好"}, "id")["state"] == "exists"
    assert [action for action, _ in collection.calls].count("addNote") == 1


def test_timeout_after_mutation_does_not_retry(service, monkeypatch):
    collection, client = service
    original = anki.http.client.HTTPConnection.getresponse

    def timeout_after_response(connection):
        response = original(connection)
        if collection.notes:
            raise TimeoutError("response lost after commit")
        return response

    with monkeypatch.context() as patch:
        patch.setattr(anki.http.client.HTTPConnection, "getresponse", timeout_after_response)
        with pytest.raises(anki.AnkiError, match="may have completed"):
            client.export("Default", {"Expression": "你好"}, "id")
    assert client.export("Default", {"Expression": "你好"}, "id")["state"] == "exists"
    assert [action for action, _ in collection.calls].count("addNote") == 1


def test_identity_lookup_survives_tag_deletion_and_refuses_tampering(service):
    collection, client = service
    client.export("Default", {"Expression": "你好"}, "id")
    collection.notes[1000]["tags"] = []
    assert client.export("Default", {"Expression": "你好"}, "id")["state"] == "exists"
    collection.notes[1000]["tags"] = ["pianpian::id::id"]
    collection.notes[1000]["fields"]["PianpianId"]["value"] = "edited"
    with pytest.raises(anki.AnkiError, match="was edited"):
        client.export("Default", {"Expression": "你好"}, "id", update=True)


def test_concurrent_clients_serialize_occurrence_creation(service):
    collection, client = service
    other = anki.Client(client.port)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(c.export, "Default", {"Expression": "你好"}, "same-id") for c in (client, other)]
        assert sorted(f.result()["state"] for f in futures) == ["added", "exists"]
    assert len(collection.notes) == 1


@pytest.mark.parametrize("port", [True, 0, 65536, "8765", "https://example.com"])
def test_endpoint_cannot_be_external(port):
    with pytest.raises(anki.AnkiError):
        anki.Client(port)
