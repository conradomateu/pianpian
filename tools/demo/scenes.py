"""The demo video's pictures: eight flat scenes with Pianpian, a slice of watermelon, as SVG (1280×720).

    python3 tools/demo/scenes.py out_dir        # writes 1.svg … 8.svg, one per line of script.txt

Drawn here, so the demo has no one else's pictures in it. The bottom of each scene is kept quiet:
that is where the subtitles go.
"""
import math
import sys
from pathlib import Path

W, H = 1280, 720
INK = "#3B2A22"
APPLE = "M12.152 6.896c-.948 0-2.415-1.078-3.96-1.04-2.04.027-3.91 1.183-4.961 3.014-2.117 3.675-.546 9.103 1.519 12.09 1.013 1.454 2.208 3.09 3.792 3.039 1.52-.065 2.09-.987 3.935-.987 1.831 0 2.35.987 3.96.948 1.637-.026 2.676-1.48 3.676-2.948 1.156-1.688 1.636-3.325 1.662-3.415-.039-.013-3.182-1.221-3.22-4.857-.026-3.04 2.48-4.494 2.597-4.559-1.429-2.09-3.623-2.324-4.39-2.376-2-.156-3.675 1.09-4.61 1.09zM15.53 3.83c.843-1.012 1.4-2.427 1.245-3.83-1.207.052-2.662.805-3.532 1.818-.78.896-1.454 2.338-1.273 3.714 1.338.104 2.715-.688 3.559-1.701"   # the Apple logo (24×24), on the Download for Mac button
RED, FLESH, RIND, BAND, PINK = "#DE3B26", "#E9503C", "#0E8A63", "#FBF8F3", "#FF9A88"


def slice_(x, y, s=1.0, flesh=FLESH, arm="down", flip=False, extra="", front=""):
    """Pianpian at (x, y) = the middle of the slice's flat top; feet end about 178·s below it.
    extra is drawn behind him (a backpack), front over him."""
    r = 120
    # five seeds on one arc, evenly spaced and pointing at the centre, well clear of the white band
    seeds = "".join(f'<ellipse cx="{78 * math.sin(math.radians(a)):.1f}" cy="{78 * math.cos(math.radians(a)):.1f}" rx="4.5" ry="7" fill="{INK}" '
                    f'transform="rotate({-a} {78 * math.sin(math.radians(a)):.1f} {78 * math.cos(math.radians(a)):.1f})"/>' for a in (-40, -20, 0, 20, 40))
    arms = {
        "down": '<path d="M-104 34 Q-132 58 -138 86" /><path d="M104 34 Q132 58 138 86" />',
        "wave": '<path d="M-104 34 Q-132 58 -138 86" /><path d="M104 30 Q140 8 150 -40" />'
                '<path d="M168 -66 q10 8 12 22 M182 -40 q12 2 20 12" stroke-width="6" opacity=".55"/>',
        "point": '<path d="M-104 34 Q-132 58 -138 86" /><path d="M106 30 Q146 22 182 6" /><path d="M182 6 l16 -8" stroke-width="7"/>',
        "up": '<path d="M-104 34 Q-132 58 -138 86" /><path d="M104 30 Q130 0 128 -40" />',
        "type": '<path d="M-104 34 Q-130 60 -110 96" /><path d="M104 34 Q140 60 170 70" />',
    }[arm]
    face = (f'<ellipse cx="-30" cy="26" rx="9" ry="11" fill="{INK}"/><ellipse cx="30" cy="26" rx="9" ry="11" fill="{INK}"/>'
            f'<circle cx="-33" cy="22" r="3.2" fill="#fff"/><circle cx="27" cy="22" r="3.2" fill="#fff"/>'
            f'<ellipse cx="-56" cy="38" rx="13" ry="7" fill="{PINK}" opacity=".85"/><ellipse cx="56" cy="38" rx="13" ry="7" fill="{PINK}" opacity=".85"/>'
            f'<path d="M-15 44 Q0 58 15 44" fill="none" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>')
    legs = (f'<path d="M-36 {r - 4} L-40 {r + 46}" /><path d="M36 {r - 4} L40 {r + 46}" />'
            f'<ellipse cx="-48" cy="{r + 50}" rx="17" ry="8" fill="{INK}" stroke="none"/><ellipse cx="48" cy="{r + 50}" rx="17" ry="8" fill="{INK}" stroke="none"/>')
    body = (f'<path d="M{-r} 0 A{r} {r} 0 0 0 {r} 0 Z" fill="{RIND}"/>'
            f'<path d="M{-r + 13} 0 A{r - 13} {r - 13} 0 0 0 {r - 13} 0 Z" fill="{BAND}"/>'
            f'<path d="M{-r + 22} 0 A{r - 22} {r - 22} 0 0 0 {r - 22} 0 Z" fill="{flesh}"/>')
    limbs = f'<g fill="none" stroke="{INK}" stroke-width="9" stroke-linecap="round">{legs}{arms}</g>'
    mirror = ' scale(-1 1)' if flip else ''
    return (f'<g transform="translate({x} {y}) scale({s}){mirror}">'
            f'<ellipse cx="0" cy="{r + 54}" rx="96" ry="12" fill="#000" opacity=".10"/>{extra}{limbs}{body}{seeds}{face}{front}</g>')


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
    """A baozi: a round bun gathered into a little knot on top, with pleats curling down from it."""
    pleats = "".join(f'<path d="M{dx * .25:.0f} -50 Q{dx * .9:.0f} -40 {dx:.0f} -24" fill="none" stroke="#DDBF95" stroke-width="3.5" stroke-linecap="round"/>'
                     for dx in (-34, -17, 0, 17, 34))
    return (f'<g transform="translate({x} {y}) scale({s})">'
            '<path d="M-56 0 C-60 -28 -38 -50 -10 -54 Q0 -60 10 -54 C38 -50 60 -28 56 0 Q0 8 -56 0 Z" fill="#FFF4E2"/>'
            '<path d="M-56 0 C-58 -12 -54 -20 -48 -26 C-44 -6 44 -6 48 -26 C54 -20 58 -12 56 0 Q0 8 -56 0 Z" fill="#F3DFC0"/>'
            f'{pleats}<path d="M-8 -54 Q0 -64 8 -54 Q0 -50 -8 -54 Z" fill="#E8CFA8"/></g>')


