"""Real Chrome clicks against the player and Anki menu; Anki endpoints are simulated."""
import base64
import functools
import io
import json
import tempfile
import threading
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from test_player_browser import ROOT, click, navigate, wait
from tools import build_site, shots


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<link rel="stylesheet" href="/assets/kit.css"><link rel="stylesheet" href="/assets/anki.css">
<style>body{padding:16px}#player{max-width:900px}.stage{max-height:430px}</style>
<div id="player"></div><script src="/assets/kit.js"></script>
<script src="/assets/player.js"></script><script src="/assets/anki.js"></script>
<script>
let current = {id:'pianpian-day'}, ankiUI;
const player = SubPlayer.mount(document.querySelector('#player'), {
  onAnkiSelection:s => ankiUI?.selectionChanged(s), onAnkiOpen:anchor => ankiUI?.open(anchor)
});
player.extra.innerHTML = '<details class="dd" data-video><summary>Video</summary><div class="ddp">Existing menu</div></details>';
const api = async (path, body) => {
  const r = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Kit':'1'},body:JSON.stringify(body)});
  const result = await r.json(); if(!r.ok) throw new Error(result.error); return result;
};
ankiUI = AnkiExport.mount(player, {api,source:()=>current,enabled:!location.search.includes('demo')});
(async()=>{
  const base='/demo/library/pianpian-day/';
  const subs=await Promise.all(['zh.srt','zh.pinyin.srt','zh.en.srt'].map(async name=>({name,text:await (await fetch(base+name)).text()})));
  const words=await (await fetch(base+'zh.words.json')).json();
  player.load({id:current.id,video:base+'source.mp4',subs,words,start:13.2});
})();
</script>"""


@pytest.fixture
def anki_browser():
    exe = next((b for b in shots.BROWSERS if Path(b).exists()), None)
    if not exe:
        pytest.skip('Chrome, Brave or Chromium required')
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\0' * 16000)

    class Handler(build_site.RangedHandler):
        calls = []
        state = 'connected'
        profile = 'Study'
        deck = 'Mandarin'
        export_state = 'added'
        fail_export = False
        fail_status = False
        preview_start_offset = 0
        preview_end_offset = 0
        preview_gate = threading.Event()
        preview_gate.set()
        export_gate = threading.Event()
        export_gate.set()

        def reply(self, data, status=200, content_type='application/json'):
            body = json.dumps(data).encode() if content_type == 'application/json' else data
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def status(self):
            return {'state': self.state, 'message': 'Connected to Anki.' if self.state == 'connected' else 'Anki connection failed: ' + self.state,
                    'decks': ['Default', 'Mandarin'], 'profile': self.profile, 'port': 8765, 'hasKey': False, 'deck': self.deck}

        def do_GET(self):
            if self.path.startswith('/test.html'):
                self.reply(PAGE.encode(), content_type='text/html')
            elif self.path == '/api/anki/status':
                self.calls.append((self.path, None))
                self.reply({'error': 'Connection refused'} if self.fail_status else self.status(), 503 if self.fail_status else 200)
            elif self.path.startswith('/preview.wav'):
                self.reply(audio.getvalue(), content_type='audio/wav')
            else:
                super().do_GET()

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.calls.append((self.path, data))
            assert self.headers['X-Kit'] == '1'
            if self.path == '/api/anki/preview':
                self.preview_gate.wait(10)
                start = data['start'] + self.preview_start_offset
                end = data['end'] + self.preview_end_offset
                self.reply({'url': '/preview.wav', 'start': start, 'end': end, 'duration': end - start})
            elif self.path == '/api/anki/export':
                self.export_gate.wait(10)
                if self.fail_export:
                    self.reply({'error': 'Anki disconnected. Your draft is kept.'}, 503)
                else:
                    self.reply({'state': 'updated' if data['update'] else self.export_state, 'noteId': 123, 'deck': data['deck']})
            elif self.path == '/api/anki/settings':
                self.reply(self.status())
            elif self.path == '/api/anki/open':
                self.reply({'ok': True})
            else:
                self.reply({'error': 'Unknown endpoint'}, 404)

        def log_message(self, *_):
            pass

    (ROOT / 'scratch').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / 'scratch', prefix='anki-browser-') as directory:
        srv = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=ROOT))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        c = shots.Chrome(exe, str(Path(directory) / 'profile'))
        try:
            target = next(t for t in c.call('Target.getTargets')['targetInfos'] if t['type'] == 'page')
            c.session = c.call('Target.attachToTarget', targetId=target['targetId'], flatten=True)['sessionId']
            c.call('Page.enable')
            yield c, f'http://127.0.0.1:{srv.server_port}', Handler
        finally:
            Handler.preview_gate.set()
            Handler.export_gate.set()
            c.close()
            srv.shutdown()
            srv.server_close()


def expand(c, name):
    if not c.js(f'document.querySelector("[data-anki-{name}]").open'):
        selector = f'[data-anki-{name}] > summary'
        c.js(f'document.querySelector({json.dumps(selector)}).scrollIntoView({{block:"center"}})')
        click(c, selector)


def press(c, name):
    if name in ('expression', 'pinyin', 'meaning', 'sentence-text', 'translation', 'highlight', 'tone-pinyin', 'tone-expression'):
        expand(c, 'edit')
    elif name in ('context', 'start', 'end', 'start-minus', 'start-plus', 'end-minus', 'end-plus'):
        expand(c, 'adjust')
    elif name in ('sentence', 'before', 'after', 'port', 'key', 'clear-key', 'connect'):
        expand(c, 'more')
    selector = '.anki > summary' if name == 'menu' else f'[data-anki-{name}]'
    c.js(f'document.querySelector({json.dumps(selector)}).scrollIntoView({{block:"center"}})')
    click(c, selector)
    if name == 'menu':
        c.js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        wait(c, 'document.querySelector(".anki-panel").getAnimations().every(a=>a.playState!=="running")')


def fill(c, name, text):
    press(c, name)
    c.js(f'document.querySelector("[data-anki-{name}]").select()')
    c.call('Input.insertText', text=text)


def ready(c, url):
    navigate(c, url + '/test.html')
    wait(c, 'player.video.readyState >= 3 && !player.video.seeking && document.querySelector(".ov [data-anki-word]")')


def word(c, index=0, shift=False):
    selector = f'.ov [data-anki-word="{index}"]'
    c.js(f'document.querySelector({json.dumps(selector)}).scrollIntoView({{block:"center"}})')
    point = c.js(f'(() => {{ const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]; }})()')
    for event in ('mousePressed', 'mouseReleased'):
        c.call('Input.dispatchMouseEvent', type=event, x=point[0], y=point[1], button='left', clickCount=1, modifiers=8 if shift else 0)


def preview(c):
    press(c, 'preview')
    wait(c, '!document.querySelector("[data-anki-audio]").hidden && !document.querySelector("[data-anki-save]").disabled')


def escape(c):
    for event in ('keyDown', 'keyUp'):
        c.call('Input.dispatchKeyEvent', type=event, key='Escape', code='Escape', windowsVirtualKeyCode=27)


def bounded(c):
    wait(c, '''(() => {
      const p=document.querySelector('.anki-panel').getBoundingClientRect();
      const h=document.querySelector('.anki-header').getBoundingClientRect();
      const f=document.querySelector('.anki-footer').getBoundingClientRect();
      const b=document.querySelector('[data-anki-save]'), r=b.getBoundingClientRect();
      return p.left>=7 && p.right<=innerWidth-7 && p.top>=7 && p.bottom<=innerHeight-7 &&
        h.top>=p.top && f.bottom<=p.bottom && document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===b;
    })()''')


def test_compact_editor_dismiss_listen_and_replay(anki_browser):
    c, url, handler = anki_browser
    ready(c, url)
    assert c.js('document.querySelector(".anki").nextElementSibling === player.extra.parentElement.lastElementChild && player.extra.parentElement.lastElementChild.matches("[data-full]")')
    assert c.js('''(() => {
      const buttons = [...player.extra.parentElement.querySelectorAll('.dd.icon > summary, [data-full]')];
      return buttons.length === 3 && buttons.every(e=>{const r=e.getBoundingClientRect();
        return r.width === 32 && r.height === 32 && (!e.matches('summary') || e.parentElement.getBoundingClientRect().height === 32);});
    })()''')
    word(c)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    assert c.js('''(() => {const s=document.querySelector('.anki > summary');return s.textContent==='' &&
      s.getAttribute('aria-label')==='Prepare Anki card' && s.title==='Prepare Anki card' && s.closest('.dd.icon')!==null;})()''')
    assert c.js('Array.from(document.querySelectorAll(".anki-fold")).every(d=>!d.open)')
    assert c.js('document.querySelector("[data-anki-expression-preview]").textContent === player.ankiSelection().expression')
    bounded(c)
    (ROOT / 'scratch' / 'anki-compact-initial.png').write_bytes(base64.b64decode(c.call('Page.captureScreenshot', format='png')['data']))
    fill(c, 'meaning', 'Draft kept on close')
    preview(c)
    wait(c, 'document.querySelector("[data-anki-audio]").currentTime > 0 && !document.querySelector("[data-anki-audio]").error')
    press(c, 'close')
    wait(c, '!document.querySelector(".anki").open && document.querySelector("[data-anki-audio]").paused')
    assert c.js('player.video.paused')
    press(c, 'menu')
    wait(c, 'document.querySelector(".anki").getAttribute("aria-busy") === "false"')
    assert c.js('document.querySelector("[data-anki-meaning]").value') == 'Draft kept on close'
    preview(c)
    wait(c, '!document.querySelector("[data-anki-audio]").paused')
    assert len([p for p, _ in handler.calls if p.endswith('/preview')]) == 1
    escape(c)
    wait(c, '!document.querySelector(".anki").open && document.querySelector("[data-anki-audio]").paused')
    assert c.js('player.video.paused && document.querySelector("[data-anki-audio]").hasAttribute("src")')
    press(c, 'menu')
    # Resources stays outside the popover when the toolbar wraps to a new row.
    click(c, 'details:has(a.res) > summary')
    wait(c, '!document.querySelector(".anki").open')
    assert c.js('document.querySelector("[data-anki-meaning]").value') == 'Draft kept on close'


def test_audio_steps_and_late_preview_never_autoplay_after_close(anki_browser):
    c, url, handler = anki_browser
    ready(c, url)
    word(c)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    preview(c)
    start = c.js('document.querySelector("[data-anki-start]").valueAsNumber')
    press(c, 'start-minus')
    assert c.js('document.querySelector("[data-anki-start]").valueAsNumber') == pytest.approx(start - .1)
    assert c.js('document.querySelector("[data-anki-audio]").hidden && document.querySelector("[data-anki-save]").disabled')
    press(c, 'start-plus')
    assert c.js('document.querySelector("[data-anki-start]").valueAsNumber') == start
    end = c.js('document.querySelector("[data-anki-end]").valueAsNumber')
    press(c, 'end-plus')
    assert c.js('document.querySelector("[data-anki-end]").valueAsNumber') == pytest.approx(end + .1)
    press(c, 'end-minus')
    assert c.js('document.querySelector("[data-anki-end]").valueAsNumber') == end
    handler.preview_gate.clear()
    press(c, 'preview')
    wait(c, 'document.querySelector(".anki").getAttribute("aria-busy") === "true"')
    assert c.js('Array.from(document.querySelectorAll("[data-anki-start-plus],[data-anki-expression],[data-anki-deck],[data-anki-port],[data-anki-save]")).every(e=>e.matches(":disabled"))')
    press(c, 'close')
    handler.preview_gate.set()
    wait(c, '!document.querySelector("[data-anki-audio]").hidden && document.querySelector(".anki").getAttribute("aria-busy") === "false"')
    assert c.js('document.querySelector("[data-anki-audio]").paused && document.querySelector("[data-anki-audio]").currentTime===0')
    press(c, 'menu')
    wait(c, 'document.querySelector(".anki").getAttribute("aria-busy") === "false"')
    assert c.js('document.querySelector("[data-anki-audio]").paused')
    preview(c)
    wait(c, 'document.querySelector("[data-anki-audio]").currentTime>0')


def test_autoplay_rejection_keeps_native_controls_and_exact_preview(anki_browser):
    c, url, handler = anki_browser
    ready(c, url)
    word(c)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    c.js('document.querySelector("[data-anki-audio]").play = () => Promise.reject(new DOMException("Gesture required", "NotAllowedError"))')
    preview(c)
    assert 'Press play' in c.js('document.querySelector("[data-anki-preview-help]").textContent')
    assert c.js('document.querySelector("[data-anki-audio]").controls && !document.querySelector("[data-anki-save]").disabled')
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").textContent === "Added"')
    assert [body for path, body in handler.calls if path.endswith('/export')][-1]['preview'] == '/preview.wav'


def test_palette_literal_preview_and_plain_text_payload(anki_browser):
    c, url, handler = anki_browser
    ready(c, url)
    word(c)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    assert c.js('document.querySelector("[data-anki-highlight]").value') == 'jade'
    expression = '<b>&.*</b>'
    sentence = f'{expression} + {expression} &lt;b&gt;'
    fill(c, 'expression', expression)
    fill(c, 'sentence-text', sentence)
    fill(c, 'meaning', '<img src=x onerror=alert(1)>')
    assert c.js('document.querySelector("[data-anki-sentence-preview]").textContent') == sentence
    assert c.js('document.querySelectorAll("[data-anki-sentence-preview] mark").length') == 2
    assert c.js('document.querySelectorAll(".anki-header b,.anki-header img,.anki-header script").length') == 0
    preview(c)
    palette = [('none', 'rgba(0, 0, 0, 0)'), ('jade', 'rgba(14, 138, 99, 0.18)'),
               ('coral', 'rgba(222, 59, 38, 0.18)'), ('blue', 'rgba(42, 113, 190, 0.18)'), ('gold', 'rgba(176, 127, 16, 0.18)')]
    for name, background in palette:
        c.js(f'document.querySelector("[data-anki-highlight]").value="{name}";document.querySelector("[data-anki-highlight]").dispatchEvent(new Event("change"))')
        wait(c, f'document.querySelector("[data-anki-highlight]").value === "{name}"')
        for theme in ('light', 'dark'):
            c.js(f'document.documentElement.dataset.theme="{theme}"')
            assert c.js('getComputedStyle(document.querySelector(".anki-header mark")).backgroundColor') == background
            assert c.js('getComputedStyle(document.querySelector(".anki-header mark")).color === getComputedStyle(document.querySelector("[data-anki-expression-preview]")).color')
        press(c, 'save')
        wait(c, 'document.querySelector("[data-anki-save]").disabled && document.querySelector(".anki").getAttribute("aria-busy") === "false"')
        exported = [body for path, body in handler.calls if path.endswith('/export')][-1]
        assert exported['highlight'] == name and exported['expression'] == expression and exported['sentence'] == sentence


def test_tone_switches_payload_and_literal_preview(anki_browser):
    c, url, handler = anki_browser
    ready(c, url)
    word(c)
    word(c, 2, shift=True)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    assert c.js('!document.querySelector("[data-anki-edit]").open')
    assert c.js('document.querySelector("[data-anki-tone-pinyin]").checked && !document.querySelector("[data-anki-tone-expression]").checked')
    original = c.js('player.ankiSelection()')
    assert original['pinyin'] == 'zuótiān wǒ chī'
    expected = [['zuó', 2], ['tiān', 1], [' ', 0], ['wǒ', 3], [' ', 0], ['chī', 1]]
    assert c.js('Array.from(document.querySelector("[data-anki-pinyin-preview]").childNodes, n=>[n.textContent, Number(n.className?.slice(1)||0)])') == expected
    assert c.js('!document.querySelector("[data-anki-expression-preview] span")')
    preview(c)
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").textContent === "Added"')
    assert [body for path, body in handler.calls if path.endswith('/export')][-1]['tones'] == {'pinyin': expected}

    press(c, 'tone-expression')
    fill(c, 'sentence-text', original['expression'] + ' + ' + original['expression'])
    assert c.js('document.querySelectorAll("[data-anki-sentence-preview] mark span").length') == 8
    for theme in ('light', 'dark'):
        c.js(f'document.documentElement.dataset.theme="{theme}"')
        assert c.js('''(() => {const p=document.querySelector('[data-anki-pinyin-preview] .t2'),
          e=document.querySelector('[data-anki-expression-preview] .t2');
          return getComputedStyle(p).color === getComputedStyle(e).color && getComputedStyle(e).color !== getComputedStyle(e.parentElement).color;})()''')
    c.js('document.querySelector("[data-anki-highlight]").value="none";document.querySelector("[data-anki-highlight]").dispatchEvent(new Event("change"))')
    assert c.js('getComputedStyle(document.querySelector(".anki-header mark")).backgroundColor') == 'rgba(0, 0, 0, 0)'
    assert c.js('document.querySelector("[data-anki-expression-preview] .t2").textContent') == '昨'
    press(c, 'tone-pinyin')
    assert c.js('!document.querySelector("[data-anki-pinyin-preview] span")')
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").textContent === "Updated"')
    exported = [body for path, body in handler.calls if path.endswith('/export')][-1]
    assert exported['tones'] == {'expression': [['昨', 2], ['天', 1], ['我', 3], ['吃', 1]]}
    assert exported['highlight'] == 'none' and exported['update']
    press(c, 'tone-expression')
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").disabled && document.querySelector(".anki").getAttribute("aria-busy") === "false"')
    assert [body for path, body in handler.calls if path.endswith('/export')][-1]['tones'] == {}

    press(c, 'tone-pinyin')
    press(c, 'tone-expression')
    edited = "  xī'ān,  nǐ-hǎo!  "
    fill(c, 'pinyin', edited)
    assert c.js('document.querySelector("[data-anki-pinyin-preview]").textContent') == edited.strip()
    assert c.js('!document.querySelector("[data-anki-expression-preview] span")')
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").disabled && document.querySelector(".anki").getAttribute("aria-busy") === "false"')
    exported = [body for path, body in handler.calls if path.endswith('/export')][-1]
    assert ''.join(text for text, _ in exported['tones']['pinyin']) == edited.strip()
    assert exported['tones']['expression'] == [[original['expression'], 0]]
    expression = '<img src=x onerror=alert(1)>&'
    fill(c, 'expression', expression)
    fill(c, 'pinyin', 'ma ma <b>&</b>')
    fill(c, 'sentence-text', expression + ' ' + expression)
    assert c.js('!document.querySelector(".anki-header img,.anki-header b,.anki-header script,.anki-header span")')
    assert c.js('document.querySelector("[data-anki-sentence-preview]").textContent') == expression + ' ' + expression
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").disabled && document.querySelector(".anki").getAttribute("aria-busy") === "false"')
    exported = [body for path, body in handler.calls if path.endswith('/export')][-1]
    assert exported['tones'] == {'pinyin': [['ma ma <b>&</b>', 0]], 'expression': [[expression, 0]]}


def test_position_resize_scroll_and_detached_anchor(anki_browser):
    c, url, _ = anki_browser
    ready(c, url)
    word(c)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    bounded(c)
    press(c, 'close')
    c.js('document.querySelector(".anki").style.cssText="position:fixed;top:12px;right:12px;z-index:50"')
    press(c, 'menu')
    wait(c, '!document.querySelector(".anki-panel").classList.contains("up")')
    bounded(c)
    press(c, 'close')
    c.js('document.querySelector(".anki").style.cssText="position:fixed;bottom:12px;right:12px;z-index:50"')
    press(c, 'menu')
    wait(c, 'document.querySelector(".anki-panel").classList.contains("up")')
    bounded(c)
    c.call('Emulation.setDeviceMetricsOverride', width=390, height=620, deviceScaleFactor=1, mobile=False)
    bounded(c)
    fill(c, 'translation', 'Scroll within the editor')
    bounded(c)
    # A word anchor may disappear when the player redraws; the same editor falls back to its toolbar.
    c.js('ankiUI.open(document.createElement("button"))')
    bounded(c)
    press(c, 'close')
    c.js('document.querySelector(".anki").style.cssText="";document.body.style.paddingBottom="1200px"')
    press(c, 'menu')
    c.js('window.scrollBy(0,120)')
    bounded(c)


def test_pinned_action_reopens_the_same_draft(anki_browser):
    c, url, _ = anki_browser
    ready(c, url)
    word(c)
    wait(c, 'document.querySelector(".anki-word-action")')
    click(c, '.anki-word-action')
    wait(c, 'document.querySelector(".anki").open && document.querySelector("[data-anki-status]").dataset.state === "connected"')
    bounded(c)
    fill(c, 'meaning', 'One editor from either action')
    press(c, 'close')
    click(c, '.anki-word-action')
    wait(c, 'document.querySelector(".anki").open')
    assert c.js('document.querySelector("[data-anki-meaning]").value') == 'One editor from either action'
    press(c, 'close')
    press(c, 'menu')
    assert c.js('document.querySelector("[data-anki-meaning]").value') == 'One editor from either action'


def test_fullscreen_word_action_keeps_editor_visible(anki_browser):
    c, url, _ = anki_browser
    ready(c, url)
    word(c)
    press(c, 'menu')
    fill(c, 'meaning', 'One editor in and out of fullscreen')
    press(c, 'close')
    c.js('document.addEventListener("fullscreenerror",()=>window.fullscreenDenied=true,{once:true})')
    click(c, '[data-full]')
    wait(c, 'window.fullscreenDenied || document.fullscreenElement === player.stage')
    if c.js('window.fullscreenDenied'):
        pytest.skip('Headless Chrome denied the real-click fullscreen request on this host')
    wait(c, 'document.fullscreenElement === player.stage && document.querySelector(".anki").parentElement === player.stage')
    click(c, '.anki-word-action')
    wait(c, 'document.querySelector(".anki").open')
    bounded(c)
    assert c.js('document.querySelector("[data-anki-meaning]").value') == 'One editor in and out of fullscreen'
    preview(c)
    press(c, 'close')
    click(c, '[data-vfull]')
    wait(c, '!document.fullscreenElement && document.querySelector(".anki").nextElementSibling === player.extra.parentElement.lastElementChild && player.extra.parentElement.lastElementChild.matches("[data-full]")')
    press(c, 'menu')
    bounded(c)
    assert c.js('document.querySelector("[data-anki-meaning]").value') == 'One editor in and out of fullscreen'


def test_word_range_preview_add_and_update(anki_browser):
    c, url, handler = anki_browser
    ready(c, url)
    assert c.js('!!document.querySelector("[data-video]")')
    word(c)
    expression = c.js('player.ankiSelection().expression')
    assert expression
    assert c.js('document.querySelector("[data-anki-expression]").value') == expression
    word(c, 2, shift=True)
    assert c.js('player.ankiSelection().first === 0 && player.ankiSelection().last === 2')
    assert c.js('document.querySelectorAll(".ov .anki-selected").length') >= 3
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    assert c.js('document.querySelector("[data-anki-deck]").value') == 'Mandarin'
    assert c.js('document.querySelector("[data-anki-save]").disabled')
    fill(c, 'meaning', 'My meaning <b>plain text</b>')
    press(c, 'retry')
    wait(c, 'document.querySelector(".anki").getAttribute("aria-busy") === "false"')
    assert c.js('document.querySelector("[data-anki-meaning]").value') == 'My meaning <b>plain text</b>'
    preview(c)
    first = next(data for path, data in handler.calls if path.endswith('/preview'))
    assert first['selection']['first'] == 0 and first['selection']['last'] == 2
    fill(c, 'start', str(first['start'] + .05))
    assert c.js('document.querySelector("[data-anki-audio]").hidden && document.querySelector("[data-anki-save]").disabled')
    assert len([p for p, _ in handler.calls if p.endswith('/preview')]) == 1
    preview(c)
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").textContent === "Added"')
    assert c.js('document.querySelector("[data-anki-save]").disabled')
    export_index = next(i for i, (path, _) in enumerate(handler.calls) if path.endswith('/export'))
    assert handler.calls[export_index - 1][0] == '/api/anki/status'
    exported = handler.calls[export_index][1]
    assert exported['preview'] == '/preview.wav'
    assert exported['meaning'] == 'My meaning <b>plain text</b>'
    assert exported['update'] is False and exported['profile'] == 'Study'
    fill(c, 'translation', 'Edited translation')
    assert c.js('document.querySelector("[data-anki-save]").textContent') == 'Update existing note'
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").textContent === "Updated"')
    assert [data for path, data in handler.calls if path.endswith('/export')][-1]['update'] is True
    press(c, 'open')
    wait(c, 'document.querySelector("[data-anki-result]").textContent === "Opened in Anki."')
    assert handler.calls[-1] == ('/api/anki/open', {'noteId': 123, 'profile': 'Study'})
    (ROOT / 'scratch' / 'anki-menu.png').write_bytes(base64.b64decode(c.call('Page.captureScreenshot', format='png')['data']))


def test_connection_failure_keeps_draft_and_requires_explicit_update(anki_browser):
    c, url, handler = anki_browser
    ready(c, url)
    word(c)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    fill(c, 'meaning', 'Keep this draft')
    preview(c)
    for state in ('unavailable', 'auth', 'wrong_service', 'no_collection'):
        handler.state = state
        press(c, 'save')
        wait(c, f'document.querySelector("[data-anki-status]").dataset.state === "{state}" && document.querySelector(".anki").getAttribute("aria-busy") === "false"')
        assert c.js('document.querySelector("[data-anki-meaning]").value') == 'Keep this draft'
    assert not any(path.endswith('/export') for path, _ in handler.calls)
    handler.fail_status = True
    press(c, 'retry')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "error"')
    handler.fail_status = False
    handler.state = 'connected'
    handler.fail_export = True
    press(c, 'retry')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-result]").textContent.includes("disconnected")')
    assert c.js('document.querySelector("[data-anki-meaning]").value') == 'Keep this draft'
    handler.fail_export = False
    handler.export_state = 'exists'
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").textContent === "Update existing note"')
    requests = [data for path, data in handler.calls if path.endswith('/export')]
    assert len(requests) == 2 and all(not data['update'] for data in requests)
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").textContent === "Updated"')
    assert [data for path, data in handler.calls if path.endswith('/export')][-1]['update'] is True


def test_sentence_settings_new_deck_and_source_reset(anki_browser):
    c, url, handler = anki_browser
    ready(c, url)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    assert c.js('!document.querySelector("[data-anki-help]").hidden')
    press(c, 'sentence')
    assert c.js('player.ankiSelection().first === null && !document.querySelector("[data-anki-draft]").hidden')
    assert 'sentence timing' in c.js('document.querySelector("[data-anki-timing]").textContent')
    fill(c, 'port', '8766')
    fill(c, 'key', 'test-key')
    press(c, 'connect')
    wait(c, 'document.querySelector("[data-anki-key]").value === ""')
    assert [data for path, data in handler.calls if path.endswith('/settings')][-1] == {'port': 8766, 'key': 'test-key'}
    c.js('document.querySelector("[data-anki-deck]").value="";document.querySelector("[data-anki-deck]").dispatchEvent(new Event("change"))')
    fill(c, 'new', 'My new deck')
    preview(c)
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").textContent === "Added"')
    assert [data for path, data in handler.calls if path.endswith('/export')][-1]['deck'] == 'My new deck'
    fill(c, 'end', '100000')
    assert c.js('document.querySelector("[data-anki-preview]").disabled')
    press(c, 'context')
    assert c.js('Number(document.querySelector("[data-anki-end]").value) <= player.video.duration')
    handler.preview_gate.clear()
    before = len(handler.calls)
    press(c, 'preview')
    wait(c, 'document.querySelector(".anki").getAttribute("aria-busy") === "true"')
    c.js('current={id:"second"};player.begin();ankiUI.reset()')
    handler.preview_gate.set()
    wait(c, 'document.querySelector("[data-anki-draft]").hidden')
    c.js('new Promise(r=>setTimeout(r,150))')
    assert len(handler.calls) > before
    assert c.js('document.querySelector("[data-anki-expression]").value === "" && document.querySelector("[data-anki-audio]").hidden')


def test_demo_and_narrow_menu(anki_browser):
    c, url, handler = anki_browser
    c.call('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=True)
    navigate(c, url + '/test.html?demo')
    wait(c, 'document.querySelector(".anki")')
    press(c, 'menu')
    assert 'local Pianpian app' in c.js('document.querySelector("[data-anki-status]").textContent')
    assert not handler.calls
    assert c.js('document.querySelector("[data-anki-sentence]").disabled')
    assert c.js('(() => {const r=document.querySelector(".anki-panel").getBoundingClientRect();return r.left>=0 && r.right<=innerWidth;})()')


def test_profile_change_and_late_export(anki_browser):
    c, url, handler = anki_browser
    ready(c, url)
    word(c)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    fill(c, 'meaning', 'My draft survives a profile switch')
    preview(c)
    handler.profile = 'Another profile'
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-result]").textContent.includes("profile changed")')
    assert not any(path.endswith('/export') for path, _ in handler.calls)
    assert c.js('document.querySelector("[data-anki-meaning]").value') == 'My draft survives a profile switch'
    handler.export_gate.clear()
    press(c, 'save')
    wait(c, 'document.querySelector(".anki").getAttribute("aria-busy") === "true"')
    # Wait for the POST to leave the page before changing media.
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    c.js('new Promise(r=>setTimeout(r,100))')
    assert any(path.endswith('/export') for path, _ in handler.calls)
    c.js('current={id:"second"};player.begin();ankiUI.reset()')
    handler.export_gate.set()
    c.js('new Promise(r=>setTimeout(r,150))')
    assert c.js('document.querySelector("[data-anki-result]").textContent === "" && document.querySelector("[data-anki-open]").hidden')
    assert c.js('document.querySelector("[data-anki-expression]").value === "" && document.querySelector("[data-anki-audio]").hidden')


def test_same_selection_and_delay_preserve_edits_and_note(anki_browser):
    c, url, handler = anki_browser
    ready(c, url)
    word(c)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    preview(c)
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").textContent === "Added"')
    fill(c, 'meaning', 'Keep my edited meaning')
    original = c.js('player.ankiSelection()')
    manual_start = original['start'] + .123
    fill(c, 'start', str(manual_start))
    preview(c)
    press(c, 'close')
    word(c)
    assert c.js('document.querySelector("[data-anki-meaning]").value') == 'Keep my edited meaning'
    assert c.js('document.querySelector("[data-anki-start]").valueAsNumber') == manual_start
    assert c.js('!document.querySelector("[data-anki-audio]").hidden && !document.querySelector("[data-anki-open]").hidden')
    # Open the real subtitle menu and change its delay control with keyboard input.
    c.js('document.querySelector("[data-delay]").closest("details.dd").querySelector("summary").setAttribute("data-test-subtitles", "")')
    c.js('document.querySelector("[data-test-subtitles]").scrollIntoView({block:"center"})')
    click(c, '[data-test-subtitles]')
    c.js('document.querySelector("[data-delay]").scrollIntoView({block:"center"})')
    click(c, '[data-delay]')
    c.js('document.querySelector("[data-delay]").select()')
    c.call('Input.insertText', text='0.5')
    c.call('Input.dispatchKeyEvent', type='keyDown', key='Tab', code='Tab', windowsVirtualKeyCode=9)
    c.call('Input.dispatchKeyEvent', type='keyUp', key='Tab', code='Tab', windowsVirtualKeyCode=9)
    wait(c, f'player.ankiSelection().start === {original["start"] + .5}')
    assert c.js('document.querySelector("[data-anki-meaning]").value') == 'Keep my edited meaning'
    assert c.js('document.querySelector("[data-anki-audio]").hidden && !document.querySelector("[data-anki-open]").hidden')
    assert c.js('document.querySelector("[data-anki-start]").valueAsNumber') == pytest.approx(max(0, original['start'] + .5 - .15))
    assert c.js('document.querySelector("[data-anki-save]").textContent') == 'Update existing note'
    press(c, 'menu')
    wait(c, 'document.querySelector(".anki").getAttribute("aria-busy") === "false"')
    preview(c)
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").textContent === "Updated"')
    exported = [data for path, data in handler.calls if path.endswith('/export')][-1]
    assert exported['update'] is True and exported['meaning'] == 'Keep my edited meaning'
    assert exported['selection']['sentence'] == original['sentence']
    assert exported['selection']['expression'] == original['expression']
    press(c, 'open')
    wait(c, 'document.querySelector("[data-anki-result]").textContent === "Opened in Anki."')
    assert handler.calls[-1] == ('/api/anki/open', {'noteId': 123, 'profile': 'Study'})


def test_preview_normalizes_small_duration_clamp_for_export(anki_browser):
    c, url, handler = anki_browser
    handler.preview_end_offset = -.004
    ready(c, url)
    word(c)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    preview(c)
    requested = [data for path, data in handler.calls if path.endswith('/preview')][-1]
    returned_end = requested['end'] - .004
    assert c.js('document.querySelector("[data-anki-end]").valueAsNumber') == returned_end
    press(c, 'save')
    wait(c, 'document.querySelector("[data-anki-save]").textContent === "Added"')
    exported = [data for path, data in handler.calls if path.endswith('/export')][-1]
    assert exported['start'] == requested['start'] and exported['end'] == returned_end
    assert exported['preview'] == '/preview.wav'


@pytest.mark.parametrize('start_offset,end_offset', [(.002, -.004), (0, -.051), (0, -100), (0, 100)])
def test_preview_rejects_shifted_or_invalid_interval(anki_browser, start_offset, end_offset):
    c, url, handler = anki_browser
    handler.preview_start_offset = start_offset
    handler.preview_end_offset = end_offset
    ready(c, url)
    word(c)
    press(c, 'menu')
    wait(c, 'document.querySelector("[data-anki-status]").dataset.state === "connected"')
    before = c.js('[document.querySelector("[data-anki-start]").value, document.querySelector("[data-anki-end]").value]')
    press(c, 'preview')
    wait(c, 'document.querySelector("[data-anki-result]").textContent.includes("preview interval changed")')
    assert c.js('document.querySelector("[data-anki-audio]").hidden && document.querySelector("[data-anki-save]").disabled')
    assert c.js('[document.querySelector("[data-anki-start]").value, document.querySelector("[data-anki-end]").value]') == before
