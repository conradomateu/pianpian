"""Shared player/Anki tone segments retain literal text and conservative alignment."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('pinyin,expression,expected_pinyin,expected_expression', [
    ('mā má mǎ mà ma', '妈麻马骂吗', [['mā', 1], [' ', 0], ['má', 2], [' ', 0], ['mǎ', 3], [' ', 0], ['mà', 4], [' ', 0], ['ma', 5]],
     [['妈', 1], ['麻', 2], ['马', 3], ['骂', 4], ['吗', 5]]),
    # Synthetic source pairing checks count preference, not pronunciation correction.
    ('piāo', '皮袄', [['pi', 5], ['āo', 1]], [['皮', 5], ['袄', 1]]),
    ('píǎo', '皮袄', [['pí', 2], ['ǎo', 3]], [['皮', 2], ['袄', 3]]),
    ("xī'ān,  nǐ-hǎo!\n", '西安，你好！', [["xī", 1], ["'", 0], ['ān', 1], [',  ', 0], ['nǐ', 3], ['-', 0], ['hǎo', 3], ['!\n', 0]],
     [['西', 1], ['安', 1], ['，', 0], ['你', 3], ['好', 3], ['！', 0]]),
    ('yìdiǎnr huār', '一点儿花儿', [['yì', 4], ['diǎn', 3], ['r', 5], [' ', 0], ['huā', 1], ['r', 5]],
     [['一', 4], ['点', 3], ['儿', 5], ['花', 1], ['儿', 5]]),
    ('nu\u0308\u030c', '女', [['nu\u0308\u030c', 3]], [['女', 3]]),
    ('LǙ', '吕', [['LǙ', 3]], [['吕', 3]]),
    ('chángān', '长安', [['cháng', 2], ['ān', 1]], [['长安', 0]]),
    ('nǐhǎo', '你', [['nǐ', 3], ['hǎo', 3]], [['你', 0]]),
    ('ma ma', '', [['ma ma', 0]], []),
    ('hello <img src=x>', '你好', [['hello <img src=x>', 0]], [['你好', 0]]),
    ('', '你', [], [['你', 0]]),
    pytest.param('ā' * 513, '', [['ā' * 513, 0]], [], id='over-parser-bound'),
    pytest.param('nǐ hǎo! ' * 2500, '你好！' * 2500,
                 [['nǐ hǎo! ' * 2500, 0]], [['你好！' * 2500, 0]], id='20k-pasted-paired'),
    pytest.param('nǐ hǎo! ' * 2500, '', [['nǐ hǎo! ' * 2500, 0]], [], id='20k-pasted-unpaired'),
])
def test_tone_segments(pinyin, expression, expected_pinyin, expected_expression):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for shared JavaScript helper')
    root = Path(__file__).resolve().parents[1]
    script = 'global.window = {};\n' + (root / 'assets/player.js').read_text(encoding='utf-8')
    script += f'\nconsole.log(JSON.stringify(window.SubPlayer.toneSegments({json.dumps(pinyin)}, {json.dumps(expression)})));'
    result = subprocess.run([node], input=script, check=True, capture_output=True, text=True, encoding='utf-8', timeout=5)
    segments = json.loads(result.stdout)
    assert segments == {'pinyin': expected_pinyin, 'expression': expected_expression}
    for key, text in [('pinyin', pinyin), ('expression', expression)]:
        assert ''.join(part for part, _ in segments[key]) == text
        assert all(type(tone) is int and 0 <= tone <= 5 for _, tone in segments[key])
