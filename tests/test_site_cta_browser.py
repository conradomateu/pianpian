"""Landing CTAs in a real Chromium browser with emulated visitor devices; not physical-device tests."""
import base64
import json
from pathlib import Path

import pytest

from test_player_browser import browser, click, navigate, wait  # noqa: F401
from test_site_os import MAC_UA, SAFARI, WIN_UA

ROOT = Path(__file__).resolve().parents[1]


def visible_downloads(c):
    return c.js("[...document.querySelectorAll('[data-umami-event=\"download\"]')].filter(e=>e.getClientRects().length).map(e=>e.textContent)")


def click_star(c, selector):
    # Keep automated checks offline: a real mouse click must reach the normal repository link.
    c.js(f"""document.querySelector({json.dumps(selector)}).addEventListener('click', e => {{
      e.preventDefault(); window.starClicked = e.currentTarget.getAttribute('href');
    }}, {{once:true}})""")
    c.js(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block:'center',behavior:'instant'}})")
    click(c, selector)
    assert c.js('window.starClicked') == 'https://github.com/{{REPO}}'  # Fixture retains the build template.
    c.js('delete window.starClicked')


@pytest.mark.parametrize('name,ua,width,touch', [
    ('iphone', 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1', 390, 5),
    ('android', 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/130.0.0.0 Mobile Safari/537.36', 320, 5),
    ('ipad-desktop-ua', SAFARI, 1024, 5),
    ('ipad', 'Mozilla/5.0 (iPad; CPU OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1', 820, 5),
])
def test_mobile_only_offers_github_ctas(browser, name, ua, width, touch):  # noqa: F811
    c, url, _ = browser
    c.call('Emulation.setUserAgentOverride', userAgent=ua)
    c.call('Emulation.setTouchEmulationEnabled', enabled=True, maxTouchPoints=touch)
    c.call('Emulation.setDeviceMetricsOverride', width=width, height=900, deviceScaleFactor=1, mobile=True)
    navigate(c, url + '/index.html')
    wait(c, "document.documentElement.dataset.siteOs === 'other'")
    assert visible_downloads(c) == []  # Includes the formerly visible header Download.
    assert 'isn’t available' in c.js("document.querySelector('#os-note').textContent")
    assert c.js("[...document.querySelectorAll('.cta')].every(pair=>[...pair.querySelectorAll('a')].filter(a=>a.getClientRects().length).length===1)")
    assert c.js("[...document.querySelectorAll('.cta .star')].every(a=>a.classList.contains('dl'))")
    assert c.js('document.documentElement.scrollWidth <= innerWidth')
    shot = ROOT / 'scratch' / f'cta-{name}.png'
    shot.write_bytes(base64.b64decode(c.call('Page.captureScreenshot', format='png')['data']))
    for selector in ('header.top .star', '#download .star', '.final .star'):
        click_star(c, selector)
    assert visible_downloads(c) == []


@pytest.mark.parametrize('os,ua', [('mac', MAC_UA), ('windows', WIN_UA)])
def test_desktop_keeps_download_and_secondary_github(browser, os, ua):  # noqa: F811
    c, url, _ = browser
    c.call('Emulation.setUserAgentOverride', userAgent=ua)
    c.call('Emulation.setDeviceMetricsOverride', width=1440, height=1000, deviceScaleFactor=1, mobile=False)
    navigate(c, url + '/index.html')
    wait(c, f"document.documentElement.dataset.siteOs === {json.dumps(os)}")
    assert len(visible_downloads(c)) == 3
    assert c.js("[...document.querySelectorAll('[data-os]')].filter(a=>a.getClientRects().length).map(a=>a.dataset.os)") == [os, os]
    assert c.js("[...document.querySelectorAll('.cta .star')].every(a=>a.classList.contains('ghost') && !a.classList.contains('dl'))")
    for selector in ('header.top .star', '#download .star', '.final .star'):
        click_star(c, selector)
    # Narrow desktop windows are still desktop, not inferred to be phones from viewport width.
    c.call('Emulation.setDeviceMetricsOverride', width=320, height=844, deviceScaleFactor=1, mobile=False)
    assert len(visible_downloads(c)) == 3
    assert c.js('document.documentElement.scrollWidth <= innerWidth')
