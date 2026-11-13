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
    submitted, detections = [], []
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
            value = payload if self.path == "/api/setup" else {"backend": "cuda", "message": "Test NVIDIA driver detected; inference not tested.", "benchmarkAvailable": True}
            if self.path == "/api/setup-gpu":
                detections.append(self.path)
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
    wait(c, "document.querySelector('#gpu-note').textContent.startsWith('Test NVIDIA')")
    assert detections == ["/api/setup-gpu"] and not submitted
    assert c.js("document.querySelector('[name=accel]').value") == "cpu"
    assert c.js("document.querySelector('#benchmark-gpu').disabled")  # engine is not installed yet
    activate("#detect-gpu")
    wait(c, "!document.querySelector('#detect-gpu').disabled")
    assert len(detections) == 2 and not submitted
    assert c.js("document.querySelector('[name=accel]').value") == "cpu"
    activate("select[name=accel]")
    for key, code in (("Escape", 27), ("n", 78), ("Enter", 13), ("Tab", 9)):
        for event in ("keyDown", "keyUp"):
            c.call("Input.dispatchKeyEvent", type=event, key=key, code="KeyN" if key == "n" else key, windowsVirtualKeyCode=code, text="n" if key == "n" and event == "keyDown" else "")
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


def test_speed_comparison_requires_a_click_and_reports_only_local_measurements(browser, monkeypatch):  # noqa: F811
    """Real browser interaction; fake CPU/CUDA timings deliberately do not validate Windows performance."""
    import runtimes
    c, url, handler = browser
    monkeypatch.setenv("PIANPIAN_RUNTIME", str(ROOT / "scratch" / "setup-browser-missing-runtime"))
    original_get = handler.do_GET
    options = {b: runtimes.status(backend=b) for b in ("cpu", "cuda", "vulkan")}
    payload = {"needed": True, "config": {"library": "/videos", "data": "/tools"},
               "engine": {"engine": True, "current": True}, "engineMB": 460, "models": [],
               "runtime": options["cpu"], "runtimeOptions": options, "free": 10**10, "progress": {"state": "idle"}}
    measured = {"tools": [{"tool": "whisper", "status": "measured", "cpu_seconds": 10.0, "gpu_seconds": 2.5,
                            "speedup": 4.0, "workload": "30 seconds of the bundled demo",
                            "estimate": {"label": "speech-only time for 10 minutes", "cpu_seconds": 200.0, "gpu_seconds": 50.0}},
                           {"tool": "llama", "status": "unconfirmed", "reason": "CUDA offload was not confirmed; no estimate."}]}
    submissions, polls = [], []

    def send(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def get(self):
        if self.path == "/setup.html":
            body = (ROOT / "setup.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if self.path == "/api/setup":
            return send(self, payload)
        if self.path == "/api/setup-gpu":
            return send(self, {"backend": "cuda", "message": "Installed CUDA tools detected; inference not measured.", "benchmarkAvailable": True})
        if self.path == "/api/jobs":
            polls.append(self.path)
            done = len(polls) > 1
            return send(self, [{"id": 42, "state": "done" if done else "running", "log": ["@benchmark " + json.dumps(measured)] if done else []}])
        return original_get(self)

    def post(self):
        submissions.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        assert self.headers["X-Kit"] == "1"
        send(self, {"id": 42, "state": "queued", "log": []})

    monkeypatch.setattr(handler, "do_GET", get)
    monkeypatch.setattr(handler, "do_POST", post, raising=False)
    navigate(c, url + "/setup.html")
    wait(c, "!document.querySelector('#benchmark-gpu').disabled")
    assert not submissions and not polls
    assert c.js("document.querySelector('[name=accel]').value") == "cpu"
    assert c.js("document.querySelector('#gpu-speed').textContent") == ""
    c.js("document.querySelector('#benchmark-gpu').scrollIntoView({block:'center',behavior:'instant'})")
    click(c, "#benchmark-gpu")
    wait(c, "document.querySelector('#gpu-speed').textContent.includes('4.0× faster')")
    assert submissions == [("/api/setup-benchmark", {})] and len(polls) >= 2
    text = c.js("document.querySelector('#gpu-speed').textContent")
    assert "CPU 10.0 s" in text and "CUDA 2.5 s" in text
    assert "CPU 3.3 min / CUDA 50.0 s" in text and "not a guaranteed completion time" in text
    assert "CUDA offload was not confirmed; no estimate." in text
    assert c.js("document.querySelector('[name=accel]').value") == "cpu"
    assert not c.js("document.querySelector('#benchmark-gpu').disabled")


def test_resources_reopens_models_and_acceleration_but_link_is_absent_from_demo(browser, monkeypatch):  # noqa: F811
    c, url, handler = browser
    original_get = handler.do_GET
    opened = []

    def get(self):
        if self.path != "/setup.html?again":
            return original_get(self)
        opened.append(self.path)
        body = b'<!doctype html><title>Setup destination</title><p id="setup-destination">Models and acceleration</p>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    monkeypatch.setattr(handler, "do_GET", get)
    navigate(c, url + "/app.html")
    wait(c, "document.querySelector('#toolslink') && document.querySelector('.load-state').hidden")
    assert not c.js("document.querySelector('[data-resources]').parentElement.open")
    c.js("document.querySelector('#player details:has([data-resources]) > summary').scrollIntoView({block:'center',behavior:'instant'})")
    click(c, "#player details:has([data-resources]) > summary")
    wait(c, "document.querySelector('[data-resources]').parentElement.open")
    assert c.js("document.querySelector('#toolslink').textContent") == "Models & acceleration"
    wait(c, "(() => { const a = document.querySelector('#toolslink'), r = a.getBoundingClientRect(); return a.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)) && !document.querySelector('[data-resources]').getAnimations().some(a => a.playState === 'running'); })()")
    click(c, "#toolslink")
    wait(c, "!!document.querySelector('#setup-destination')")
    assert opened == ["/setup.html?again"]
    assert c.js("location.href") == url + "/setup.html?again"
    navigate(c, url + "/app.html?demo#v=pianpian-day")
    wait(c, "document.documentElement.classList.contains('demo') && document.querySelector('video')")
    assert not c.js("!!document.querySelector('#toolslink')")
