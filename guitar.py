"""Аккорды для гитары: названия, тональность, каподастр и аппликатуры.

Метки — как у lv-chordia: «C:maj», «F#:min7», «D:sus4(b7)», «E:maj/3»; «N» — тишина.
Аппликатуры — лады от 6-й струны к 1-й, -1 — струна не звучит.
"""
import numpy as np

SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
RU_SHARP = ["До", "До-диез", "Ре", "Ре-диез", "Ми", "Фа", "Фа-диез", "Соль", "Соль-диез",
            "Ля", "Ля-диез", "Си"]
RU_FLAT = ["До", "Ре-бемоль", "Ре", "Ми-бемоль", "Ми", "Фа", "Соль-бемоль", "Соль",
           "Ля-бемоль", "Ля", "Си-бемоль", "Си"]
LETTER = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# Ступень баса в обращениях: «/3» — терция в басу.
DEGREES = {"2": 2, "b3": 3, "3": 4, "4": 5, "5": 7, "b7": 10, "7": 11}

# Качество → суффикс названия, звуки от корня, вид аппликатуры.
QUALITIES = {
    "maj": ("", (0, 4, 7), "maj"),
    "min": ("m", (0, 3, 7), "min"),
    "7": ("7", (0, 4, 7, 10), "7"),
    "maj7": ("maj7", (0, 4, 7, 11), "maj7"),
    "min7": ("m7", (0, 3, 7, 10), "min7"),
    "dim": ("dim", (0, 3, 6), "dim"),
    "dim7": ("dim7", (0, 3, 6, 9), "dim7"),
    "hdim7": ("m7b5", (0, 3, 6, 10), "hdim7"),
    "aug": ("aug", (0, 4, 8), "aug"),
    "sus2": ("sus2", (0, 2, 7), "sus2"),
    "sus4": ("sus4", (0, 5, 7), "sus4"),
    "sus4(b7)": ("7sus4", (0, 5, 7, 10), "7sus4"),
    "maj6": ("6", (0, 4, 7, 9), "6"),
    "min6": ("m6", (0, 3, 7, 9), "m6"),
    "9": ("9", (0, 4, 7, 10, 2), "9"),
    "maj9": ("maj9", (0, 4, 7, 11, 2), "maj7"),
    "min9": ("m9", (0, 3, 7, 10, 2), "min7"),
    "11": ("11", (0, 4, 7, 10, 5), "7"),
    "13": ("13", (0, 4, 7, 10, 9), "7"),
}