def steamer(x, y):
    """A round bamboo steamer (蒸笼), open, three buns inside: its back rim, the buns, then its front."""
    slats = "".join(f'<path d="M{dx} 4 V54" stroke="#B98A55" stroke-width="3" opacity=".55"/>' for dx in range(-150, 151, 30))
    return (f'<g transform="translate({x} {y})">'
            '<ellipse cx="0" cy="0" rx="176" ry="30" fill="#C99A62"/><ellipse cx="0" cy="2" rx="160" ry="22" fill="#A97B47"/>'
            f'{bun(-80, 10, .95)}{bun(80, 10, .95)}{bun(0, 2, 1.05)}'
            '<path d="M-176 0 A176 30 0 0 0 176 0 V44 A176 30 0 0 1 -176 44 Z" fill="#D9AE74"/>'
            f'{slats}<path d="M-176 0 A176 30 0 0 0 176 0" fill="none" stroke="#C4945C" stroke-width="7"/>'
            '<path d="M-176 26 A176 30 0 0 0 176 26" fill="none" stroke="#C4945C" stroke-width="5"/></g>')


def scene_baozi():
    steam = "".join(f'<path d="M{x} 286 q-14 -24 0 -48 t0 -48" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity=".8"/>' for x in (790, 860, 930))
    body = ('<rect x="0" y="0" width="1280" height="440" fill="#F6E3CC"/>'
            '<rect x="930" y="70" width="230" height="190" rx="14" fill="#CFE7F3" stroke="#E9CDAE" stroke-width="12"/><path d="M1045 70 V260 M930 165 H1160" stroke="#E9CDAE" stroke-width="10"/>'
            '<rect x="0" y="430" width="1280" height="290" fill="#E9CBA7"/>'
            '<rect x="560" y="420" width="640" height="36" rx="10" fill="#C98B5A"/><rect x="600" y="456" width="26" height="200" fill="#B27749"/><rect x="1134" y="456" width="26" height="200" fill="#B27749"/>'
            f'{steamer(860, 352)}{steam}'
            f'{slice_(330, 300, 1.0, arm="point")}')
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
            f'{slice_(880, 360, .9, arm="up")}')
    return svg(body, sky("#FFD9BF", "#FFF2E6"))





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


def scene_get_app():
    """The last line invites you to download: the name, what it does, and a Download button (drawn, not a link)."""
    font = "font-family:'Avenir Next','Helvetica Neue','PingFang SC',sans-serif"
    body = (f'<circle cx="330" cy="300" r="210" fill="{PINK}" opacity=".22"/>'
            f'{slice_(330, 230, 1.15, arm="wave")}'
            f'<text x="600" y="210" style="{font};font-weight:800;font-size:76px" fill="{INK}">Pianpian <tspan fill="{RED}">片片</tspan></text>'
            f'<text x="604" y="262" style="{font};font-weight:500;font-size:30px" fill="#6B5A4E">Learn Mandarin from real videos</text>'
            f'<g transform="translate(604 304)"><rect width="420" height="84" rx="22" fill="{RED}"/>'
            f'<g transform="translate(26 17) scale(2)"><path fill="#fff" d="{APPLE}"/></g>'
            f'<text x="84" y="55" style="{font};font-weight:700;font-size:32px" fill="#fff">Download for Mac</text></g>'
            f'<text x="606" y="436" style="{font};font-weight:500;font-size:22px" fill="#8A7F74">Free · open source · Apple Silicon</text>')
    return svg(body, '<radialGradient id="bg" cx=".3" cy=".42" r=".9"><stop offset="0" stop-color="#FFF7EE"/><stop offset="1" stop-color="#F5E4D2"/></radialGradient>')


SCENES = [scene_hello, scene_park, scene_baozi, scene_china, scene_study, scene_cook, scene_rain, scene_get_app]

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for i, make in enumerate(SCENES, 1):
        (out / f"{i}.svg").write_text(make(), encoding="utf-8")
