"""Player selection with real browser input and original subtitle/timing fixtures."""
import functools
import json
import shutil
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import build_site, shots  # noqa: E402
from test_player_browser import click, navigate, wait  # noqa: E402


@pytest.fixture
def selection_browser():
    exe = next((b for b in shots.BROWSERS if Path(b).exists()), None)
    if not exe:
        pytest.skip("Chrome, Brave or Chromium required")
    (ROOT / "scratch").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / "scratch", prefix="anki-selection-") as directory:
        dest = Path(directory)
        shutil.copytree(ROOT / "assets", dest / "assets")
        shutil.copytree(ROOT / "demo" / "library", dest / "library")
        (dest / "index.html").write_text('<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="assets/kit.css">'
                                        '<link rel="stylesheet" href="assets/anki.css">'
                                        '<div id="player" style="margin:20px"></div><script src="assets/player.js"></script>', encoding="utf-8")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(build_site.RangedHandler, directory=dest))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        c = shots.Chrome(exe, str(dest / "profile"))
        try:
            target = next(t for t in c.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
            c.session = c.call("Target.attachToTarget", targetId=target["targetId"], flatten=True)["sessionId"]
            c.call("Page.enable")
            navigate(c, f"http://127.0.0.1:{srv.server_port}/index.html")
            assert c.js("""(() => {
              window.changes = [];
              window.opened = [];
              window.playerOpts = {onAnkiSelection: s => changes.push(s),
                onAnkiOpen: anchor => opened.push({anchor, selection:p.ankiSelection()})};
              window.p = SubPlayer.mount(document.querySelector('#player'), playerOpts);
              window.testWords = {cues: [
                {s:1,e:3,w:[[['我','wǒ','I'],['喝','hē','drink'],['茶','chá','tea'],['。','.']], [['你好','nǐhǎo','hello']]],
                 k:[[[1.05,1.25],[1.3,1.55],[1.6,1.95],0],[[2.1,2.8]]]},
                {s:4,e:6,w:[[['明天','míngtiān','tomorrow'],['见','jiàn','see'],['。','.']]],k:[[[4.1,4.7],[4.8,5.6],0]]},
                {s:7,e:9,w:[[['谢谢','xièxie','thank you'],['。','.']]],k:[[[7.1,8.5],0]]}
              ]};
              const srt = rows => rows.map(([s,e,text],i) => `${i+1}\\n00:00:${s.toFixed(3).padStart(6,'0')} --> 00:00:${e.toFixed(3).padStart(6,'0')}\\n${text}`).join('\\n\\n');
              window.testSubs = [
                {name:'zh.srt',text:srt([[1,3,'我喝茶。\\n你好'],[4,6,'明天见。'],[7,9,'谢谢。']])},
                {name:'zh.pinyin.srt',text:srt([[1,3,'wǒ hē chá.\\nnǐhǎo'],[4,6,'míngtiān jiàn.'],[7,9,'xièxie.']])},
                {name:'zh.en.srt',text:srt([[0,.5,'Before'],[.8,3.2,'I drink tea. Hello.'],[4,6,'See you tomorrow.'],[7,9,'Thank you.']])}
              ];
              p.load({id:'original',video:'library/pianpian-day/source.mp4',subs:testSubs,words:testWords});
              return true;
            })()""")
            wait(c, "p.video.readyState >= 3 && document.querySelector('.load-state').hidden")
            c.js("p.video.currentTime = 1.1")
            wait(c, "!p.video.seeking && document.querySelector('.ov .w[data-anki-cue=\"0\"]')")
            yield c
        finally:
            c.close()
            srv.shutdown()
            srv.server_close()


def shift_click(c, selector):
    point = c.js(f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; }})()")
    for event in ("mousePressed", "mouseReleased"):
        c.call("Input.dispatchMouseEvent", type=event, x=point[0], y=point[1], button="left", clickCount=1, modifiers=8)


