"""The demo video's pictures: seven flat scenes with Pianpian, a slice of watermelon, as SVG (1280×720).

    python3 tools/demo/scenes.py out_dir        # writes 1.svg … 7.svg, one per line of script.txt

Drawn here, so the demo has no one else's pictures in it. The bottom of each scene is kept quiet:
that is where the subtitles go.
"""
import sys
from pathlib import Path

W, H = 1280, 720
INK = "#3B2A22"
RED, FLESH, RIND, BAND, PINK = "#DE3B26", "#E9503C", "#0E8A63", "#FBF8F3", "#FF9A88"


def slice_(x, y, s=1.0, flesh=FLESH, arm="down", flip=False, extra=""):
    """Pianpian at (x, y) = the middle of the slice's flat top; feet end about 178·s below it."""
    r = 120
    seeds = "".join(f'<ellipse cx="{sx}" cy="{sy}" rx="5" ry="8" fill="{INK}" transform="rotate({a} {sx} {sy})"/>'
                    for sx, sy, a in ((-62, 58, 30), (-30, 80, 12), (30, 80, -12), (62, 58, -30), (0, 92, 0)))
    arms = {
        "down": '<path d="M-104 34 Q-132 58 -138 86" /><path d="M104 34 Q132 58 138 86" />',
        "wave": '<path d="M-104 34 Q-132 58 -138 86" /><path d="M104 30 Q140 8 150 -40" />'
                '<path d="M168 -66 q10 8 12 22 M182 -40 q12 2 20 12" stroke-width="6" opacity=".55"/>',
        "belly": '<path d="M-104 34 Q-120 70 -60 70" /><path d="M104 34 Q132 58 138 86" />',
        "up": '<path d="M-104 34 Q-132 58 -138 86" /><path d="M104 30 Q130 0 128 -40" />',
        "type": '<path d="M-104 34 Q-130 60 -110 96" /><path d="M104 34 Q140 60 170 70" />',
    }[arm]
    face = (f'<ellipse cx="-30" cy="26" rx="9" ry="11" fill="{INK}"/><ellipse cx="30" cy="26" rx="9" ry="11" fill="{INK}"/>'
            f'<circle cx="-33" cy="22" r="3.2" fill="#fff"/><circle cx="27" cy="22" r="3.2" fill="#fff"/>'
            f'<ellipse cx="-56" cy="44" rx="13" ry="7" fill="{PINK}" opacity=".85"/><ellipse cx="56" cy="44" rx="13" ry="7" fill="{PINK}" opacity=".85"/>'
            f'<path d="M-15 44 Q0 58 15 44" fill="none" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>')
    legs = (f'<path d="M-36 {r - 4} L-40 {r + 46}" /><path d="M36 {r - 4} L40 {r + 46}" />'
            f'<ellipse cx="-48" cy="{r + 50}" rx="17" ry="8" fill="{INK}" stroke="none"/><ellipse cx="48" cy="{r + 50}" rx="17" ry="8" fill="{INK}" stroke="none"/>')
    body = (f'<path d="M{-r} 0 A{r} {r} 0 0 0 {r} 0 Z" fill="{RIND}"/>'
            f'<path d="M{-r + 13} 0 A{r - 13} {r - 13} 0 0 0 {r - 13} 0 Z" fill="{BAND}"/>'
            f'<path d="M{-r + 22} 0 A{r - 22} {r - 22} 0 0 0 {r - 22} 0 Z" fill="{flesh}"/>'
            f'<rect x="{-r}" y="-5" width="{2 * r}" height="10" rx="5" fill="{flesh}"/>')
    limbs = f'<g fill="none" stroke="{INK}" stroke-width="9" stroke-linecap="round">{legs}{arms}</g>'
    mirror = ' scale(-1 1)' if flip else ''
    return (f'<g transform="translate({x} {y}) scale({s}){mirror}">'
            f'<ellipse cx="0" cy="{r + 54}" rx="96" ry="12" fill="#000" opacity=".10"/>{extra}{limbs}{body}{seeds}{face}</g>')


def svg(body, bg):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'<defs>{bg}</defs><rect width="{W}" height="{H}" fill="url(#bg)"/>{body}</svg>')


def sky(top, bottom):
    return f'<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>'


