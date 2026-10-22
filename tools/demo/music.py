"""The demo's background music, composed here: short playful loops in the Chinese pentatonic scale.

    python3 tools/demo/music.py out.wav SECONDS [STYLE]      # STYLE: bouncy (default), dizi, sneaky, festival, calm

Each style is a tempo, a chord loop, a lead instrument and a few percussion parts. The melody is one
short motif, repeated and answered, which is what makes a tune feel playful rather than random.
Instruments are synthesised: a plucked string close to a guzheng (Karplus-Strong), a bamboo flute
(dizi: sine with breath, vibrato and slides), a wooden fish (木鱼), a small bell and cymbal. Fixed
seed: the same file every time. Standard library only, so nobody else's music is in the demo.
"""
import array
import math
import random
import sys
import wave

SR = 32000
MAJOR = [60, 62, 64, 67, 69, 72, 74, 76, 79, 81]                 # C D E G A: gong mode, bright
MINOR = [57, 60, 62, 64, 67, 69, 72, 74, 76, 79]                 # A C D E G: yu mode, a little sly
STYLES = {
    #            bpm  chords (bass root, chord tones)                                       scale  lead     notes  drums
    "calm":     (100, [(48, (60, 64, 67)), (45, (57, 60, 64)), (41, (57, 60, 65)), (43, (59, 62, 67))], MAJOR, "pluck", 0.30, "kick shaker"),
    "bouncy":   (118, [(48, (60, 64, 67)), (43, (59, 62, 67)), (45, (57, 60, 64)), (43, (59, 62, 67))], MAJOR, "stacc", 0.62, "muyu boing"),
    "dizi":     (104, [(48, (60, 64, 67)), (41, (57, 60, 65)), (45, (57, 60, 64)), (43, (59, 62, 67))], MAJOR, "dizi", 0.50, "muyu bell"),
    "sneaky":   (96, [(45, (57, 60, 64)), (45, (57, 60, 64)), (41, (57, 60, 65)), (40, (59, 64, 67))], MINOR, "stacc", 0.45, "tiptoe slide"),
    "festival": (132, [(48, (60, 64, 67)), (48, (60, 64, 67)), (45, (57, 60, 64)), (43, (59, 62, 67))], MAJOR, "stacc", 0.70, "muyu cymbal kick"),
}


def hz(midi: float) -> float:
    return 440 * 2 ** ((midi - 69) / 12)


def add(buf, start: float, samples) -> None:
    i = int(start * SR)
    for k, s in enumerate(samples):
        if 0 <= i + k < len(buf):
            buf[i + k] += s


def pluck(midi, length, gain, rng, damp=0.497):
    """Karplus-Strong: noise in a delay line, averaged: a plucked string. Lower damp = shorter note."""
    n = max(2, int(SR / hz(midi)))
    line = [rng.uniform(-1, 1) for _ in range(n)]
    out, j = [], 0
    for _ in range(int(length * SR)):
        a, b = line[j], line[(j + 1) % n]
        line[j] = damp * (a + b)
        out.append(a * gain)
        j = (j + 1) % n
    return out


def dizi(midi, length, gain, rng, slide_from=None):
    """A bamboo flute: a sine and a soft second harmonic, breath noise, vibrato that grows, a slide into the note."""
    out, phase, f0 = [], 0.0, hz(midi)
    start = hz(slide_from) if slide_from else f0
    for k in range(int(length * SR)):
        t = k / SR
        f = f0 + (start - f0) * math.exp(-t * 28) + f0 * 0.012 * min(1, t * 3) * math.sin(2 * math.pi * 5.6 * t)
        phase += 2 * math.pi * f / SR
        env = min(1, t * 25) * min(1, (length - t) * 12)
        out.append(gain * env * (math.sin(phase) + 0.18 * math.sin(2 * phase) + 0.04 * rng.uniform(-1, 1)))
    return out


def bass(midi, length, gain, boing=False):
    out, phase, f0 = [], 0.0, hz(midi)
    for k in range(int(length * SR)):
        t = k / SR
        f = f0 * (1 + (0.5 * math.exp(-t * 18) if boing else 0))     # boing: starts a fifth high and drops
        phase += 2 * math.pi * f / SR
        out.append(gain * math.exp(-(6 if boing else 2.2) * t) * (math.sin(phase) + 0.25 * math.sin(2 * phase)) * min(1, t * 80))
    return out


def tone(freqs, length, gain, decay):
    """A struck thing: a few partials dying away (wooden fish, bell)."""
    return [gain * sum(a * math.sin(2 * math.pi * f * t) * math.exp(-t * decay * (1 + i * 0.6)) for i, (f, a) in enumerate(freqs))
            for t in (k / SR for k in range(int(length * SR)))]


def noise(length, gain, decay, rng, bright=True):
    out, last = [], 0.0
    for k in range(int(length * SR)):
        x = rng.uniform(-1, 1)
        out.append(gain * math.exp(-k / SR * decay) * ((x - last) if bright else x))
        last = x
    return out


