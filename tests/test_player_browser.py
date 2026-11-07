"""Browser regression checks using the existing Chrome helper; no extra packages.

Uses only the self-made demo. Skips when Chrome/Brave/Chromium is unavailable.
"""
import base64
import functools
import json
import shutil
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import build_site, shots  # noqa: E402


@pytest.fixture
def browser(monkeypatch):
    exe = next((b for b in shots.BROWSERS if Path(b).exists()), None)
    if not exe:
        pytest.skip("Chrome, Brave or Chromium required")
    import server
    monkeypatch.setitem(server.CFG, "library", ROOT / "demo" / "library")
    videos = server.library()
    detail = server.describe(server.entry_path(videos[0]["id"]))
    (ROOT / "scratch").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / "scratch", prefix="player-test-") as directory:
        dest = Path(directory)
        shutil.copy(ROOT / "app.html", dest)
        shutil.copy(ROOT / "site" / "index.html", dest / "index.html")
        shutil.copytree(ROOT / "design" / "icons", dest / "design" / "icons")
        shutil.copytree(ROOT / "assets", dest / "assets")
        shutil.copytree(ROOT / "demo", dest / "demo")
        shutil.copytree(ROOT / "demo" / "library", dest / "library")
        build_site.demo_api(dest / "demo" / "api", "test")
        videos.append({**videos[0], "id": "second", "title": "Second demo"})
        shutil.copytree(dest / "library" / "pianpian-day", dest / "library" / "second")

        class Handler(build_site.RangedHandler):
            fail = False
            platform = "darwin"
            update = None
            delay = 0
            track_gate = threading.Event()
            track_gate.set()
            fail_tracks = False
            video_ranges = []
            video_gate = threading.Event()
            video_gate.set()
            frame_gate = threading.Event()
            frame_gate.set()

            def do_GET(self):
                if self.path == '/frame-gate.gif':
                    self.frame_gate.wait(15)
                    self.send_response(204)
                    self.end_headers()
                    return
                if self.path.endswith('.mp4'):
                    self.video_ranges.append(self.headers.get('Range'))
                    self.video_gate.wait(15)
                if '/pianpian-day/' in self.path and self.path.endswith('.srt'):
                    self.track_gate.wait(10)
                    if self.fail_tracks:
                        self.send_error(503)
                        return
                if self.path.endswith('/pianpian-day') or self.path.endswith('/pianpian-day.json'):
                    time.sleep(self.delay)
                if self.path.startswith('/api/'):
                    if self.path.startswith('/api/videos/') and self.fail:
                        self.send_error(503)
                        return
                    data = {"/api/setup": {"needed": False}, "/api/jobs": [],
                             "/api/status": {"library": "demo", "engine": True, "platform": self.platform, "update": self.update},
                            "/api/videos": videos}.get(self.path, detail)
                    if self.path == '/api/videos/second':
                        data = {**detail, "id": "second", "title": "Second demo"}
                    body = json.dumps(data).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    super().do_GET()

        srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=dest))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        c = shots.Chrome(exe, str(dest / "profile"))
        try:
            target = next(t for t in c.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
            c.session = c.call("Target.attachToTarget", targetId=target["targetId"], flatten=True)["sessionId"]
            c.call("Page.enable")
            c.call("Network.enable")
            c.call("Network.setBlockedURLs", urls=["https://*"])  # Fonts/analytics must not gate local regression checks.
            yield c, f"http://127.0.0.1:{srv.server_port}", Handler
        finally:
            Handler.track_gate.set()
            Handler.video_gate.set()
            Handler.frame_gate.set()
            c.close()
            srv.shutdown()
            srv.server_close()


def wait(c, condition):
    assert c.js("""new Promise(resolve => {
      const end = Date.now() + 8000;
      const check = () => {
        try { if (CONDITION) { resolve(true); return; } } catch {}
        if (Date.now() > end) resolve(false); else setTimeout(check, 30);
      }; check();
    })""".replace("CONDITION", condition)), (condition, c.js("({url:location.href,time:document.querySelector('video')?.currentTime, state:document.querySelector('video')?.readyState, text:document.querySelector('[data-load-text]')?.textContent})"))


def tap_in_frame(c, expr):
    """A real touch tap on an element inside the demo iframe (expr runs in the iframe's document)."""
    point = c.js(f"""(() => {{ const f = document.querySelector('iframe'), d = f.contentDocument, r = f.getBoundingClientRect();
      const b = ({expr}).getBoundingClientRect(); return [r.x+b.x+b.width/2, r.y+b.y+b.height/2]; }})()""")
    c.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": point[0], "y": point[1]}])
    c.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])