def test_outside_click_dismisses_word_but_keeps_export_draft(selection_browser):
    c = selection_browser
    c.js("document.body.insertAdjacentHTML('afterbegin', '<button id=outside>Outside word</button>')")
    click(c, '.ov .w[data-anki-word="1"]')
    wait(c, "document.querySelector('[data-anki-word-action]')")
    count = c.js('changes.length')
    click(c, '.ov .gl > span')
    assert c.js("p.video.paused && !!document.querySelector('[data-anki-word-action]')")
    click(c, '[data-anki-word-action]')
    assert c.js('opened.length') == 1
    click(c, '#outside')
    assert c.js("!document.querySelector('.w.anki-selected, .w.hl, .w[aria-pressed=true]') && document.querySelector('.ov .gl').textContent === ''")
    assert c.js('changes.length') == count  # Closing the word does not reset the editor's saved draft.
    shift_click(c, '.ov .w[data-anki-word="2"]')
    assert c.js('p.ankiSelection().expression') == '茶'


def test_pinned_word_action_real_click_over_controls_keeps_selection(selection_browser):
    c = selection_browser
    point = c.js("(() => { const r = document.querySelector('.ov .w[data-anki-word=\"1\"]').getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; })()")
    c.call("Input.dispatchMouseEvent", type="mouseMoved", x=point[0], y=point[1])
    assert c.js("document.querySelector('.ov .gl').textContent.includes('drink') && !document.querySelector('[data-anki-word-action]')")
    click(c, '[data-play]')
    wait(c, '!p.video.paused')
    click(c, '.ov .w[data-anki-word="1"]')
    wait(c, "p.video.paused && document.querySelector('[data-anki-word-action]')")
    selected = c.js('p.ankiSelection()')
    count = c.js('changes.length')
    assert c.js("""(() => {
      const b = document.querySelector('[data-anki-word-action]'), img = b.querySelector('img');
      window.action = b;
      return [b.tagName,b.type,b.className,b.getAttribute('aria-label'),b.title,img.getAttribute('src'),img.alt];
    })()""") == ['BUTTON', 'button', 'anki-word-action', 'Prepare Anki card', 'Prepare Anki card', 'assets/anki-logo.png', '']
    # Stress the shared hit-test layer: place the card directly over the real control bar.
    c.js("""(() => {
      const bar = document.querySelector('.vc').getBoundingClientRect(), r = action.getBoundingClientRect();
      document.querySelector('.ov').style.transform = `translateY(${bar.y+bar.height/2-r.y-r.height/2}px)`;
    })()""")
    click(c, '[data-anki-word-action] img')
    assert c.js("[opened.length,opened[0]?.anchor === action,changes.length,p.video.paused]") == [1, True, count, True]
    assert c.js('opened[0].selection') == selected
    assert c.js('p.ankiSelection()') == selected
    assert c.js("new Promise(r => setTimeout(() => r(p.video.paused && action.isConnected), 350))")
    c.js('p.clearAnkiSelection()')
    assert c.js("!document.querySelector('[data-anki-word-action]')")


def test_transcript_pin_action_keyboard_focus_survives_redraw(selection_browser):
    c = selection_browser
    click(c, '.transcript .zh .w[data-anki-cue="1"][data-anki-word="0"]')
    wait(c, '!p.video.seeking && document.querySelector("[data-anki-word-action]")')
    assert c.js('p.ankiSelection().expression') == '明天'
    c.js("window.action = document.querySelector('[data-anki-word-action]'); document.querySelector('.ov .w').focus()")
    for event in ('keyDown', 'keyUp'):
        c.call('Input.dispatchKeyEvent', type=event, key='Tab', code='Tab', windowsVirtualKeyCode=9, modifiers=8)
    assert c.js('document.activeElement === action')
    # A forced subtitle redraw and the paused timer must retain the actual focused node.
    c.js("document.querySelector('[data-colour]').dispatchEvent(new Event('input', {bubbles:true}))")
    assert c.js("new Promise(r => setTimeout(() => r(document.activeElement === action && action.isConnected), 350))")
    count = c.js('changes.length')
    for total, (key, code, number) in enumerate([('Enter', 'Enter', 13), (' ', 'Space', 32)], 1):
        for event in ('keyDown', 'keyUp'):
            c.call('Input.dispatchKeyEvent', type=event, key=key, code=code, windowsVirtualKeyCode=number,
                   text='\r' if event == 'keyDown' and key == 'Enter' else '')
        assert c.js('[opened.length,opened.at(-1)?.anchor === action,p.video.paused,changes.length]') == [total, True, True, count]
    shift_click(c, '.transcript .zh .w[data-anki-cue="1"][data-anki-word="1"]')
    selected = c.js('p.ankiSelection()')
    assert selected['expression'] == '明天见'
    count = c.js('changes.length')
    click(c, '[data-anki-word-action]')
    assert c.js('[opened.length,changes.length]') == [3, count]
    assert c.js('opened.at(-1).selection') == selected
    c.js('p.video.currentTime = 7.1')
    wait(c, '!p.video.seeking')
    assert c.js("!document.querySelector('[data-anki-word-action]') && !document.querySelector('.gl').textContent")