def kick(gain):
    out, phase = [], 0.0
    for k in range(int(0.16 * SR)):
        t = k / SR
        phase += 2 * math.pi * (50 + 90 * math.exp(-t * 30)) / SR
        out.append(gain * math.exp(-t * 22) * math.sin(phase))
    return out


def motif(rng, density):
    """One bar: (eighth, steps up or down the scale) pairs; repeated and answered, it becomes the tune."""
    beats, step = [], 0
    for e in range(8):
        if e == 0 or rng.random() < density:
            step = max(-3, min(3, step + rng.choice((-2, -1, 1, 1, 2))))
            beats.append((e, step))
    return beats


def compose(seconds: float, style: str = "bouncy"):
    bpm, chords, scale, lead, density, drums = STYLES[style]
    beat = 60 / bpm
    bar = 4 * beat
    rng = random.Random({"calm": 7, "bouncy": 11, "dizi": 23, "sneaky": 5, "festival": 3}[style])
    buf = array.array("f", [0.0]) * int((seconds + 4) * SR)
    call, answer = motif(rng, density), motif(rng, density)
    bars = int(seconds // bar)
    for b in range(bars):
        root, triad = chords[b % len(chords)]
        t0 = b * bar
        boing = "boing" in drums
        if "tiptoe" in drums:                               # bass on each beat, short: tiptoeing
            for q in range(4):
                add(buf, t0 + q * beat, bass(root + (7 if q % 2 else 0), beat * 0.5, 0.30, boing=False))
        else:
            add(buf, t0, bass(root, beat * 2, 0.32, boing))
            add(buf, t0 + 2 * beat, bass(root + (7 if boing else 0), beat * 2, 0.26, boing))
        if b > 0:                                           # the first bar is a soft start: bass and tune only
            for q in range(4):
                if "kick" in drums and q % 2 == 0:
                    add(buf, t0 + q * beat, kick(0.26))
                if "muyu" in drums and q % 2 == 1:          # the wooden fish on the off-beats, two pitches
                    f = 820 if (b + q) % 4 == 1 else 680
                    add(buf, t0 + q * beat, tone([(f, 1), (f * 2.7, 0.3)], 0.12, 0.30, 45))
                if "shaker" in drums:
                    add(buf, t0 + q * beat + beat / 2, noise(0.05, 0.05, 70, rng))
                if "cymbal" in drums and q == 0 and b % 2 == 0:
                    add(buf, t0, noise(0.5, 0.06, 7, rng))
        # the tune: the call twice, then the answer, then the call again, moved onto each chord
        phrase = answer if b % 4 == 2 else call
        anchor = min(scale, key=lambda p: abs(p - (triad[0] + 12)))
        prev = None
        for e, step in phrase:
            idx = max(0, min(len(scale) - 1, scale.index(anchor) + step))
            note = scale[idx]
            at = t0 + e * beat / 2
            if lead == "dizi":
                add(buf, at, dizi(note, beat * 0.9, 0.22, rng, slide_from=(note - 2) if prev is None or rng.random() < 0.3 else None))
            elif lead == "stacc":
                add(buf, at, pluck(note, beat * 0.45, 0.32, rng, damp=0.488))
            else:
                add(buf, at, pluck(note, beat * 1.5, 0.30, rng))
            prev = note
        if b % 4 == 3:                                      # the end of each four-bar phrase gets a little flourish
            if "bell" in drums:
                add(buf, t0 + 3.5 * beat, tone([(hz(84), 1), (hz(84) * 2.76, 0.4), (hz(84) * 5.4, 0.2)], 1.2, 0.12, 4))
            if "slide" in drums:
                add(buf, t0 + 3.5 * beat, dizi(scale[2], beat * 0.5, 0.16, rng, slide_from=scale[2] + 7))
            if "boing" in drums:
                add(buf, t0 + 3.5 * beat, bass(root + 12, beat * 0.5, 0.18, boing=True))
    end = bars * bar                                        # a last chord, rung out
    add(buf, end, bass(chords[0][0], 2.5, 0.32))
    for i, note in enumerate(chords[0][1] + (chords[0][1][0] + 12,)):
        add(buf, end + i * 0.06, pluck(note, 2.8, 0.26, rng))
    if "muyu" in drums:
        add(buf, end, tone([(820, 1), (2214, 0.3)], 0.15, 0.3, 45))
    peak = max(abs(s) for s in buf) or 1.0
    return [s / peak * 0.9 for s in buf[:int((end + 2.8) * SR)]]


def main():
    out, seconds = sys.argv[1], float(sys.argv[2])
    samples = compose(seconds, sys.argv[3] if len(sys.argv) > 3 else "bouncy")
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(array.array("h", (int(s * 32767) for s in samples)).tobytes())


if __name__ == "__main__":
    main()