def cloud(x, y, s=1.0, fill="#fff", o=1.0):
    return (f'<g transform="translate({x} {y}) scale({s})" fill="{fill}" opacity="{o}">'
            '<ellipse cx="0" cy="0" rx="70" ry="32"/><circle cx="-30" cy="-18" r="34"/><circle cx="24" cy="-26" r="42"/><circle cx="62" cy="-4" r="28"/></g>')


def tree(x, y, s=1.0):
    return (f'<g transform="translate({x} {y}) scale({s})"><rect x="-10" y="-20" width="20" height="90" rx="8" fill="#9A6B4C"/>'
            '<circle cx="0" cy="-70" r="64" fill="#3FA05E"/><circle cx="-38" cy="-40" r="42" fill="#47AD66"/><circle cx="40" cy="-44" r="44" fill="#379554"/></g>')


def scene_hello():
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}" opacity=".55"/>' for x, y, r, c in (
        (180, 140, 14, PINK), (1090, 170, 18, "#7FCBA5"), (240, 520, 10, "#7FCBA5"), (1040, 500, 12, PINK),
        (380, 90, 8, RED), (900, 90, 9, RIND), (140, 330, 7, RIND), (1150, 340, 8, RED)))
    body = (f'<circle cx="640" cy="330" r="250" fill="{PINK}" opacity=".22"/><circle cx="640" cy="330" r="180" fill="{PINK}" opacity=".22"/>'
            f'{dots}{slice_(640, 250, 1.45, arm="wave")}')
    return svg(body, '<radialGradient id="bg" cx=".5" cy=".42" r=".8"><stop offset="0" stop-color="#FFF7EE"/><stop offset="1" stop-color="#F5E4D2"/></radialGradient>')


def scene_park():
    rays = "".join(f'<rect x="-6" y="-118" width="12" height="34" rx="6" fill="#FFC94D" transform="rotate({a})"/>' for a in range(0, 360, 30))
    body = (f'<g transform="translate(1080 140)">{rays}<circle r="70" fill="#FFD36E"/></g>'
            f'{cloud(260, 130, 1.0)}{cloud(700, 90, .8, o=.9)}'
            '<path d="M0 470 Q260 360 560 440 T1280 410 V720 H0 Z" fill="#A8D8AE"/>'
            '<path d="M0 560 Q320 470 700 540 T1280 520 V720 H0 Z" fill="#74C083"/>'
            '<path d="M560 720 Q620 600 820 560 T1280 540 V600 Q980 610 880 640 T760 720 Z" fill="#E8CFA4"/>'
            f'{tree(1010, 470, .9)}{tree(160, 500, 1.1)}{tree(1180, 500, .7)}'
            f'{slice_(470, 330, 1.0, arm="up")}')
    return svg(body, sky("#BFE3F5", "#F1F9FC"))


def bun(x, y, s=1.0):
    pleats = "".join(f'<path d="M0 -44 Q{dx} -20 {dx * 1.6} 0" fill="none" stroke="#D4B48C" stroke-width="4" stroke-linecap="round"/>' for dx in (-26, -12, 12, 26))
    return (f'<g transform="translate({x} {y}) scale({s})"><path d="M-62 0 Q-60 -58 0 -60 Q60 -58 62 0 Z" fill="#FBE9CF" stroke="#DCC09B" stroke-width="4"/>'
            f'{pleats}<circle cx="0" cy="-50" r="7" fill="#E6CBA6"/></g>')


def scene_baozi():
    steam = "".join(f'<path d="M{x} 300 q-14 -24 0 -48 t0 -48" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity=".8"/>' for x in (780, 850, 920))
    body = ('<rect x="0" y="0" width="1280" height="440" fill="#F6E3CC"/>'
            '<rect x="930" y="70" width="230" height="190" rx="14" fill="#CFE7F3" stroke="#E9CDAE" stroke-width="12"/><path d="M1045 70 V260 M930 165 H1160" stroke="#E9CDAE" stroke-width="10"/>'
            '<rect x="0" y="430" width="1280" height="290" fill="#E9CBA7"/>'
            '<rect x="560" y="420" width="640" height="36" rx="10" fill="#C98B5A"/><rect x="600" y="456" width="26" height="200" fill="#B27749"/><rect x="1134" y="456" width="26" height="200" fill="#B27749"/>'
            '<ellipse cx="850" cy="412" rx="190" ry="26" fill="#fff"/><ellipse cx="850" cy="408" rx="150" ry="16" fill="#F3EEE5"/>'
            f'{bun(760, 404)}{bun(940, 404)}{bun(850, 380, 1.05)}{steam}'
            f'{slice_(330, 300, 1.0, arm="belly")}')
    return svg(body, sky("#F6E3CC", "#F6E3CC"))