def click(c, selector):
    point = c.js(f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; }})()")
    assert point
    c.call("Input.dispatchMouseEvent", type="mouseMoved", x=point[0], y=point[1])
    for event in ("mousePressed", "mouseReleased"):
        c.call("Input.dispatchMouseEvent", type=event, x=point[0], y=point[1], button="left", clickCount=1)


def navigate(c, url):
    c.js("window.__leaving = true")
    c.call("Page.navigate", url=url)
    wait(c, "!window.__leaving && document.readyState === 'complete'")


# the server (updates.check_app) sends only this platform's file, or none: then the card links the release page
@pytest.mark.parametrize("platform,download", [("win32", "https://example.test/Pianpian-Windows-Setup.exe"), ("win32", None),
                                               ("darwin", "https://example.test/Pianpian-macOS.dmg")])
def test_update_action_matches_the_server_platform(browser, platform, download):
    c, url, handler = browser
    handler.platform = platform
    handler.update = {"version": "0.2.0", "url": "https://example.test/release", "download": download}
    navigate(c, url + "/app.html")
    wait(c, "!document.querySelector('#upd').hidden && document.querySelector('#upddl').textContent === 'Download'")
    c.js("document.querySelector('#upddl').addEventListener('click', e => { window.clickedUpdate = e.currentTarget.href; e.preventDefault(); })")
    click(c, '#upddl')
    wait(c, f"window.clickedUpdate === {json.dumps(download or handler.update['url'])}")


@pytest.mark.parametrize('width', [900, 390])
def test_grammar_close_stays_fixed_while_examples_scroll(browser, width):
    c, url, _ = browser
    c.call('Emulation.setDeviceMetricsOverride', width=width, height=600, deviceScaleFactor=1, mobile=False)
    navigate(c, url + '/app.html')
    wait(c, "document.querySelector('.item') && document.querySelector('.load-state').hidden")
    click(c, '.item')
    wait(c, "document.querySelector('video').readyState >= 3 && document.querySelector('.load-state').hidden")
    c.js("document.querySelector('details:has(.grammar) > summary').scrollIntoView({block:'center', behavior:'instant'})")
    click(c, 'details:has(.grammar) > summary')
    wait(c, "document.querySelector('details:has(.grammar)').open")
    before = c.js("document.querySelector('[data-grammar-close]').getBoundingClientRect().toJSON()")
    assert c.js("""(() => {
      const button = document.querySelector('[data-grammar-close]'), b = button.getBoundingClientRect();
      const icon = button.querySelector('svg').getBoundingClientRect();
      return Math.abs(b.x + b.width/2 - icon.x - icon.width/2) < 1 &&
        Math.abs(b.y + b.height/2 - icon.y - icon.height/2) < 1;
    })()""")
    x, y = c.js("(() => { const r=document.querySelector('.grammar-body').getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; })()")
    c.call('Input.dispatchMouseEvent', type='mouseMoved', x=x, y=y)
    c.call('Input.dispatchMouseEvent', type='mouseWheel', x=x, y=y, deltaX=0, deltaY=1500)
    wait(c, "document.querySelector('.grammar-body').scrollTop > 100")
    assert c.js("document.querySelector('[data-grammar-close]').getBoundingClientRect().toJSON()") == before
    assert c.js("document.querySelector('.grammar').scrollTop") == 0
    click(c, '[data-grammar-close]')
    assert c.js("!document.querySelector('details:has(.grammar)').open && document.activeElement.matches('details:has(.grammar) > summary')")


