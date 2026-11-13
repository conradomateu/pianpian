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


def test_windows_setup_cpu_default_and_optional_gpu_costs(browser, monkeypatch):  # noqa: F811
    """Real Chrome clicks, simulated Windows hardware/API. Does not install a runtime."""
    import runtimes
    c, url, handler = browser
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(ROOT / "scratch" / "setup-browser-missing-runtime"))
    original_get = handler.do_GET

    def activate(selector):
        c.js(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block:'center',behavior:'instant'}})")
        click(c, selector)
    options = {b: runtimes.status(backend=b) for b in ("cpu", "cuda", "vulkan")}
    submitted = []
    payload = {"needed": True, "config": {"library": "/videos", "data": "/tools"},
               "engine": {"engine": False, "current": False}, "engineMB": 460,
               "models": [{"id": "speech", "task": "transcribe", "about": "Whisper Q8", "size": 874188075, "ready": False},
                          {"id": "translation", "task": "translate", "about": "Hy-MT2 Q4", "size": 1133080448, "ready": False}],
               "runtime": options["cpu"], "runtimeOptions": options,
               "free": 10**10, "progress": {"state": "idle"}}

    def get(self):
        if self.path == "/setup.html":
            body, kind = (ROOT / "setup.html").read_bytes(), "text/html"
        elif self.path in ("/api/setup", "/api/setup-gpu"):
            value = payload if self.path == "/api/setup" else {"backend": "cuda", "message": "Test NVIDIA driver detected; inference not tested."}
            body, kind = json.dumps(value).encode(), "application/json"
        else:
            return original_get(self)
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def post(self):
        submitted.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        body = json.dumps({"error": "Stopped by the browser test before installing"}).encode()
        self.send_response(409)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    monkeypatch.setattr(handler, "do_GET", get)
    monkeypatch.setattr(handler, "do_POST", post, raising=False)
    navigate(c, url + "/setup.html")
    wait(c, "!document.querySelector('#plan').hidden")
    assert c.js("document.querySelector('[name=accel]').value") == "cpu"
    assert c.js("document.querySelector('#runtime-size').textContent") == "33 MB"
    assert c.js("document.querySelector('#sum').textContent.startsWith('2.0 GB models')")
    assert c.js("document.querySelector('#sum').textContent.includes('Python/packages/dictionary (size varies)')")
    activate("#detect-gpu")
    wait(c, "document.querySelector('[name=accel]').value === 'cuda'")
    assert c.js("document.querySelector('#runtime-size').textContent") == "1.3 GB"
    assert c.js("document.querySelector('#gpu-fallback').textContent.includes('33 MB extra')")
    assert c.js("document.querySelector('#sum').textContent.startsWith('3.4 GB models')")
    activate("input[value=translation]")
    assert c.js("document.querySelector('#runtime-size').textContent") == "685 MB"
    activate("input[value=speech]")
    assert c.js("document.querySelector('#runtime-size').textContent") == "not needed"
    assert c.js("document.querySelector('#sum').textContent.startsWith('0 MB models')")
    activate("#go")
    wait(c, "!document.querySelector('#err').hidden")
    assert submitted == [{"library": "/videos", "data": "/tools", "accel": "cuda", "models": [], "cleanup": False}]

    # Installed models remain optional: keeping speech must not implicitly enable translation's runtime.
    payload["config"]["models"] = ["speech"]
    for model in payload["models"]:
        model["ready"] = True
    navigate(c, url + "/setup.html")
    wait(c, "!document.querySelector('#plan').hidden")
    assert c.js("document.querySelector('#runtime-size').textContent") == "9 MB"
    assert not c.js("document.querySelector('input[value=translation]').checked")
    assert not c.js("document.querySelector('input[value=speech]').disabled")
    activate("input[value=speech]")
    assert c.js("document.querySelector('#runtime-size').textContent") == "not needed"
    activate("input[value=translation]")
    assert c.js("document.querySelector('#runtime-size').textContent") == "24 MB"