def scene_china():
    wall = "".join(f'<rect x="{x}" y="{y - 22}" width="20" height="22" fill="#B5664E"/>' for x, y in
                   ((120, 392), (200, 372), (280, 350), (360, 334), (440, 330), (520, 338), (600, 352), (680, 368), (760, 362), (840, 344), (920, 326), (1000, 318), (1080, 330), (1160, 352)))
    towers = "".join(f'<rect x="{x}" y="{y}" width="56" height="64" fill="#A65A44"/><rect x="{x + 18}" y="{y + 26}" width="20" height="38" rx="10" fill="#7E4232"/>' for x, y in ((404, 270), (968, 256)))
    trail = "".join(f'<circle cx="{x}" cy="{y}" r="5" fill="#fff" opacity=".9"/>' for x, y in ((180, 180), (230, 160), (284, 146), (340, 136), (398, 132), (456, 134)))
    body = ('<circle cx="640" cy="300" r="120" fill="#FFD0A8" opacity=".9"/>'
            '<path d="M0 360 L180 250 L330 330 L500 220 L700 330 L880 230 L1060 320 L1280 240 V720 H0 Z" fill="#EBB79E"/>'
            '<path d="M0 420 Q120 380 200 388 T360 350 T520 344 T680 380 T840 356 T1000 334 T1160 368 T1280 380 V720 H0 Z" fill="#D7957C"/>'
            '<path d="M0 404 Q120 364 200 372 T360 334 T520 328 T680 364 T840 340 T1000 318 T1160 352 T1280 364" fill="none" stroke="#B5664E" stroke-width="20"/>'
            f'{wall}{towers}<path d="M0 520 Q400 470 800 520 T1280 500 V720 H0 Z" fill="#C7826A"/>'
            f'{trail}<g transform="translate(540 120) rotate(-8)"><path d="M-60 0 L60 0 Q78 0 78 8 Q78 16 60 16 L-60 16 Z" fill="#fff"/>'
            '<path d="M-6 6 L-40 -34 L-22 -34 L22 6 Z M-6 10 L-40 50 L-22 50 L22 10 Z M-58 4 L-74 -20 L-62 -20 L-44 4 Z" fill="#fff"/></g>'
            f'{slice_(880, 360, .9, arm="up", extra=_backpack())}')
    return svg(body, sky("#FFD9BF", "#FFF2E6"))


def _backpack():
    return '<rect x="-150" y="-10" width="70" height="96" rx="20" fill="#3E7CB1"/><rect x="-140" y="34" width="50" height="30" rx="8" fill="#2F6595"/>'


def scene_study():
    bars = (f'<rect x="760" y="300" width="300" height="168" rx="10" fill="#1C1916"/><path d="M890 352 L890 400 L932 376 Z" fill="{RED}"/>'
            f'<rect x="800" y="420" width="130" height="10" rx="5" fill="{PINK}"/><rect x="940" y="420" width="80" height="10" rx="5" fill="#7FCBA5"/>'
            '<rect x="830" y="440" width="160" height="8" rx="4" fill="#F2EDE4" opacity=".8"/>')
    books = "".join(f'<rect x="{x}" y="{y}" width="{w}" height="26" rx="5" fill="{c}"/>' for x, y, w, c in
                    ((1100, 446, 120, RIND), (1090, 420, 136, "#E9A23B"), (1106, 394, 110, RED)))
    body = ('<rect x="0" y="0" width="1280" height="500" fill="#EAF0F6"/>'
            '<rect x="120" y="70" width="300" height="230" rx="16" fill="#CFE7F3" stroke="#D9E2EA" stroke-width="14"/>'
            f'{cloud(240, 190, .55)}<path d="M270 70 V300" stroke="#D9E2EA" stroke-width="10"/>'
            '<rect x="0" y="490" width="1280" height="230" fill="#DCCFC0"/>'
            '<rect x="620" y="480" width="640" height="34" rx="10" fill="#D9A273"/><rect x="650" y="514" width="24" height="200" fill="#C08A5C"/><rect x="1210" y="514" width="24" height="200" fill="#C08A5C"/>'
            f'<path d="M740 480 L1080 480 L1100 470 L720 470 Z" fill="#B9B3AC"/>{bars}{books}'
            f'{slice_(440, 312, 1.0, arm="type")}')
    return svg(body, sky("#EAF0F6", "#EAF0F6"))