# Открытые аккорды — без баррэ, их берут первыми.
OPEN = {
    (0, "maj"): (-1, 3, 2, 0, 1, 0), (2, "maj"): (-1, -1, 0, 2, 3, 2),
    (4, "maj"): (0, 2, 2, 1, 0, 0), (7, "maj"): (3, 2, 0, 0, 0, 3),
    (9, "maj"): (-1, 0, 2, 2, 2, 0),
    (2, "min"): (-1, -1, 0, 2, 3, 1), (4, "min"): (0, 2, 2, 0, 0, 0),
    (9, "min"): (-1, 0, 2, 2, 1, 0),
    (0, "7"): (-1, 3, 2, 3, 1, 0), (2, "7"): (-1, -1, 0, 2, 1, 2),
    (4, "7"): (0, 2, 0, 1, 0, 0), (7, "7"): (3, 2, 0, 0, 0, 1),
    (9, "7"): (-1, 0, 2, 0, 2, 0), (11, "7"): (-1, 2, 1, 2, 0, 2),
    (0, "maj7"): (-1, 3, 2, 0, 0, 0), (2, "maj7"): (-1, -1, 0, 2, 2, 2),
    (4, "maj7"): (0, 2, 1, 1, 0, 0), (5, "maj7"): (-1, -1, 3, 2, 1, 0),
    (7, "maj7"): (3, 2, 0, 0, 0, 2), (9, "maj7"): (-1, 0, 2, 1, 2, 0),
    (2, "min7"): (-1, -1, 0, 2, 1, 1), (4, "min7"): (0, 2, 0, 0, 0, 0),
    (9, "min7"): (-1, 0, 2, 0, 1, 0),
    (2, "sus4"): (-1, -1, 0, 2, 3, 3), (4, "sus4"): (0, 2, 2, 2, 0, 0),
    (9, "sus4"): (-1, 0, 2, 2, 3, 0),
    (2, "sus2"): (-1, -1, 0, 2, 3, 0), (9, "sus2"): (-1, 0, 2, 2, 0, 0),
    (2, "7sus4"): (-1, -1, 0, 2, 1, 3), (4, "7sus4"): (0, 2, 0, 2, 0, 0),
    (9, "7sus4"): (-1, 0, 2, 0, 3, 0),
    (0, "6"): (-1, 3, 2, 2, 1, 0), (2, "6"): (-1, -1, 0, 2, 0, 2),
    (4, "6"): (0, 2, 2, 1, 2, 0), (7, "6"): (3, 2, 0, 0, 0, 0),
    (9, "6"): (-1, 0, 2, 2, 2, 2),
    (2, "m6"): (-1, -1, 0, 2, 0, 1), (4, "m6"): (0, 2, 2, 0, 2, 0),
    (9, "m6"): (-1, 0, 2, 2, 1, 2),
    (0, "9"): (-1, 3, 2, 3, 3, 3), (4, "9"): (0, 2, 0, 1, 0, 2),
    (9, "9"): (-1, 0, 2, 4, 2, 3),
    (0, "aug"): (-1, 3, 2, 1, 1, 0), (4, "aug"): (0, 3, 2, 1, 1, 0),
}
# Переносные формы от лада корня: от 6-й струны (форма ми) и от 5-й (форма ля).
# None — струна не звучит; −1 — лад ниже корня (у C9 ре-струна на втором ладу).
X = None
E_SHAPES = {
    "maj": (0, 2, 2, 1, 0, 0), "min": (0, 2, 2, 0, 0, 0), "7": (0, 2, 0, 1, 0, 0),
    "min7": (0, 2, 0, 0, 0, 0), "sus4": (0, 2, 2, 2, 0, 0), "7sus4": (0, 2, 0, 2, 0, 0),
    "maj7": (0, X, 1, 1, 0, X), "hdim7": (0, X, 0, 0, -1, X),
}
A_SHAPES = {
    "maj": (X, 0, 2, 2, 2, 0), "min": (X, 0, 2, 2, 1, 0), "7": (X, 0, 2, 0, 2, 0),
    "min7": (X, 0, 2, 0, 1, 0), "maj7": (X, 0, 2, 1, 2, 0), "sus4": (X, 0, 2, 2, 3, 0),
    "sus2": (X, 0, 2, 2, 0, 0), "7sus4": (X, 0, 2, 0, 3, 0), "6": (X, 0, 2, 2, 2, 2),
    "m6": (X, 0, 2, 2, 1, 2), "dim": (X, 0, 1, 2, 1, X), "dim7": (X, 0, 1, 2, 1, 2),
    "hdim7": (X, 0, 1, 0, 1, X), "aug": (X, 0, 3, 2, 2, 1), "9": (X, 0, -1, 0, 0, 0),
}
# Нет своей формы — берётся ближайшая попроще.
SIMPLER = {"9": "7", "6": "maj", "m6": "min", "aug": "maj", "dim": "min", "dim7": "dim",
           "hdim7": "min7", "sus2": "maj", "7sus4": "7"}

# Профили Крумхансла — Кесслер: насколько каждая ступень «своя» в мажоре и миноре.
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def parse(label):
    """«F#:min7/b7» → {"root": 6, "quality": "min7", "bass": 4}; тишина — None."""
    if not label or label in ("N", "X"):
        return None
    root, _, rest = label.partition(":")
    quality, _, bass = (rest or "maj").partition("/")
    pc = (LETTER[root[0]] + root[1:].count("#") - root[1:].count("b")) % 12
    if quality not in QUALITIES:
        quality = "min" if quality.startswith("min") else "maj"
    return {"root": pc, "quality": quality,
            "bass": (pc + DEGREES[bass]) % 12 if bass in DEGREES else None}


def flats(key):
    """Бемоли или диезы — по тональности: в фа мажоре Bb, а не A#."""
    pc, minor = key
    return pc in ((2, 7, 0, 5, 10, 3) if minor else (5, 10, 3, 8, 1))


