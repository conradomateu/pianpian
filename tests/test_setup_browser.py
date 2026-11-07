"""The setup must show a rejected start while its progress card is still hidden."""
import json

from test_player_browser import ROOT, browser, click, navigate, wait  # noqa: F401


def test_setup_start_error_is_visible(browser, monkeypatch):  # noqa: F811 (shared pytest fixture)
    c, url, handler = browser
    original_get = handler.do_GET
    message = "Wait for the current job to finish, then run the setup."

    def get(self):
        if self.path == "/setup.html":
            body = (ROOT / "setup.html").read_bytes()
            content_type = "text/html"
        elif self.path == "/api/setup":
            body = json.dumps({"needed": True, "config": {"library": "/videos", "data": "/tools"},
                               "engine": {"engine": False, "current": False}, "engineMB": 650,
                               "models": [], "free": 10**10, "progress": {"state": "idle"}}).encode()
            content_type = "application/json"
        else:
            return original_get(self)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def post(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.dumps({"error": message}).encode()
        self.send_response(409)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    monkeypatch.setattr(handler, "do_GET", get)
    monkeypatch.setattr(handler, "do_POST", post, raising=False)
    navigate(c, url + "/setup.html")
    wait(c, "!document.querySelector('#plan').hidden")
    click(c, "#go")
    wait(c, f"document.querySelector('#err').textContent === {json.dumps(message)}")
    assert c.js("document.querySelector('#err').getBoundingClientRect().height > 0")
    assert c.js("!document.querySelector('#plan').hidden")