def test_word_action_requires_callback_and_valid_chinese_anchor(selection_browser):
    c = selection_browser
    c.js('delete playerOpts.onAnkiOpen')
    click(c, '.ov .w[data-anki-word="1"]')
    assert c.js("document.querySelector('.gl').textContent.includes('drink') && !document.querySelector('[data-anki-word-action]')")
    c.js("playerOpts.onAnkiOpen = anchor => opened.push(anchor); testSubs[0].text = testSubs[0].text.replace('我喝茶。','我喝水。'); p.load({subs:testSubs,words:testWords})")
    click(c, '.ov .w[data-w="0-1"]')
    assert c.js("p.ankiSelection() === null && !document.querySelector('[data-anki-word-action]') && opened.length === 0")
    # Grammar cards keep their own content and never gain a dictionary action.
    c.js("""testSubs[0].text = testSubs[0].text.replace('我喝水。', '我没见。');
      testWords.cues[0].w[0] = [['我','wǒ','I'],['没','méi','not'],['见','jiàn','see'],['。','.']];
      testWords.cues[0].g = [[[1,'past:mei']],[]];
      p.load({subs:testSubs,words:testWords});
    """)
    click(c, 'details:has([data-grammar]) summary')
    c.js("document.querySelector('[data-grammar]').scrollIntoView({block:'nearest'})")
    click(c, '[data-grammar]')
    assert c.js("document.querySelector('[data-grammar]').classList.contains('on')")
    c.js("document.querySelector('[data-grammar-close]').scrollIntoView({block:'nearest'})")
    click(c, '[data-grammar-close]')
    assert c.js("!document.querySelector('details:has([data-grammar])').open")
    c.js("document.querySelector('.stage').scrollIntoView({block:'start'})")
    click(c, '.ov .g')
    assert c.js('p.ankiSelection().expression') == '没'
    c.call('Input.dispatchMouseEvent', type='mouseMoved', x=1, y=1)
    assert c.js("p.video.paused && document.querySelector('.gl .rule').textContent.includes('did not happen') && !document.querySelector('[data-anki-word-action]')")


def test_word_range_multiline_cross_cue_and_keyboard(selection_browser):
    c = selection_browser
    assert c.js("p.ankiSelection()") is None
    click(c, '[data-play]')
    wait(c, "!p.video.paused")
    click(c, '.ov .w[data-anki-word="1"]')
    assert c.js("p.ankiSelection()") == {
        "sourceId": "original", "cueStart": 0, "cueEnd": 0, "first": 1, "last": 1,
        "expression": "喝", "pinyin": "hē", "meaning": "drink", "sentence": "我喝茶。\n你好",
        "translation": "I drink tea. Hello.", "start": 1.3, "end": 1.55,
        "sentenceStart": 1, "sentenceEnd": 3, "timing": "word",
    }
    assert c.js("p.video.paused && document.querySelector('.ov .gl').textContent.includes('drink')")
    shift_click(c, '.transcript .zh .w[data-anki-cue="0"][data-anki-word="4"]')
    assert c.js("[p.ankiSelection().expression,p.ankiSelection().first,p.ankiSelection().last,p.ankiSelection().end]") == ["喝茶。你好", 1, 4, 2.8]
    shift_click(c, '.transcript .zh .w[data-anki-cue="1"][data-anki-word="1"]')
    assert c.js("[p.ankiSelection().cueStart,p.ankiSelection().cueEnd,p.ankiSelection().expression,p.ankiSelection().end]") == [0, 1, "喝茶。你好\n明天见", 5.6]
    assert c.js("document.querySelectorAll('.transcript .zh .anki-selected').length") == 5
    # Keyboard activation pauses without bubbling Space to the video shortcut.
    c.js("document.querySelector('.transcript .zh .w[data-anki-cue=\"1\"][data-anki-word=\"0\"]').focus()")
    c.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    assert c.js("p.ankiSelection().expression") == "明天"
    c.js("document.querySelector('.transcript .zh .w[data-anki-cue=\"0\"][data-anki-word=\"2\"]').focus()")
    c.call("Input.dispatchKeyEvent", type="keyDown", key=" ", code="Space", windowsVirtualKeyCode=32, modifiers=8)
    assert c.js("[p.ankiSelection().expression,p.video.paused]") == ["茶。你好\n明天", True]
    c.js("p.clearAnkiSelection()")
    assert c.js("p.ankiSelection() === null && changes.at(-1) === null && !document.querySelector('.anki-selected')")