def name(chord, shift=0, flat=False):
    names = FLAT if flat else SHARP
    text = names[(chord["root"] + shift) % 12] + QUALITIES[chord["quality"]][0]
    if chord["bass"] is not None:
        text += "/" + names[(chord["bass"] + shift) % 12]
    return text


def key_of(segments, alternative=False):
    """Тональность по звукам аккордов с учётом длительности: (корень, минор?).
    alternative — ещё и параллельная, если она почти так же вероятна: у ля минора
    и до мажора одни и те же звуки, и по аккордам их не всегда развести."""
    hist = np.zeros(12)
    for s in segments:
        c = parse(s["chord"])
        if c is None:
            continue
        dur = s["end"] - s["start"]
        for iv in QUALITIES[c["quality"]][1][:4]:
            hist[(c["root"] + iv) % 12] += dur * (1.5 if iv == 0 else 1.0)
    if not hist.any():
        return ((0, False), None) if alternative else (0, False)
    # Песни чаще начинаются и кончаются тоникой: это решает спор параллельных
    # тональностей, у которых звуки одни и те же (ля мажор и фа-диез минор).
    ends = [parse(s["chord"]) for s in segments if parse(s["chord"])]
    ends = [(c["root"], c["quality"].startswith(("min", "hdim", "dim"))) for c in (ends[0], ends[-1])] if ends else []
    score = {(pc, minor): np.corrcoef(hist, np.roll(profile, pc))[0, 1] + 0.08 * ends.count((pc, minor))
             for pc in range(12) for minor, profile in ((False, MAJOR), (True, MINOR))}
    found = max(score, key=score.get)
    if not alternative:
        return found
    pc, minor = found
    other = ((pc + 3) % 12, False) if minor else ((pc + 9) % 12, True)
    return found, (other if score[found] - score[other] < 0.1 else None)


def key_name(key, shift=0):
    pc, minor = key
    pc = (pc + shift) % 12
    flat = flats((pc, minor))
    short = (FLAT if flat else SHARP)[pc] + ("m" if minor else "")
    from i18n import current, t
    if current() == "en":
        name = (FLAT if flat else SHARP)[pc].replace("b", "♭").replace("#", "♯")
    else:
        name = (RU_FLAT if flat else RU_SHARP)[pc]
    return f"{name} {t('минор') if minor else t('мажор')} · {short}"


def fingering(root, quality):
    """Самая простая аппликатура: открытая, иначе баррэ пониже.
    → {"frets": (…6), "barre": лад или None, "cost": 0 открытая / больше — труднее}."""
    kind = QUALITIES[quality][2]
    while True:
        if (root, kind) in OPEN:
            return {"frets": OPEN[(root, kind)], "barre": None, "cost": 0}
        found = []
        for table, low in ((E_SHAPES, 4), (A_SHAPES, 9)):
            rel = table.get(kind)
            if rel is None:
                continue
            f = (root - low) % 12
            if f + min(r for r in rel if r is not None) < 0:
                f += 12
            frets = tuple(-1 if r is None else r + f for r in rel)
            found.append({"frets": frets, "barre": f or None, "cost": 0 if f == 0 else 10 + f})
        if found:
            return min(found, key=lambda x: x["cost"])
        kind = SIMPLER.get(kind, "maj")


def capo_for(segments, transpose=0):
    """Лад каподастра, с которым аккорды песни берутся открытыми формами чаще всего.
    Совет — только если выигрыш заметный: иначе без каподастра."""
    costs = []
    for capo in range(8):
        total = 0.0
        for s in segments:
            c = parse(s["chord"])
            if c is not None:
                hard = fingering((c["root"] + transpose - capo) % 12, c["quality"])["cost"] > 0
                total += (s["end"] - s["start"]) * hard
        costs.append(total)
    best = min(range(8), key=lambda c: (costs[c], c))
    return best if costs[0] - costs[best] > 0.15 * max(costs[0], 1e-9) else 0


def tidy(segments, min_len=0.3):
    """Для показа: без коротких вспышек и без повторов подряд."""
    out = []
    for s in segments:
        if out and (s["chord"] == out[-1]["chord"] or s["end"] - s["start"] < min_len):
            out[-1] = dict(out[-1], end=s["end"])
        else:
            out.append(dict(s))
    return out
