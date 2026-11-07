"""Landing-page examples: actual demo data, real clicks and bounded audio playback."""
import json
import time
from pathlib import Path

from test_player_browser import browser, click, navigate, wait  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def press(c, selector):
    c.js(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block:'center',behavior:'instant'}})")
    click(c, selector)


def test_landing_examples(browser):  # noqa: F811 (shared pytest fixture)
    c, url, _ = browser
    c.call('Emulation.setDeviceMetricsOverride', width=1440, height=1000, deviceScaleFactor=1, mobile=False)
    c.call('Emulation.setEmulatedMedia', features=[{'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    navigate(c, url + '/index.html')
    wait(c, "!document.querySelector('[data-pp-word]').disabled")
    play_icon = c.js("document.querySelector('[data-pp-play-icon]').getAttribute('d')")
    source = ROOT / 'demo/library/pianpian-day'
    cue = json.loads((source / 'zh.words.json').read_text())['cues'][5]
    for index, word in enumerate(cue['w'][0][:4]):
        press(c, f'[data-pp-word="{index}"]')
        assert c.js("document.querySelector('[data-pp-gloss-word]').textContent") == word[0]
        assert c.js("document.querySelector('[data-pp-pinyin]').textContent") == word[1]
        assert c.js("document.querySelector('[data-pp-meaning]').textContent") == word[2]
    assert c.js("[...document.querySelectorAll('[data-pp-pinyin] span')].map(e=>e.className)") == ['t1', 't2']
    press(c, '[data-pp-role="1"]')
    assert 'in progress' in c.js("document.querySelector('[data-pp-role-text]').textContent")
    # The next native button must also activate with Tab + Enter.
    c.call('Input.dispatchKeyEvent', type='keyDown', key='Tab', code='Tab', windowsVirtualKeyCode=9)
    c.call('Input.dispatchKeyEvent', type='keyUp', key='Tab', code='Tab', windowsVirtualKeyCode=9)
    assert c.js("document.activeElement.dataset.ppRole") == '2', c.js("document.activeElement.outerHTML")
    c.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13, text='\r')
    c.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    assert c.js("document.querySelector('[data-pp-role=\"2\"]').getAttribute('aria-pressed')") == 'true'

    press(c, '[data-pp-slow]')
    assert c.js("document.querySelector('[data-pp-audio]').playbackRate") == .75
    assert c.js("document.querySelector('[data-pp-speed]').textContent") == '0.75×'
    press(c, '[data-pp-play]')
    wait(c, "document.querySelector('[data-pp-audio]').currentTime > 22.6 && document.querySelector('.pp-speaking')")
    assert c.js("document.querySelector('[data-pp-play]').getAttribute('aria-label')") == 'Pause'
    assert c.js("document.querySelector('[data-pp-play-icon]').getAttribute('d')") != play_icon
    press(c, '[data-pp-play]')
    assert c.js("document.querySelector('[data-pp-audio]').paused")
    wait(c, "document.querySelector('[data-pp-play-icon]').getAttribute('d') === " + json.dumps(play_icon))
    assert not c.js("document.querySelector('.pp-speaking')")
    press(c, '[data-pp-play]')
    wait(c, "document.querySelector('[data-pp-play]').getAttribute('aria-label') === 'Replay line'")
    assert abs(c.js("document.querySelector('[data-pp-audio]').currentTime") - cue['e']) < .05
    press(c, '[data-pp-slow]')
    press(c, '[data-pp-loop]')
    press(c, '[data-pp-play]')
    wait(c, "document.querySelector('[data-pp-audio]').currentTime > 25")
    wait(c, "document.querySelector('[data-pp-audio]').currentTime < 23.2")
    assert not c.js("document.querySelector('[data-pp-audio]').paused")
    press(c, '[data-pp-play]')

    tracks = c.js("[...document.querySelectorAll('#pp-replay .l')].map(e=>e.textContent)")
    for name, text in zip(['zh.srt', 'zh.pinyin.srt', 'zh.en.srt'], tracks):
        assert text in (source / name).read_text()
    wait(c, "document.querySelector('#pp-replay [data-pp-en] button')")
    press(c, '#pp-replay [data-pp-en] [data-pp-linked="2"]')
    assert c.js("[...document.querySelectorAll('#pp-replay .w.hl')].map(e=>e.textContent)") == ['学', 'xué', 'learning']
    press(c, '#pp-replay [data-pp-py] [data-pp-linked="3"]')
    assert c.js("[...document.querySelectorAll('#pp-replay .w.hl')].map(e=>e.textContent)") == ['中文', 'zhōngwén', 'Chinese']
    assert c.js("[...document.querySelectorAll('#pp-replay [data-pp-py] [data-pp-linked=\"3\"] span')].map(e=>e.className)") == ['t1', 't2']
    press(c, '#pp-replay [data-pp-zh] [data-pp-linked="1"]')
    assert c.js("document.querySelectorAll('#pp-replay [data-pp-en] .hl').length") == 0  # No invented link for 正在.
    assert c.js("[...document.querySelectorAll('[data-pp-role-pinyin=\"1\"] span')].map(e=>e.className)") == ['t4', 't4']
    press(c, '#faq-files > summary')
    assert c.js("document.querySelector('#faq-files').open")
    assert c.js("document.querySelector('#faq-files code').textContent") == '~/Movies/Pianpian'
    for href in c.js("[...document.querySelectorAll('#faq-files a')].map(e=>e.getAttribute('href'))"):
        assert (ROOT / href).is_file()

    for mode in ['light', 'dark']:
        c.call('Emulation.setEmulatedMedia', features=[{'name': 'prefers-color-scheme', 'value': mode}, {'name': 'prefers-reduced-motion', 'value': 'reduce'}])
        for width in [320, 390, 641, 1001, 1440]:
            c.call('Emulation.setDeviceMetricsOverride', width=width, height=1000, deviceScaleFactor=1, mobile=False)
            assert c.js('document.documentElement.scrollWidth <= innerWidth')
            assert c.js("[...document.querySelectorAll('.dl')].every(e=>getComputedStyle(e).color==='rgb(255, 255, 255)')")
            assert c.js("[...document.querySelectorAll('.pp-timeline text')].every(e=>parseFloat(getComputedStyle(e).fontSize)*e.getScreenCTM().a>=12)")
            wait(c, """(() => {
              const expected = document.createElement('span'); expected.style.color='var(--tr-en)'; document.body.append(expected);
              const blue=getComputedStyle(expected).color; expected.remove();
              return [...document.querySelectorAll('[data-pp-en]')].every(e=>getComputedStyle(e).color===blue);
            })()""")
    assert c.js("parseFloat(getComputedStyle(document.querySelector('.pp-preview .w')).transitionDuration)") <= .00001


def test_main_download_buttons_show_both_platforms_and_accept_real_clicks(browser):  # noqa: F811
    c, url, _ = browser
    navigate(c, url + '/index.html')
    assert c.js("document.querySelector('header.top .dl').querySelectorAll('svg').length") == 2
    for where in ('hero', 'bottom'):
        selector = f'[data-umami-event-where="{where}"][data-os="mac"]'
        assert c.js(f"""(() => {{ const a = document.querySelector({json.dumps(selector)});
          return [a.textContent, a.querySelectorAll('svg').length]; }})()""") == ['Download Pianpian', 2]
        c.js(f"document.querySelector({json.dumps(selector)}).addEventListener('click', e => {{ e.preventDefault(); window.downloadClicked = {json.dumps(where)}; }})")
        press(c, selector)
        assert c.js('window.downloadClicked') == where


def test_mobile_explains_computer_only_and_highlights_no_download(browser):  # noqa: F811
    c, url, _ = browser
    c.call('Emulation.setUserAgentOverride', userAgent='Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1')
    c.call('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=True)
    navigate(c, url + '/index.html')
    wait(c, "!document.querySelector('#os-note').hidden")
    assert 'not phones or tablets' in c.js("document.querySelector('#os-note').textContent")
    assert c.js("document.querySelectorAll('[data-os].dl').length") == 0


def test_static_landing_without_javascript(browser):  # noqa: F811 (shared pytest fixture)
    c, url, _ = browser
    c.call('Emulation.setScriptExecutionDisabled', value=True)
    c.call('Page.navigate', url=url + '/index.html')
    node = 0
    for _ in range(80):
        try:
            root = c.call('DOM.getDocument')['root']['nodeId']
            node = c.call('DOM.querySelector', nodeId=root, selector='#pp-definition')['nodeId']
        except RuntimeError as error:
            if 'Could not find node' not in str(error):
                raise
        if node:
            break
        time.sleep(.1)
    assert node
    assert 'to learn; to study; to imitate' in c.call('DOM.getOuterHTML', nodeId=node)['outerHTML']
    for selector in ['#pp-role-detail', '#faq-files > summary']:
        node = c.call('DOM.querySelector', nodeId=root, selector=selector)['nodeId']
        assert node
        assert c.call('DOM.getBoxModel', nodeId=node)['model']['height'] > 0
    c.call('DOM.scrollIntoViewIfNeeded', nodeId=node)
    quad = c.call('DOM.getBoxModel', nodeId=node)['model']['border']
    x, y = (quad[0] + quad[2]) / 2, (quad[1] + quad[5]) / 2
    for event in ('mousePressed', 'mouseReleased'):
        c.call('Input.dispatchMouseEvent', type=event, x=x, y=y, button='left', clickCount=1)
    node = c.call('DOM.querySelector', nodeId=root, selector='#faq-files a[href$="zh.en.srt"]')['nodeId']
    assert c.call('DOM.getBoxModel', nodeId=node)['model']['height'] > 0