def test_resume_retry_and_player_feedback(browser):
    c, url, handler = browser
    navigate(c, url + "/app.html")
    wait(c, "document.querySelector('.item') && document.querySelector('.load-state').hidden")
    handler.delay = 1
    click(c, '.item')
    wait(c, "!document.querySelector('.load-state').hidden && document.querySelector('[data-poster]').naturalWidth > 0")
    assert c.js("document.querySelector('[data-poster]').naturalWidth") == 1280
    assert c.js("player.video.poster.endsWith('/poster.jpg')")
    assert c.js("getComputedStyle(document.querySelector('.item .thumb')).backgroundImage.includes('/thumb.jpg')")
    (ROOT / 'scratch' / 'player-loading.png').write_bytes(base64.b64decode(c.call('Page.captureScreenshot', format='png')['data']))
    handler.delay = 0
    wait(c, "document.querySelector('video').readyState >= 3 && document.querySelector('.load-state').hidden")
    click(c, '[data-play]')
    wait(c, "document.querySelector('video').currentTime > 0.3")
    click(c, '[data-play]')
    c.js("player.video.currentTime = 13.2")
    wait(c, "!player.video.seeking && Number(localStorage.getItem('pp-position:pianpian-day')) > 13")
    # A real subtitle click must still pause and pin the definition.
    wait(c, "document.querySelector('.ov .w')")
    click(c, '.ov .w')
    assert c.js("player.video.paused && !!document.querySelector('.ov > .gl span')")
    assert c.js("localStorage.getItem('pp-last-video')") == 'pianpian-day'
    navigate(c, url + "/app.html")
    wait(c, "document.querySelector('video').currentTime > 13 && document.querySelector('.load-state').hidden")
    assert c.js("player.video.paused")
    # Explicit links override the remembered position.
    navigate(c, url + "/app.html?link#v=pianpian-day&t=4")
    wait(c, "Math.abs(player.video.currentTime - 4) < .1 && !player.video.seeking")
    # Simulate the media event; real playback and controls are checked above.
    c.js("player.video.dispatchEvent(new Event('waiting'))")
    wait(c, "document.querySelector('[data-load-text]').textContent === 'Buffering…'")
    c.js("player.video.dispatchEvent(new Event('canplay'))")
    wait(c, "document.querySelector('.load-state').hidden")
    handler.fail = True
    click(c, '.item')
    wait(c, "!document.querySelector('[data-retry]').hidden")
    handler.fail = False
    click(c, '[data-retry]')
    wait(c, "document.querySelector('video').readyState >= 3 && document.querySelector('.load-state').hidden")
    # Deleted saved video falls back to the library, without an endless spinner.
    c.js("player.begin(); localStorage.setItem('pp-last-video', 'missing')")
    navigate(c, url + "/app.html")
    wait(c, "document.querySelector('.drop').textContent.includes('Choose a video') && document.querySelector('.load-state').hidden")
    # The website always starts its demo on its first line (subtitles visible), independent of app memory.
    navigate(c, url + "/app.html?demo#v=pianpian-day")
    wait(c, "player.tracks.length && !player.video.seeking && document.querySelector('.load-state').hidden && document.querySelector('.ov .zh .w')")
    assert c.js("player.video.currentTime") == pytest.approx(1.51, abs=.01)


def test_switching_during_loading_and_website(browser):
    c, url, handler = browser
    navigate(c, url + "/app.html")
    wait(c, "document.querySelectorAll('.item').length === 2")
    handler.delay = 1
    click(c, '.item[data-id="pianpian-day"]')
    wait(c, "!document.querySelector('.load-state').hidden")
    click(c, '.item[data-id="second"]')
    wait(c, "current?.id === 'second' && document.querySelector('.load-state').hidden")
    c.js("new Promise(r => setTimeout(r, 1200))")
    assert c.js("current.id") == 'second'
    # Blocked storage must not prevent selection or playback.
    c.js("Storage.prototype.setItem = () => { throw new Error('disabled'); }")
    click(c, '.item[data-id="second"]')
    wait(c, "player.video.readyState >= 3 && document.querySelector('.load-state').hidden")
    click(c, '[data-play]')
    wait(c, "player.video.currentTime > .3")
    navigate(c, url + '/index.html')
    click(c, 'a[href="#demo"]')
    wait(c, "document.querySelector('iframe').contentDocument?.querySelector('[data-poster]')?.naturalWidth > 0")
    assert c.js("document.querySelector('iframe').contentDocument.querySelector('[data-poster]').naturalWidth") == 1280
    assert c.js("document.querySelector('iframe').contentDocument.querySelector('video').poster.endsWith('/poster.jpg')")
    assert c.js("document.querySelector('iframe').contentDocument.querySelector('.drop').checkVisibility({visibilityProperty:true})") is False
    wait(c, "document.querySelector('iframe').contentDocument.querySelector('.load-state').hidden")
    assert c.js("document.querySelector('iframe').contentDocument.querySelector('video').paused")