def scene_cook():
    steam = "".join(f'<path d="M{x} 320 q-14 -24 0 -48 t0 -48" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round" opacity=".85"/>' for x in (600, 660, 720))
    body = ('<rect x="0" y="0" width="1280" height="460" fill="#FFF0DE"/>'
            '<rect x="80" y="60" width="220" height="180" rx="14" fill="#CFE7F3" stroke="#F0D2AE" stroke-width="12"/>'
            '<rect x="120" y="200" width="60" height="40" rx="8" fill="#C98B5A"/><circle cx="150" cy="186" r="26" fill="#3FA05E"/>'
            '<rect x="0" y="450" width="1280" height="270" fill="#F0D9BE"/>'
            '<rect x="420" y="430" width="440" height="40" rx="10" fill="#E3B07F"/><rect x="440" y="470" width="400" height="250" fill="#D49C6A"/>'
            '<rect x="560" y="404" width="200" height="30" rx="8" fill="#5A4A40"/>'
            '<path d="M530 340 H790 L770 430 H550 Z" fill="#4A3B33"/><rect x="520" y="330" width="280" height="22" rx="11" fill="#5C4B41"/>'
            f'<rect x="498" y="336" width="34" height="12" rx="6" fill="#5C4B41"/><rect x="788" y="336" width="34" height="12" rx="6" fill="#5C4B41"/>{steam}'
            f'{slice_(260, 330, 1.0, arm="up")}{slice_(1030, 360, .82, flesh="#F4C246", arm="wave", flip=True)}')
    return svg(body, sky("#FFF0DE", "#FFF0DE"))


def scene_rain():
    drops = "".join(f'<path d="M{x} {y} l-10 26" stroke="#EEF3F8" stroke-width="4" stroke-linecap="round" opacity=".75"/>'
                    for x in range(40, 1280, 70) for y in (190 + (x * 7) % 90, 350 + (x * 11) % 110))
    umbrella = (f'<g><path d="M0 -40 V60" stroke="{INK}" stroke-width="8" stroke-linecap="round"/>'
                f'<path d="M-150 -40 Q-150 -170 0 -170 Q150 -170 150 -40 Q125 -62 100 -40 Q75 -62 50 -40 Q25 -62 0 -40 Q-25 -62 -50 -40 Q-75 -62 -100 -40 Q-125 -62 -150 -40 Z" fill="{RED}"/>'
                f'<path d="M0 -170 Q-40 -110 -50 -40 M0 -170 Q40 -110 50 -40" fill="none" stroke="#B32A18" stroke-width="5"/></g>')
    body = (f'{cloud(220, 120, 1.6, "#6F7C8A")}{cloud(640, 90, 1.9, "#7B8896")}{cloud(1060, 130, 1.5, "#6F7C8A")}'
            '<path d="M0 500 Q400 460 800 500 T1280 480 V720 H0 Z" fill="#7E9A86"/>'
            '<ellipse cx="420" cy="600" rx="120" ry="14" fill="#AFC1CF" opacity=".7"/><ellipse cx="900" cy="640" rx="90" ry="10" fill="#AFC1CF" opacity=".7"/>'
            '<rect x="900" y="300" width="260" height="210" fill="#E9D5BF"/><path d="M880 310 L1030 200 L1180 310 Z" fill="#B5664E"/>'
            '<rect x="940" y="360" width="70" height="60" rx="6" fill="#FFD38A"/><rect x="1060" y="400" width="60" height="110" rx="8" fill="#8A5A3C"/>'
            f'{drops}{slice_(560, 340, .95, arm="up", extra=umbrella.replace("<g>", "<g transform=\"translate(128 -30)\">"))}')
    return svg(body, sky("#93A1B0", "#C8D1DA"))


SCENES = [scene_hello, scene_park, scene_baozi, scene_china, scene_study, scene_cook, scene_rain]

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for i, make in enumerate(SCENES, 1):
        (out / f"{i}.svg").write_text(make(), encoding="utf-8")