def test_chinese_anchor_when_reordered_hidden_and_delayed(selection_browser):
    c = selection_browser
    click(c, 'details summary')
    click(c, '[data-up="2"]')
    click(c, '[data-up="1"]')
    # English lead has an extra cue, so lead indices differ from Chinese indices.
    click(c, '[data-on="1"]')
    click(c, 'details summary')
    click(c, '.transcript .en .w[data-anki-cue="0"][data-anki-word="2"]')
    assert c.js("[p.ankiSelection().cueStart,p.ankiSelection().expression,p.video.paused]") == [0, "茶", True]
    c.js("document.querySelector('[data-delay]').value = '.5'; document.querySelector('[data-delay]').dispatchEvent(new Event('change')); p.video.currentTime = 4.6")
    wait(c, "!p.video.seeking")
    assert c.js("p.selectAnkiSentence()") == {
        "sourceId": "original", "cueStart": 1, "cueEnd": 1, "first": None, "last": None,
        "expression": "明天见。", "pinyin": "míngtiān jiàn.", "meaning": "tomorrow; see",
        "sentence": "明天见。", "translation": "See you tomorrow.", "start": 4.5, "end": 6.5,
        "sentenceStart": 4.5, "sentenceEnd": 6.5, "timing": "sentence",
    }
    c.js("document.querySelector('[data-delay]').value = '1'; document.querySelector('[data-delay]').dispatchEvent(new Event('change'))")
    assert c.js("changes.at(-1).sentenceStart") == 5


def test_invalid_or_missing_times_never_use_uniform_karaoke(selection_browser):
    c = selection_browser
    bad_times = ["undefined", "{}", "[null]", "[]", "[[[1,2]]]", "[[[1,1],[1.3,1.5],[1.6,1.9],0],[[2.1,2.8]]]",
                 "[[[NaN,1.2],[1.3,1.5],[1.6,1.9],0],[[2.1,2.8]]]",
                 "[[[1,Infinity],[1.3,1.5],[1.6,1.9],0],[[2.1,2.8]]]",
                 "[[[.1,.3],[1.3,1.5],[1.6,1.9],0],[[2.1,2.8]]]",
                 "[[[1,1.5],[1.3,1.6],[1.6,1.9],0],[[2.1,2.8]]]",
                 "[[[1.01,1.02],[1,1.01],[1.6,1.9],0],[[2.1,2.8]]]",
                 "[[[1,1.2],[1.3,1.5],[1.6,1.9],0],[[2.1,30]]]",
                 "[[[1,1.2],0,[1.6,1.9],0],[[2.1,2.8]]]"]
    for times in bad_times:
        c.js(f"testWords.cues[0].k = {times}; p.load({{subs:testSubs,words:testWords}})")
        click(c, '.ov .w[data-anki-word="1"]')
        assert c.js("[p.ankiSelection().timing,p.ankiSelection().start,p.ankiSelection().end,p.ankiSelection().expression]") == ["sentence", 1, 3, "喝"], times
    # A hand-edited Chinese line cannot borrow stale token anchors or word audio.
    c.js("testSubs[0].text = testSubs[0].text.replace('我喝茶。','我喝水。'); p.load({subs:testSubs,words:testWords})")
    assert c.js("document.querySelectorAll('.w[data-anki-cue=\"0\"]').length") == 0
    assert c.js("[p.selectAnkiSentence().expression,p.ankiSelection().timing]") == ["我喝水。\n你好", "sentence"]
    # An untokenized intermediate cue stays in a cross-cue expression.
    c.js("testSubs[0].text = testSubs[0].text.replace('我喝水。','我喝茶。').replace('明天见。','明天喝水。'); p.load({subs:testSubs,words:testWords})")
    click(c, '.transcript .zh .w[data-anki-cue="0"][data-anki-word="4"]')
    shift_click(c, '.transcript .zh .w[data-anki-cue="2"][data-anki-word="0"]')
    assert c.js("[p.ankiSelection().expression,p.ankiSelection().timing]") == ["你好\n明天喝水。\n谢谢", "sentence"]