@pytest.mark.parametrize('demo', [False, True])
def test_video_loads_before_subtitles(browser, demo):
    c, url, handler = browser
    c.call('Network.enable')
    c.call('Network.setCacheDisabled', cacheDisabled=True)
    handler.track_gate.clear()
    navigate(c, url + '/app.html' + ('?demo' if demo else '') + '#v=pianpian-day')
    wait(c, "player.video.readyState >= 3 && document.querySelector('.load-state').hidden")
    assert c.js('player.tracks.length') == 0
    click(c, '[data-play]')
    wait(c, 'player.video.currentTime > .3')
    handler.track_gate.set()
    wait(c, 'player.tracks.length > 0 && document.querySelector(".cue")')
    assert c.js('!player.video.paused && player.video.currentTime > .3')
    # A late response must not attach the previous video's subtitles to a new selection.
    if demo:
        return
    handler.track_gate.clear()
    click(c, '.item[data-id="pianpian-day"]')
    wait(c, 'player.video.currentSrc && player.tracks.length === 0')
    click(c, '.item[data-id="second"]')
    wait(c, "current.id === 'second' && player.tracks.length > 0")
    count = c.js('player.tracks.length')
    handler.track_gate.set()
    c.js('new Promise(r => setTimeout(r, 300))')
    assert c.js("current.id === 'second' && player.tracks.length") == count


def test_subtitle_failure_keeps_video_playable(browser):
    c, url, handler = browser
    handler.fail_tracks = True
    navigate(c, url + '/app.html#v=pianpian-day')
    wait(c, "player.video.readyState >= 3 && document.querySelector('[data-retry-subs]')")
    click(c, '[data-play]')
    wait(c, 'player.video.currentTime > .3')
    handler.fail_tracks = False
    click(c, '[data-retry-subs]')
    wait(c, "player.tracks.length > 0 && !document.querySelector('[data-retry-subs]')")


def test_progressive_playback(browser):
    c, url, handler = browser
    navigate(c, url + '/app.html')
    wait(c, "document.querySelector('.item') && document.querySelector('.load-state').hidden")
    c.call('Network.enable')
    c.call('Network.setCacheDisabled', cacheDisabled=True)
    c.call('Network.emulateNetworkConditions', offline=False, latency=150,
           downloadThroughput=32768, uploadThroughput=32768)
    click(c, '.item')
    wait(c, "!document.querySelector('.load-state').hidden && document.querySelector('[data-poster]').naturalWidth > 0")
    wait(c, "player.video.readyState >= 3 && document.querySelector('.load-state').hidden")
    click(c, '[data-play]')
    wait(c, 'player.video.currentTime > .3')
    assert c.js('player.video.buffered.end(player.video.buffered.length - 1) < player.video.duration')
    assert any(r and r.startswith('bytes=') for r in handler.video_ranges)


