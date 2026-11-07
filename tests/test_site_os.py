"""The landing page's visitor-computer check (assets/site-os.js) over sample browsers. The user agents are typical
strings, the hints what Chromium's getHighEntropyValues returns; none of this is a test on the real devices."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAC_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
SAFARI = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15'
WIN_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
FIREFOX_WIN = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0'
CASES = [
    ('mac-arm-chrome', {'ua': MAC_UA, 'platform': 'macOS', 'hints': {'architecture': 'arm', 'bitness': '64', 'platformVersion': '15.1.0'}}, 'mac', True),
    ('mac-arm-old-macos', {'ua': MAC_UA, 'platform': 'macOS', 'hints': {'architecture': 'arm', 'platformVersion': '13.6.0'}}, 'mac', False),
    ('mac-intel-chrome', {'ua': MAC_UA, 'platform': 'macOS', 'hints': {'architecture': 'x86', 'bitness': '64', 'platformVersion': '14.0.0'}}, 'mac', False),
    ('mac-safari', {'ua': SAFARI, 'gpu': 'Apple GPU'}, 'mac', None),
    ('mac-safari-m-gpu', {'ua': SAFARI, 'gpu': 'Apple M2'}, 'mac', None),
    ('ipad', {'ua': SAFARI, 'touch': 5}, 'other', False),
    ('win11-x64', {'ua': WIN_UA, 'platform': 'Windows', 'hints': {'architecture': 'x86', 'bitness': '64', 'platformVersion': '19.0.0'}}, 'windows', True),
    ('win10-x64', {'ua': WIN_UA, 'platform': 'Windows', 'hints': {'architecture': 'x86', 'bitness': '64', 'platformVersion': '10.0.0'}}, 'windows', None),
    ('win-arm', {'ua': WIN_UA, 'platform': 'Windows', 'hints': {'architecture': 'arm', 'bitness': '64', 'platformVersion': '15.0.0'}}, 'windows', False),
    ('win-32bit', {'ua': WIN_UA, 'platform': 'Windows', 'hints': {'architecture': 'x86', 'bitness': '32', 'platformVersion': '10.0.0'}}, 'windows', False),
    ('win-firefox', {'ua': FIREFOX_WIN}, 'windows', None),
    ('linux', {'ua': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36', 'platform': 'Linux'}, 'other', False),
    ('iphone', {'ua': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1', 'touch': 5}, 'other', False),
    ('android', {'ua': 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36', 'platform': 'Android'}, 'other', False),
]


@pytest.mark.parametrize('name,seen,os,fits', CASES, ids=[c[0] for c in CASES])
def test_classify(name, seen, os, fits):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required')
    script = 'global.window = {};\n' + (ROOT / 'assets/site-os.js').read_text()
    script += f'\nconsole.log(JSON.stringify(window.PianpianOS.classify({json.dumps(seen)})));'
    out = json.loads(subprocess.run([node], input=script, check=True, capture_output=True, text=True, timeout=5).stdout)
    assert (out['os'], out['fits']) == (os, fits), out
    if os == 'mac' and fits is None:
        assert 'Apple Silicon' in out['note'] and 'macOS 14' in out['note']    # unknown chip: say what it needs, never that it works
    if name == 'win-arm':
        assert 'ARM' in out['note']