def test_begin_media_switch_and_async_append_invalidate(selection_browser):
    c = selection_browser
    click(c, '.ov .w[data-anki-word="1"]')
    c.js("p.begin(); p.load({id:'second',video:'library/pianpian-day/source.mp4'})")
    assert c.js("p.ankiSelection() === null && changes.at(-1) === null && !document.querySelector('.anki-selected')")
    wait(c, "p.video.readyState >= 3 && document.querySelector('.load-state').hidden")
    c.js("p.load({id:'original',subs:testSubs,words:testWords,append:true})")
    assert c.js("p.tracks.length") == 0
    c.js("p.load({id:'second',subs:testSubs,words:testWords,append:true}); p.video.currentTime = 1.1")
    wait(c, "!p.video.seeking && document.querySelector('.ov .w')")
    assert c.js("p.ankiSelection()") is None
    click(c, '.ov .w[data-anki-word="2"]')
    assert c.js("p.ankiSelection().sourceId") == "second"
    c.js("p.load({subs:testSubs,words:testWords})")
    assert c.js("p.ankiSelection() === null && changes.at(-1) === null")


def test_controls_keep_native_keyboard_actions_without_video_shortcuts(selection_browser):
    c = selection_browser
    c.js("""p.extra.innerHTML = `<details class="dd" id="anki-like"><summary>Anki</summary><div class="ddp">
      <button id="export-like">Export</button><input id="margin-like" type="range" min="0" max="10" value="5">
      <audio id="preview-like" controls src="library/pianpian-day/source.mp4"></audio>
      <div contenteditable="true"><span id="editable-child" tabindex="0">Draft</span></div>
      <a href="#anki-like"><span id="link-child" tabindex="0">Note</span></a>
      <div role="button"><span id="role-child" tabindex="0">Preview</span></div>
      <div id="handled-key" tabindex="0">Handled locally</div>
      </div></details>`;
      window.exportsClicked = 0;
      document.querySelector('#export-like').onclick = () => exportsClicked++;
      document.querySelector('#handled-key').onkeydown = e => e.preventDefault();
    """)

    def press(selector, key, code, number):
        c.js(f"document.querySelector({json.dumps(selector)}).focus()")
        for event in ("keyDown", "keyUp"):
            c.call("Input.dispatchKeyEvent", type=event, key=key, code=code, windowsVirtualKeyCode=number)

    press('#anki-like summary', ' ', 'Space', 32)
    wait(c, "document.querySelector('#anki-like').open")
    assert c.js("p.video.paused")
    press('#export-like', ' ', 'Space', 32)
    assert c.js("[exportsClicked,p.video.paused]") == [1, True]
    before = c.js("p.video.currentTime")
    press('#margin-like', 'ArrowRight', 'ArrowRight', 39)
    assert c.js("[document.querySelector('#margin-like').value,p.video.currentTime]") == ['6', before]
    for selector in ('#editable-child', '#link-child', '#role-child', '#handled-key'):
        press(selector, 'ArrowRight', 'ArrowRight', 39)
        assert c.js("p.video.currentTime") == before, selector
    press('#handled-key', ' ', 'Space', 32)
    assert c.js("p.video.paused")
    wait(c, "document.querySelector('#preview-like').readyState >= 3")
    press('#preview-like', ' ', 'Space', 32)
    wait(c, "!document.querySelector('#preview-like').paused")
    assert c.js("p.video.paused && p.video.currentTime") == before