@pytest.mark.parametrize('width', [390, 1440])
def test_demo_loading_keeps_video_size(browser, width):
    c, url, handler = browser
    c.call('Emulation.setDeviceMetricsOverride', width=width, height=844, deviceScaleFactor=1, mobile=False)
    c.call('Page.addScriptToEvaluateOnNewDocument', source="""
      if (location.pathname === '/app.html') addEventListener('DOMContentLoaded', () => {
        const img = new Image(); img.hidden = true; img.src = '/frame-gate.gif'; document.body.append(img);
      });
    """)
    handler.video_gate.clear()
    handler.frame_gate.clear()                 # keep iframe.load pending after the player has rendered
    c.call('Page.navigate', url=url + '/index.html')
    # clicked while the page was still loading, the hit test sometimes landed on Download: wait until it lands here
    wait(c, """document.readyState !== 'loading' && (() => { const g = document.querySelector('.ghost[href="#demo"]'), r = g.getBoundingClientRect();
      return g.contains(document.elementFromPoint(r.x + r.width/2, r.y + r.height/2)); })()""")
    click(c, '.ghost[href="#demo"]')
    wait(c, "document.querySelector('iframe').contentDocument?.querySelector('[data-poster]')?.naturalWidth > 0")
    wait(c, "!document.querySelector('iframe').contentDocument.querySelector('.load-state').hidden")
    assert c.js("getComputedStyle(document.querySelector('iframe')).opacity") == '1'
    c.js("scrollTo({top:document.querySelector('#demo').offsetTop - 70, behavior:'instant'})")
    bounds = """(() => { const r = document.querySelector('iframe').contentDocument.querySelector('.stage').getBoundingClientRect();
      return [r.x, r.y, r.width, r.height]; })()"""
    loading = c.js(bounds)
    (ROOT / 'scratch' / f'demo-loading-{width}.png').write_bytes(base64.b64decode(c.call('Page.captureScreenshot', format='png')['data']))
    handler.frame_gate.set()
    handler.video_gate.set()
    wait(c, "document.querySelector('iframe').contentDocument.querySelector('.load-state').hidden")
    assert c.js(bounds) == pytest.approx(loading, abs=1)
    c.js('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
    (ROOT / 'scratch' / f'demo-ready-{width}.png').write_bytes(base64.b64decode(c.call('Page.captureScreenshot', format='png')['data']))
    c.js("document.querySelector('iframe').scrollIntoView({block:'center', behavior:'instant'})")
    point = c.js("""(() => { const f = document.querySelector('iframe'), r = f.getBoundingClientRect();
      const b = f.contentDocument.querySelector('[data-play]').getBoundingClientRect(); return [r.x+b.x+b.width/2, r.y+b.y+b.height/2]; })()""")
    c.call('Input.dispatchMouseEvent', type='mouseMoved', x=point[0], y=point[1])
    for event in ('mousePressed', 'mouseReleased'):
        c.call('Input.dispatchMouseEvent', type=event, x=point[0], y=point[1], button='left', clickCount=1)
    wait(c, "document.querySelector('iframe').contentDocument.querySelector('video').currentTime > .3")


def test_mobile_demo_layout(browser):
    c, url, _ = browser
    c.call('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=True)
    navigate(c, url + '/index.html')
    click(c, '.ghost[href="#demo"]')
    wait(c, "document.querySelector('iframe').contentDocument?.querySelector('.load-state')?.hidden")
    wait(c, "Math.abs(parseFloat(document.querySelector('iframe').style.height) - document.querySelector('iframe').contentDocument.querySelector('.shell').getBoundingClientRect().height) < 2")
    wait(c, "getComputedStyle(document.querySelector('iframe').contentDocument.querySelector('.vc')).opacity === '1'")
    # A decorative title bar must never act as a second sticky navigation bar.
    assert c.js("getComputedStyle(document.querySelector('.window-bar')).position") == 'static'
    c.js("scrollTo(0, document.querySelector('#demo').offsetTop + 80)")
    c.js("new Promise(r => setTimeout(r, 400))")
    assert c.js("document.elementFromPoint(195, 20).closest('header.top') !== null")
    for width in (320, 390, 768):
        c.call('Emulation.setDeviceMetricsOverride', width=width, height=844, deviceScaleFactor=1, mobile=True)
        wait(c, "document.documentElement.scrollWidth <= innerWidth")
        assert c.js("(() => { const w = document.querySelector('iframe').contentWindow; return w.document.documentElement.scrollWidth <= w.innerWidth; })()")
    c.call('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=True)
    c.call('Emulation.setTouchEmulationEnabled', enabled=True, maxTouchPoints=1)
    c.js("scrollTo(0, document.querySelector('#demo').offsetTop - 70)")
    c.js("new Promise(r => setTimeout(r, 400))")
    f = "document.querySelector('iframe').contentDocument"
    # On a phone the demo is the video, three line switches and the transcript: no window bar, panel toggles or menus.
    assert c.js("getComputedStyle(document.querySelector('.window-bar')).display") == 'none'
    assert c.js(f"[...{f}.querySelectorAll('.ptoggle, .panel.left, .pbar > :not(.quick)')].every(e => !e.getClientRects().length)")
    assert c.js(f"[...{f}.querySelectorAll('[data-quick-role]')].map(b => b.dataset.quickRole + ':' + b.getAttribute('aria-pressed'))") == \
        ['zh:true', 'pinyin:true', 'en:true']
    assert c.js(f"{f}.querySelector('.panel.right').getBoundingClientRect().top >= {f}.querySelector('.pbar').getBoundingClientRect().bottom")
    # It opens on its first line, so the subtitles are there before play.
    wait(c, f"{f}.querySelector('video').currentTime > 1.5 && {f}.querySelectorAll('.ov .ln').length === 3")
    # A tap on a subtitle word while it plays pauses and opens the word as a sheet (not the card on the video).
    tap_in_frame(c, "d.querySelector('[data-play]')")
    wait(c, f"{f}.querySelector('video').currentTime > 7 && {f}.querySelector('.ov .zh .w')")
    word = c.js(f"{f}.querySelector('.ov .zh .w').textContent")
    tap_in_frame(c, "d.querySelector('.ov .zh .w')")
    wait(c, f"{f}.querySelector('video').paused && !{f}.querySelector('.wsheet').hidden")
    assert c.js(f"{f}.querySelector('[data-sheet-body]').textContent").startswith(word)
    assert c.js(f"""(() => {{ const fr = document.querySelector('iframe'), s = {f}.querySelector('.wsheet').getBoundingClientRect();
      return s.left >= 0 && s.right <= fr.clientWidth && s.bottom <= fr.clientHeight && !{f}.querySelector('.ov > .gl').getClientRects().length; }})()""")
    (ROOT / 'scratch' / 'mobile-demo.png').write_bytes(base64.b64decode(c.call('Page.captureScreenshot', format='png')['data']))
    # A switch is the track's own on/off; tapping it is also a tap outside the sheet.
    tap_in_frame(c, "d.querySelector('[data-quick-role=pinyin]')")
    wait(c, f"{f}.querySelector('.wsheet').hidden && !{f}.querySelector('.ov .pinyin') && !{f}.querySelector('.cue .l.pinyin')")
    assert c.js(f"[...{f}.querySelectorAll('[data-on]')].map(e => e.checked)") == [True, False, True]
    # The × closes it too; a tap on the page around the demo as well.
    tap_in_frame(c, "d.querySelector('.cue .l.zh .w')")
    wait(c, f"!{f}.querySelector('.wsheet').hidden")
    tap_in_frame(c, "d.querySelector('[data-sheet-close]')")
    wait(c, f"{f}.querySelector('.wsheet').hidden")
    tap_in_frame(c, "d.querySelector('.cue .l.zh .w')")
    wait(c, f"!{f}.querySelector('.wsheet').hidden")
    click(c, 'h2')
    wait(c, f"{f}.querySelector('.wsheet').hidden")


def test_words_keep_a_gap(browser):
    """Neighbouring words, Chinese and pinyin, on the video and in the transcript, never touch: 0.3em apart."""
    c, url, _ = browser
    c.call('Emulation.setDeviceMetricsOverride', width=1280, height=800, deviceScaleFactor=1, mobile=False)
    navigate(c, url + '/app.html#v=pianpian-day&t=7.5')
    wait(c, "!player.video.seeking && document.querySelector('.ov .pinyin .w') && document.querySelector('.cue .l.pinyin .w')")
    gaps = c.js("""(() => {
      const glyphs = el => { const r = document.createRange(); r.selectNodeContents(el); return r.getBoundingClientRect(); };
      const out = [];
      for (const line of document.querySelectorAll('.ov .zh, .ov .pinyin, .cue .l.zh, .cue .l.pinyin')) {
        const words = [...line.querySelectorAll('.w')], em = parseFloat(getComputedStyle(words[0] || line).fontSize);
        for (let i = 1; i < words.length; i++) {
          if (words[i - 1].nextSibling !== words[i] && !words[i - 1].nextSibling?.matches?.('.sp')) continue;   // punctuation between
          const a = glyphs(words[i - 1]), b = glyphs(words[i]);
          if (Math.abs(a.top - b.top) < 2) out.push([line.className, words[i - 1].textContent, words[i].textContent, (b.left - a.right) / em]);
        }
      }
      return out;
    })()""")
    kinds = {k for k, *_ in gaps}
    assert {'zh', 'pinyin', 'l zh', 'l pinyin'} <= kinds, kinds
    assert all(g == pytest.approx(.3, abs=.02) for *_, g in gaps), [x for x in gaps if abs(x[3] - .3) > .02]
    # punctuation sits right after its word: no word gap before a comma or a full stop
    tight = c.js("""(() => [...document.querySelectorAll('.ov .pinyin .w.end, .cue .l.pinyin .w.end, .ov .zh .w.end, .cue .l.zh .w.end')].map(w => {
      const r = document.createRange(); r.selectNodeContents(w); const a = r.getBoundingClientRect();
      const t = w.nextSibling; if (!t || t.nodeType !== 3) return null;
      r.setStart(t, 0); r.setEnd(t, 1); const b = r.getBoundingClientRect();
      return Math.abs(a.top - b.top) < 2 ? (b.left - a.right) / parseFloat(getComputedStyle(w).fontSize) : null;
    }).filter(x => x !== null))()""")
    assert tight and all(g < .12 for g in tight), tight
    # the space between pinyin words is not drawn, but a copy still has it
    assert c.js("(() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('.cue .l.pinyin')); return r.toString(); })()").startswith('nǐhǎo wǒ jiào')
