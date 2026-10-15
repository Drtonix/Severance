"""Severance: песня → голос и музыка → части, BPM, аккорды для гитары, новый голос."""
import json
import math
import os
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import (QFile, QIODevice, QMimeData, QPoint, QPointF, QRectF, QSettings, QSize, Qt,
                            QThread, QTimer, QUrl, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QCursor, QDesktopServices, QDrag, QFont,
                           QFontDatabase, QGuiApplication, QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen,
                           QFontMetricsF, QImage, QPixmap, QPolygonF, QRadialGradient, QTransform)
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMenuBar, QMessageBox,
                               QPushButton, QScrollArea, QStackedWidget, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

import engine
import guitar
import i18n
import links
from i18n import shown, t, tf

# Время нажатия на значок — от оболочки .app; в журнал пишется, когда показалось окно.
T0 = float(os.environ.get("SEVERANCE_T0") or time.time())

APP = "Severance"
AUTHOR = "DrTonix"
SITE = "bdub.space"
URL = "https://bdub.space"
# SEVERANCE_OUT — для проверок: результаты не в «Музыку» пользователя.
OUT_DIR = Path(os.environ.get("SEVERANCE_OUT") or Path.home() / "Music" / APP)
WORK = engine.APP_DIR / "work"
MEDIA_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif", ".wma",
             ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
# MLX обходит граф рекурсией: стека рабочего потока по умолчанию (512 КБ) не хватает.
STACK = 64 * 1024 * 1024

# Тёмное и светлое оформление: имена ниже переписываются при смене темы,
# а рисование и лист стилей берут их в момент отрисовки.
PALETTES = {
    "dark": {"BG": "#101013", "TEXT": "#ededf1", "MUTED": "#8d8d97", "FAINT": "#5b5b65",
             "SOFT": "#c4c4cc", "POPUP": "#1c1c21", "LINK": "#93a2ff", "LINK_HOVER": "#bcc6ff",
             "ERROR": "#ff8a7a", "INK": 255},
    "light": {"BG": "#f4f4f7", "TEXT": "#17171c", "MUTED": "#6b6b75", "FAINT": "#a2a2ac",
              "SOFT": "#46464e", "POPUP": "#ffffff", "LINK": "#4a58d6", "LINK_HOVER": "#2f3cb0",
              "ERROR": "#cf4436", "INK": 0},
}
BG = TEXT = MUTED = FAINT = SOFT = POPUP = LINK = LINK_HOVER = ERROR = ""
INK = 255
# Тёмный — на градиенте кнопок и круга, в обеих темах.
DARK = "#16161a"
THEMES = ("system", "light", "dark")


def use_palette(name):
    globals().update(PALETTES[name])


def ink(alpha):
    """Полупрозрачная заливка поверх фона: белая на тёмном, чёрная на светлом."""
    return QColor(255, 255, 255, alpha) if INK else QColor(0, 0, 0, int(alpha * 0.8))


def wash(alpha):
    """То же для листа стилей."""
    return f"rgba(255,255,255,{alpha})" if INK else f"rgba(0,0,0,{alpha * 0.8:.3g})"


use_palette("dark")
# Один градиент на всё — значок, круг, кнопка пуска: тёплое — голос, холодное — музыка.
STOPS = ((0.0, "#ffb15c"), (0.34, "#ff5a7a"), (0.68, "#8a5cff"), (1.0, "#3cc8f0"))
WARM = ("#ffb15c", "#ff5a7a")
LANES = {"vocals": WARM, "lead": WARM, "back": ("#ff8fb0",) * 2,
         "music": ("#8a5cff", "#3cc8f0"), "drums": ("#a07cff",) * 2, "bass": ("#6f7dff",) * 2,
         "guitar": ("#45b4ff",) * 2, "piano": ("#3fd6d0",) * 2, "other": ("#8098bb",) * 2,
         "kick": ("#c08cff",) * 2, "snare": ("#9d8fff",) * 2, "toms": ("#8073ff",) * 2,
         "hh": ("#d6b8ff",) * 2, "cymbals": ("#ead8ff",) * 2, "original": ("#9c9ca8",) * 2}
# Как дорожку можно разложить: (режим, пункт меню). «model» — модель из
# engine.SPLITS, «singers» — по исполнителям.
SPLIT_MODES = {"vocals": (("model", "Основной голос и бэк-вокал"), ("singers", "По исполнителям")),
               "lead": (("singers", "По исполнителям"),),
               "music": (("model", "Барабаны, бас, гитара, клавишные и другие инструменты"),),
               "drums": (("model", "Бочка, малый, томы, хай-хэт и тарелки"),),
               "other": (("timbre", "По тембру: инструмент 1, 2…"),),
               "back": (("singers", "По исполнителям"),),
               "guitar": (("timbre", "По тембру: инструмент 1, 2…"),),
               "piano": (("timbre", "По тембру: инструмент 1, 2…"),),
               "bass": (("timbre", "По тембру: инструмент 1, 2…"),)}
# Режимы, где число частей можно задать: (режим, «Число …»).
COUNTED = {"singers": "Число исполнителей…", "timbre": "Число инструментов…"}
SINGERS = ("#ffb15c", "#ff6f91", "#ffd36b", "#ff8a5c", "#f7a8d8", "#ffc39b")
INSTRUMENTS = ("#7fa3d6", "#9a8fe0", "#5fc0d8", "#b0a4e8", "#86b9e8", "#a8c4e0")
VOICE = ("#ffd36b", "#ff9a4d")
TILT = math.radians(18)
# Левая колонка: значок «Новой песни», точка выбранной песни и кнопка свёртки —
# на одной вертикали, названия — на другой. Свёрнутая колонка — узкая полоса
# без полей, значок и кнопка — по её середине.
ORB_X, TEXT_X = 22, 38
RAIL, RAIL_SLIM = 236, 2 * ORB_X


def font_family():
    have = set(QFontDatabase.families())
    return next((f for f in ("Avenir Next", "Helvetica Neue", "Segoe UI") if f in have), "Arial")


def style(family):
    return f"""
* {{ outline: none; font-family: "{family}"; }}
QWidget#root {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-size: 13px; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 26px; font-weight: 600; }}
QLabel#sub   {{ color: {MUTED}; font-size: 12px; }}
QLabel#bpm   {{ font-size: 46px; font-weight: 200; }}
QLabel#unit  {{ color: {MUTED}; font-size: 11px; }}
QLabel#hello {{ font-size: 19px; font-weight: 500; }}
QLabel#song  {{ font-size: 20px; font-weight: 600; }}
QLabel#stage {{ color: {MUTED}; font-size: 14px; }}
QLabel#faint {{ color: {FAINT}; font-size: 12px; }}
QLabel#error {{ color: {ERROR}; font-size: 12px; }}
QLabel#key   {{ font-size: 15px; font-weight: 600; }}
QPushButton#text {{
    background: transparent; border: none; color: {MUTED};
    padding: 4px 2px; font-size: 13px;
}}
QFrame#group {{ background: {wash(0.045)}; border-radius: 12px; }}
QFrame#rule  {{ background: {wash(0.07)}; }}
QScrollArea#settings, QWidget#settingsInner {{ background: transparent; border: none; }}
QPushButton#text:hover, QPushButton#text:checked {{ color: {TEXT}; }}
QPushButton#text:disabled {{ color: {FAINT}; }}
QPushButton#opt {{
    background: transparent; border: none; color: {MUTED};
    padding: 4px 3px 3px 3px; font-size: 13px; border-bottom: 2px solid transparent;
}}
QPushButton#opt:hover {{ color: {TEXT}; }}
QPushButton#opt:checked {{ color: {TEXT}; border-bottom: 2px solid #ff7a6b; }}
QPushButton#action {{
    background: transparent; border: none; color: {LINK};
    font-size: 12px; padding: 2px 0; text-align: left;
}}
QPushButton#action:hover {{ color: {LINK_HOVER}; }}
QPushButton#action:disabled {{ color: {MUTED}; }}
QLineEdit#link {{
    background: transparent; border: none; border-bottom: 1px solid {wash(0.14)};
    padding: 8px 2px; font-size: 14px; color: {TEXT};
    selection-background-color: rgba(255,90,122,0.45);
}}
QLineEdit#link:focus {{ border-bottom: 1px solid #ff7a6b; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {wash(0.12)}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QListWidget#history {{ background: transparent; border: none; }}
QMenu {{
    background: {POPUP}; border: 1px solid {wash(0.08)};
    border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 6px 20px 6px 10px; border-radius: 5px; color: {TEXT}; }}
QMenu::item:selected {{ background: {wash(0.08)}; }}
QToolTip {{
    background: {POPUP}; color: {TEXT}; border: 1px solid {wash(0.08)};
    padding: 5px 7px; font-size: 12px;
}}
"""


def app_icon():
    here = Path(__file__).resolve().parent
    for p in (here.parent / "AppIcon.icns", here / "icon" / "AppIcon.icns"):
        if p.exists():
            return QIcon(str(p))
    return QIcon()


def clock(seconds: float) -> str:
    m, s = divmod(int(max(seconds, 0)), 60)
    return f"{m}:{s:02d}"


def safe_name(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', " ", text).strip()[:80] or "песня"


def unique(path: Path) -> Path:
    """«Имя», «Имя 2», «Имя 3»… — для папок и для файлов."""
    if not path.exists():
        return path
    n = 2
    while (path.parent / f"{path.stem} {n}{path.suffix}").exists():
        n += 1
    return path.parent / f"{path.stem} {n}{path.suffix}"


def gradient(x0, y0, x1, y1, stops=STOPS):
    g = QLinearGradient(x0, y0, x1, y1)
    for at, c in stops:
        g.setColorAt(at, QColor(c))
    return g


class Drift:
    """Плавное случайное блуждание около нуля: ключевые значения в случайные
    моменты, между ними — сплайн Катмулла–Рома. Путь не повторяется."""

    def __init__(self, rng, lo=1.4, hi=3.8):
        self.rng, self.lo, self.hi = rng, lo, hi
        self.keys = [(-2 * hi, rng.uniform(-1, 1))]      # второй ключ — ещё до нуля
        while len(self.keys) < 4:
            self._add()

    def _add(self):
        t = self.keys[-1][0] + self.rng.uniform(self.lo, self.hi)
        self.keys.append((t, self.rng.uniform(-1, 1)))

    def at(self, t):
        while t >= self.keys[2][0]:
            self.keys.pop(0)
            self._add()
        (t1, p1), (t2, p2) = self.keys[1], self.keys[2]
        p0, p3 = self.keys[0][1], self.keys[3][1]
        u = (t - t1) / (t2 - t1)
        return 0.5 * (2 * p1 + (p2 - p0) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u
                      + (3 * p1 - p0 - 3 * p2 + p3) * u * u * u)


class Spin:
    """Переливание, пока идёт дело: центр градиента плавает, вращение то быстрее,
    то медленнее, пятна блуждают каждое само по себе — у каждой кнопки свой путь,
    и он не повторяется. Включается и гаснет плавно; в покое таймер стоит."""
    BLOBS = 5

    def __init__(self, widget):
        import random
        self.widget = widget
        rng = random.Random()
        self.center = (Drift(rng), Drift(rng))
        self.speed = Drift(rng, 2.0, 5.0)
        self.blobs = [(Drift(rng), Drift(rng), Drift(rng, 2.0, 4.5), Drift(rng, 2.5, 6.0))
                      for _ in range(self.BLOBS)]
        self.t = 0.0
        self.angle = rng.uniform(0, 360)
        self.amount = 0.0           # сила: 0 — обычный градиент, 1 — переливается
        self.tempo = 1.0            # множитель хода: у кнопки воспроизведения — по BPM песни
        self.on = False
        self.last = 0.0
        self.timer = QTimer(widget)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._step)

    def set(self, on):
        self.on = bool(on)
        if self.on or self.amount > 0:
            if not self.timer.isActive():
                self.last = time.monotonic()
                self.timer.start()

    def _step(self):
        now = time.monotonic()
        dt, self.last = min(now - self.last, 0.1), now
        dt *= self.tempo
        self.t += dt
        self.angle += (55 + 70 * self.speed.at(self.t)) * dt      # от −15 до 125 °/с
        self.amount += ((1.0 if self.on else 0.0) - self.amount) * min(dt * 3.5, 1.0)
        if not self.on and self.amount < 0.01:
            self.amount = 0.0
            self.timer.stop()
        self.widget.update()

    def state(self):
        """Центр (доля радиуса), угол и пятна: [(x, y, размер, место в палитре)]."""
        t = self.t
        cx, cy = (d.at(t) * 0.42 for d in self.center)
        n = len(self.blobs)
        blobs = [(x.at(t) * 0.62, y.at(t) * 0.62, 0.7 + 0.25 * z.at(t), (i / n + 0.35 * c.at(t)) % 1)
                 for i, (x, y, z, c) in enumerate(self.blobs)]
        return cx, cy, self.angle, blobs


def palette(at):
    """Цвет палитры в точке at ∈ [0, 1): по кругу, последний переходит в первый."""
    stops = [QColor(c) for _, c in STOPS]
    x = at % 1 * len(stops)
    a, b, k = stops[int(x)], stops[(int(x) + 1) % len(stops)], x % 1
    return QColor(int(a.red() + (b.red() - a.red()) * k), int(a.green() + (b.green() - a.green()) * k),
                  int(a.blue() + (b.blue() - a.blue()) * k))


def paint_flow(p: QPainter, shape: QPainterPath, cx, cy, r, spin):
    """Переливы внутри формы: плавный градиент, повёрнутый вокруг плавающего центра,
    и поверх — мягкие пятна. Пятна блуждают и по кругу, и по палитре: цвета
    перетекают друг в друга без резких точек и швов."""
    if spin is None or spin.amount <= 0:
        return
    ox, oy, angle, blobs = spin.state()
    fx, fy = cx + ox * r, cy + oy * r
    a = math.radians(angle)
    dx, dy = math.cos(a) * r * 1.5, math.sin(a) * r * 1.5
    p.save()
    p.setOpacity(spin.amount)
    p.setClipPath(shape, Qt.IntersectClip)
    p.setPen(Qt.NoPen)
    area = shape.boundingRect().adjusted(-2, -2, 2, 2)
    p.setBrush(gradient(fx - dx, fy - dy, fx + dx, fy + dy))
    p.drawRect(area)
    for bx, by, size, hue in blobs:
        x, y = cx + bx * r, cy + by * r
        c = palette(hue)
        g = QRadialGradient(x, y, r * size)
        core, mid, rim = c.lighter(108), c.lighter(108), QColor(c)
        core.setAlpha(200)
        mid.setAlpha(90)
        rim.setAlpha(0)
        g.setColorAt(0, core)
        g.setColorAt(0.55, mid)
        g.setColorAt(1, rim)
        p.setBrush(g)
        p.drawRect(area)
    p.restore()


def paint_orb(p: QPainter, cx, cy, r, gap, spin=None):
    """Круг из значка: две половины по наклонному разрезу, раздвинутые на gap.
    Идёт дело (spin) — половины переливаются."""
    dx, dy = math.sin(TILT), -math.cos(TILT)
    nx, ny = math.cos(TILT), math.sin(TILT)
    big = r * 3
    disc = QPainterPath()
    disc.addEllipse(QPointF(cx, cy), r, r)
    p.setPen(Qt.NoPen)
    p.setBrush(gradient(cx - r, cy - r, cx + r, cy + r))
    halves = QPainterPath()
    for side in (-1, 1):
        cut = QPainterPath()
        cut.addPolygon(QPolygonF([
            QPointF(cx + dx * big, cy + dy * big),
            QPointF(cx + dx * big + nx * big * side, cy + dy * big + ny * big * side),
            QPointF(cx - dx * big + nx * big * side, cy - dy * big + ny * big * side),
            QPointF(cx - dx * big, cy - dy * big)]))
        shift = QPointF((nx - dx * 0.55) * gap * side, (ny - dy * 0.55) * gap * side)
        half = disc.intersected(cut).translated(shift)
        p.drawPath(half)
        halves.addPath(half)
    paint_flow(p, halves, cx, cy, r * 1.05, spin)


class Mixer(QIODevice):
    """Все дорожки — одним потоком: не расходятся, соло и выключение срабатывают сразу.

    Дорожки — int16 [кадры, 2]. Метроном щёлкает на найденных ударах, сильная
    доля выше: так темп проверяется на слух.
    """

    def __init__(self):
        super().__init__()
        self.tracks = {}
        self.active = set()
        self.gains = {}             # 1024 — как есть; громкость в целых, чтобы не тратить float
        self.length = 0
        self.pos = 0
        self.beats = np.zeros(0, dtype=np.int64)
        self.strong = set()
        self.metronome = False
        t = np.arange(int(engine.SR * 0.03)) / engine.SR
        env = np.exp(-t * 90)
        self.click = (np.sin(2 * np.pi * 1500 * t) * env * 9000).astype(np.int32)
        self.click_hi = (np.sin(2 * np.pi * 2400 * t) * env * 11000).astype(np.int32)

    def load(self, tracks: dict, beats=(), downbeats=()):
        self.tracks = tracks
        self.length = max((len(a) for a in tracks.values()), default=0)
        self.pos = 0
        self.beats = (np.asarray(beats) * engine.SR).astype(np.int64)
        self.strong = {int(round(b * engine.SR)) for b in downbeats}

    def readData(self, maxlen):
        n = int(maxlen) // 4
        end = min(self.pos + n, self.length)
        k = end - self.pos
        if k <= 0:
            return b""
        acc = np.zeros((k, 2), np.int32)
        for name in self.active:
            a = self.tracks.get(name)
            g = self.gains.get(name, 1024)
            if a is not None and g > 0 and self.pos < len(a):
                part = a[self.pos:min(end, len(a))]
                if g == 1024:
                    acc[:len(part)] += part
                else:
                    acc[:len(part)] += (part.astype(np.int32) * g) >> 10
        if self.metronome and len(self.beats):
            i0, i1 = np.searchsorted(self.beats, [self.pos - len(self.click), end])
            for b in self.beats[i0:i1]:
                c = self.click_hi if int(b) in self.strong else self.click
                s, e = max(b, self.pos), min(b + len(c), end)
                if s < e:
                    acc[s - self.pos:e - self.pos] += c[s - b:e - b, None]
        self.pos = end
        return np.clip(acc, -32768, 32767).astype(np.int16).tobytes()

    def writeData(self, data):
        return 0

    def bytesAvailable(self):
        return max(self.length - self.pos, 0) * 4 + super().bytesAvailable()

    def isSequential(self):
        return True


class Player:
    """QAudioSink в режиме вытягивания. Нет устройства вывода — молча без звука."""

    def __init__(self):
        self.mixer = Mixer()
        self.mixer.open(QIODevice.ReadOnly)
        fmt = QAudioFormat()
        fmt.setSampleRate(engine.SR)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Int16)
        device = QMediaDevices.defaultAudioOutput()
        self.sink = QAudioSink(device, fmt) if not device.isNull() else None
        if self.sink is not None:
            # 120 мс буфера: соло и выключение слышны почти сразу.
            self.sink.setBufferSize(int(engine.SR * 4 * 0.12))
        self.playing = False
        self.started = False

    def position(self) -> float:
        lag = 0
        if self.sink is not None and self.started:
            lag = (self.sink.bufferSize() - self.sink.bytesFree()) // 4
        return max(self.mixer.pos - lag, 0) / engine.SR

    def seek(self, seconds: float):
        self.mixer.pos = int(min(max(seconds, 0), self.mixer.length / engine.SR) * engine.SR)

    def play(self):
        if self.sink is None or not self.mixer.length:
            return
        if self.mixer.pos >= self.mixer.length:
            self.mixer.pos = 0
        if not self.started:
            self.sink.start(self.mixer)
            self.started = True
        else:
            self.sink.resume()
        self.playing = True

    def pause(self):
        if self.sink is not None and self.started:
            self.sink.suspend()
        self.playing = False

    def stop(self):
        if self.sink is not None:
            self.sink.stop()
        self.started = self.playing = False


class Orb(QWidget):
    """Круг из значка. Ход разделения — насколько разошлись половины; без доли
    половины дышат на месте. Над пустым экраном круг — ещё и кнопка выбора."""
    clicked = Signal()

    def __init__(self, size, clickable=False):
        super().__init__()
        self.setFixedSize(size, size)
        self.clickable = clickable
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
        self.target = 0.0
        self.value = 0.0
        self.busy = False
        self.hot = False
        self.phase = 0.0
        self.spin = Spin(self)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._step)

    def set_split(self, share, busy=False):
        self.target, self.busy = share, busy
        self.timer.start()

    def set_hot(self, on):
        self.hot = on
        self.timer.start()

    def _step(self):
        goal = self.target + (0.14 if self.hot else 0.0)
        if self.busy:
            self.phase += 0.045
            goal += 0.06 * (1 - math.cos(self.phase))
        self.value += (goal - self.value) * 0.12
        if not self.busy and abs(goal - self.value) < 0.002:
            self.value = goal
            self.timer.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.width()
        r = s * 0.33
        paint_orb(p, s / 2, s / 2, r, r * (0.07 + 0.36 * min(self.value, 1.2)), self.spin)

    def enterEvent(self, e):
        if self.clickable:
            self.set_hot(True)

    def leaveEvent(self, e):
        if self.clickable:
            self.set_hot(False)

    def mouseReleaseEvent(self, e):
        if self.clickable and e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class ElideLabel(QLabel):
    """Длинное название — с многоточием, целиком в подсказке."""

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self):
        return QSize(40, super().minimumSizeHint().height())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        p.drawText(self.rect(), int(self.alignment()) | Qt.AlignVCenter, text)


class Lane(QWidget):
    """Дорожка: точка — звучит ли, имя, «соло», волна в своём цвете и громкость.
    У разложенной дорожки точка, «соло» и громкость действуют на все её части.
    Имя можно перетащить в Finder или другую программу — уйдёт сам файл."""
    mute_clicked = Signal(str)
    solo_clicked = Signal(str)
    split_clicked = Signal(str)
    gain_changed = Signal()
    seek = Signal(float)
    reveal = Signal(object)
    save = Signal(str)
    selected = Signal(str)                  # выделен отрезок — у остальных снять
    context = Signal(str, object)           # правый щелчок: ключ, место на экране
    LABEL = 214
    RIGHT = 100
    LOW, HIGH = -30.0, 6.0      # шкала громкости, дБ; в самом низу — выкл

    def __init__(self, key, title, colors, path: Path, height, depth=0):
        super().__init__()
        self.key, self.title, self.colors, self.path, self.depth = key, title, colors, path, depth
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.muted = False
        self.solo = False
        self.audible = True
        self.group = False          # разложена: звук — у частей
        self.partial = False        # из частей звучит не всё
        self.db = 0.0               # None — выключена регулятором
        self.split_text = ""        # «разложить», «раскладка · 40%», «бэк-вокала нет»
        self.split_live = False
        self.split_tip = ""
        self.peaks = np.zeros(0, dtype=np.float32)
        self.duration = 0.0
        self.at = 0.0
        self.hover = False
        self.press = None
        self.scrub = False
        self.fading = False
        self._path = None
        self._pix = {}              # готовые картинки волны: яркая, приглушённая, серая
        self.selectable = False     # часть разложенной дорожки: протяжка по волне выделяет
        self.sel = None             # выделенный отрезок, секунды
        self.sel_from = None
        self.sel_moved = False

    def set_audio(self, data: np.ndarray, top: float):
        """Огибающая по громкости кусков. Тише четверти всей песни — рисуется
        соразмерно меньше: тихий инструмент не притворяется громким."""
        buckets = 1600
        step = max(len(data) // buckets, 1)
        mono = data[:step * buckets, 0].astype(np.float32) + data[:step * buckets, 1]
        rms = np.sqrt((mono.reshape(-1, step) ** 2).mean(axis=1)) / 65536.0
        norm = max(float(rms.max()) if len(rms) else 0.0, top * 0.25, 1e-9)
        self.peaks = np.clip(rms / norm, 0, 1) ** 0.8
        self.duration = len(data) / engine.SR
        self._path = None
        self._pix = {}
        self.update()

    def resizeEvent(self, e):
        self._path = None
        self._pix = {}

    def _picture(self, kind):
        """Волна целиком, отрисованная заранее: каждый кадр её градиент с обрезкой
        заново — это и было «мало кадров», когда дорожек десяток."""
        if kind not in self._pix:
            w = self._wave()
            ratio = self.devicePixelRatioF()
            pix = QPixmap(int(w.right() * ratio) + 2, int(self.height() * ratio) + 2)
            pix.setDevicePixelRatio(ratio)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            if kind == "grey":
                p.setOpacity(0.22)
                p.fillPath(self._outline(), QColor(MUTED))
            else:
                # Непроигранное на светлом фоне бледнеет сильнее — ему плотнее.
                p.setOpacity(1.0 if kind == "on" else (0.32 if INK else 0.5))
                p.fillPath(self._outline(), gradient(w.left(), 0, w.right(), 0,
                                                     ((0, self.colors[0]), (1, self.colors[1]))))
            p.end()
            self._pix[kind] = pix
        return self._pix[kind]

    def playhead_x(self, at=None):
        w = self._wave()
        at = self.at if at is None else at
        return w.left() + w.width() * (at / self.duration if self.duration else 0)

    def _x(self):
        return 22 + 16 * self.depth

    def _line(self):
        """Средняя линия имени: со ссылкой «разложить» под ним — выше середины."""
        return self.height() / 2 - (8 if self.split_text else 0)

    def _dot(self):
        return QPointF(6 + 16 * self.depth, self._line())

    def _name(self):
        return QRectF(self._x(), self._line() - 10, self.LABEL - self._x() - 52, 20)

    def _solo(self):
        return QRectF(self.LABEL - 50, self._line() - 10, 40, 20)

    def _split(self):
        w = self.fontMetrics().horizontalAdvance(self.split_text) + 8
        return QRectF(self._x(), self._line() + 9, min(w, self.LABEL - self._x() - 10), 16)

    def _wave(self):
        return QRectF(self.LABEL, 5, max(self.width() - self.LABEL - self.RIGHT, 1), self.height() - 10)

    def _fader(self):
        x0 = self.width() - self.RIGHT + 18
        return QRectF(x0, self.height() / 2 - 12, self.RIGHT - 26, 14)

    def _db_text(self):
        f = self._fader()
        return QRectF(f.left(), f.bottom() + 1, f.width(), 14)

    def _near_dot(self, pos):
        d = self._dot()
        return math.dist((pos.x(), pos.y()), (d.x(), d.y())) <= 12

    def _pos(self):
        return 0.0 if self.db is None else (self.db - self.LOW) / (self.HIGH - self.LOW)

    def _set_db(self, db):
        if db != self.db:
            self.db = db
            self.gain_changed.emit()
            self.update()

    def _fade_to(self, x):
        f = self._fader()
        p = min(max((x - f.left()) / f.width(), 0.0), 1.0)
        if p < 0.02:
            self._set_db(None)
            return
        db = self.LOW + p * (self.HIGH - self.LOW)
        # Около нуля липнет к нулю: на слух норму так найти проще.
        self._set_db(0.0 if abs(db) < 0.8 else round(db, 1))

    def db_label(self):
        if self.db is None:
            return t("выкл")
        if self.db == 0:
            return "0 " + t("дБ")
        return f"{'+' if self.db > 0 else '−'}{abs(self.db):g} " + t("дБ")

    def _outline(self):
        if self._path is None:
            w = self._wave()
            path = QPainterPath()
            if len(self.peaks):
                n = max(int(w.width() / 2), 2)
                edges = np.linspace(0, len(self.peaks), n + 1).astype(int)
                v = np.maximum.reduceat(self.peaks, np.minimum(edges[:-1], len(self.peaks) - 1))
                mid, amp = w.center().y(), w.height() / 2
                xs = w.left() + np.arange(n) * w.width() / (n - 1)
                half = np.maximum(v * amp, 0.7)
                path.moveTo(xs[0], mid - half[0])
                for x, h in zip(xs[1:], half[1:]):
                    path.lineTo(x, mid - h)
                for x, h in zip(xs[::-1], half[::-1]):
                    path.lineTo(x, mid + h)
                path.closeSubpath()
            self._path = path
        return self._path

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c0, c1 = QColor(self.colors[0]), QColor(self.colors[1])
        h = self.height()

        dot = self._dot()
        if self.muted:
            p.setPen(QPen(QColor(FAINT), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(dot, 5, 5)
        elif self.partial:
            # Звучит часть дорожки: точка закрашена наполовину.
            p.setPen(QPen(c0, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(dot, 5, 5)
            half = QPainterPath()
            half.moveTo(dot)
            half.arcTo(QRectF(dot.x() - 5, dot.y() - 5, 10, 10), 90, 180)
            half.closeSubpath()
            p.fillPath(half, c0)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(c0 if self.audible else QColor(FAINT))
            p.drawEllipse(dot, 6, 6)

        f = QFont(self.font())
        f.setPixelSize(13)
        f.setWeight(QFont.Medium if self.group else QFont.Normal)
        p.setFont(f)
        p.setPen(QColor(TEXT if self.audible else MUTED))
        name = self._name()
        p.drawText(name, Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(self.title, Qt.ElideRight, int(name.width())))
        f.setWeight(QFont.Normal)
        if self.hover or self.solo:
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(c0 if self.solo else QColor(FAINT))
            p.drawText(self._solo(), Qt.AlignVCenter | Qt.AlignRight, t("соло"))
        if self.split_text:
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(QColor(LINK) if self.split_live else QColor(FAINT))
            p.drawText(self._split(), Qt.AlignVCenter | Qt.AlignLeft, self.split_text)

        w = self._wave()
        played = self.playhead_x()
        if not self.audible:
            p.drawPixmap(0, 0, self._picture("grey"))
        else:
            p.save()
            p.setClipRect(QRectF(w.left(), 0, played - w.left(), h))
            p.drawPixmap(0, 0, self._picture("on"))
            p.restore()
            p.save()
            p.setClipRect(QRectF(played, 0, w.right() - played + 1, h))
            p.drawPixmap(0, 0, self._picture("dim"))
            p.restore()
        if self.sel and self.duration:
            x0 = w.left() + w.width() * self.sel[0] / self.duration
            x1 = w.left() + w.width() * self.sel[1] / self.duration
            p.fillRect(QRectF(x0, 2, x1 - x0, h - 4), ink(34))
            p.fillRect(QRectF(x0 - 0.5, 2, 1, h - 4), ink(140))
            p.fillRect(QRectF(x1 - 0.5, 2, 1, h - 4), ink(140))
        if self.duration:
            p.fillRect(QRectF(played - 0.75, 2, 1.5, h - 4), ink(215))

        # Громкость: дорожка, отметка нуля, ручка и подпись.
        fr = self._fader()
        y = fr.center().y()
        zero = fr.left() + fr.width() * (-self.LOW) / (self.HIGH - self.LOW)
        knob = fr.left() + fr.width() * self._pos()
        p.setPen(Qt.NoPen)
        p.setBrush(ink(26))
        p.drawRoundedRect(QRectF(fr.left(), y - 1.5, fr.width(), 3), 1.5, 1.5)
        # Цвет — как у правого края волны, рядом с которым регулятор стоит.
        p.setBrush(c1 if self.audible else QColor(FAINT))
        p.drawRoundedRect(QRectF(fr.left(), y - 1.5, knob - fr.left(), 3), 1.5, 1.5)
        p.fillRect(QRectF(zero - 0.5, y - 5, 1, 10), ink(60))
        p.setBrush(QColor(TEXT if self.audible else MUTED))
        p.drawEllipse(QPointF(knob, y), 5, 5)
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor(FAINT if self.db == 0 else MUTED))
        p.drawText(self._db_text(), Qt.AlignHCenter | Qt.AlignTop, self.db_label())

    def _seek_to(self, x):
        w = self._wave()
        if self.duration:
            self.seek.emit(min(max((x - w.left()) / w.width(), 0), 1) * self.duration)

    def _in_fader(self, pos):
        return self._fader().adjusted(-8, -4, 8, 4).contains(pos)

    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() == Qt.RightButton:
            self.context.emit(self.key, e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        if self._db_text().adjusted(-4, 0, 4, 2).contains(pos) and self.db != 0:
            self._set_db(0.0)
        elif self._in_fader(pos):
            self.fading = True
            self._fade_to(pos.x())
        elif self.LABEL - 4 <= pos.x() < self.width() - self.RIGHT + 6:
            if self.selectable and self.duration:
                self.sel_from, self.sel_moved = self._time(pos.x()), False
            else:
                self.scrub = True
                self._seek_to(pos.x())
        elif self._near_dot(pos):
            self.mute_clicked.emit(self.key)
        elif self.split_text and self.split_live and self._split().contains(pos):
            self.split_clicked.emit(self.key)
        elif self._solo().contains(pos):
            self.solo_clicked.emit(self.key)
        else:
            self.press = pos

    def mouseDoubleClickEvent(self, e):
        if self._in_fader(e.position()):
            self._set_db(0.0)
        else:
            self.mousePressEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if e.buttons() & Qt.LeftButton:
            if self.fading:
                self._fade_to(pos.x())
            elif self.sel_from is not None:
                at = self._time(pos.x())
                if self.sel_moved or abs(at - self.sel_from) * self._wave().width() / self.duration > 3:
                    self.sel_moved = True
                    self.sel = (min(at, self.sel_from), max(at, self.sel_from))
                    self.update()
            elif self.scrub:
                self._seek_to(pos.x())
            elif self.press is not None and (pos - self.press).manhattanLength() > 8:
                self.press = None
                self._drag()
            return
        over_split = bool(self.split_text) and self._split().contains(pos)
        self.setToolTip(self.split_tip if over_split else
                        (t("Вернуть 0 дБ") if self._db_text().contains(pos) and self.db != 0 else ""))
        clickable = (self._near_dot(pos) or self._solo().contains(pos) or self._in_fader(pos)
                     or (over_split and self.split_live) or self.LABEL - 4 <= pos.x()
                     or (self._db_text().contains(pos) and self.db != 0))
        self.setCursor(Qt.PointingHandCursor if clickable else Qt.OpenHandCursor)

    def wheelEvent(self, e):
        if self._in_fader(e.position()):
            step = 1.0 if e.angleDelta().y() > 0 else -1.0
            base = self.LOW if self.db is None else self.db
            db = min(max(base + step, self.LOW), self.HIGH)
            self._set_db(None if db <= self.LOW else (0.0 if abs(db) < 0.5 else db))
            e.accept()
        else:
            super().wheelEvent(e)

    def mouseReleaseEvent(self, e):
        if self.sel_from is not None:
            if self.sel_moved and self.sel and self.sel[1] - self.sel[0] >= 0.05:
                self.selected.emit(self.key)
            else:
                self.clear_sel()
                self._seek_to(e.position().x())
            self.sel_from = None
        self.scrub = False
        self.fading = False
        self.press = None

    def _time(self, x):
        w = self._wave()
        return min(max((x - w.left()) / w.width(), 0), 1) * self.duration

    def clear_sel(self):
        if self.sel is not None:
            self.sel = None
            self.update()

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def _drag(self):
        if self.path is None:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.path))])
        drag = QDrag(self)
        drag.setMimeData(mime)
        f = QFont(self.font())
        f.setPixelSize(13)
        width = self.fontMetrics().horizontalAdvance(self.path.name) + 40
        pix = QPixmap(int(width * 2), 56)
        pix.setDevicePixelRatio(2)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(POPUP))
        p.drawRoundedRect(QRectF(0, 0, width, 28), 8, 8)
        p.setBrush(QColor(self.colors[0]))
        p.drawEllipse(QPointF(14, 14), 5, 5)
        p.setFont(f)
        p.setPen(QColor(TEXT))
        p.drawText(QRectF(26, 0, width - 30, 28), Qt.AlignVCenter, self.path.name)
        p.end()
        drag.setPixmap(pix)
        drag.exec(Qt.CopyAction)


class ChordTicker(QWidget):
    """Лента аккордов вокруг текущего места: 3 с прошлого и 9 с вперёд.
    Аккорд начинается у левого края своей плашки; внизу — начала тактов."""
    seek = Signal(float)
    BEFORE, AFTER = 3.0, 9.0

    def __init__(self):
        super().__init__()
        self.setFixedHeight(46)
        self.setCursor(Qt.PointingHandCursor)
        self.items = []             # (начало, конец, название или None)
        self.bars = np.zeros(0)
        self.at = 0.0

    def _x(self, t):
        return (t - self.at + self.BEFORE) / (self.BEFORE + self.AFTER) * self.width()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        f = QFont(self.font())
        f.setPixelSize(14)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        lo, hi = self.at - self.BEFORE, self.at + self.AFTER
        for start, end, name in self.items:
            if end < lo or start > hi or name is None:
                continue
            x0, x1 = self._x(start) + 1.5, self._x(end) - 1.5
            r = QRectF(x0, 4, max(x1 - x0, 2), h - 14)
            p.setPen(Qt.NoPen)
            if start <= self.at < end:
                p.setBrush(gradient(r.left(), 0, r.right(), 0, ((0, WARM[0]), (1, WARM[1]))))
                p.drawRoundedRect(r, 7, 7)
                p.setPen(QColor(DARK))
            else:
                past = end <= self.at
                p.setBrush(ink(8 if past else 17))
                p.drawRoundedRect(r, 7, 7)
                p.setPen(QColor(FAINT if past else TEXT))
            # Уехавшая за левый край плашка подписана у края, а не за ним.
            r_text = QRectF(max(r.left(), 0) + 8, r.top(), r.right() - max(r.left(), 0) - 12, r.height())
            text = p.fontMetrics().elidedText(name, Qt.ElideRight, int(r_text.width()))
            p.drawText(r_text, Qt.AlignVCenter | Qt.AlignLeft, text)
        p.setPen(QPen(ink(46), 1))
        for b in self.bars[(self.bars >= lo) & (self.bars <= hi)]:
            x = self._x(b)
            p.drawLine(QPointF(x, h - 7), QPointF(x, h - 2))
        x = self._x(self.at)
        p.fillRect(QRectF(x - 0.75, 0, 1.5, h), ink(215))

    def mousePressEvent(self, e):
        t = self.at - self.BEFORE + e.position().x() / max(self.width(), 1) * (self.BEFORE + self.AFTER)
        self.seek.emit(max(t, 0.0))


class ChordDiagram(QWidget):
    """Аппликатура: шесть струн, пять ладов, точки, баррэ, × и ○ над грифом."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(84, 124)
        self.name = ""
        self.frets = None
        self.barre = None
        self.now = False

    def set(self, name, shape, now):
        self.name, self.now = name, now
        self.frets = shape["frets"] if shape else None
        self.barre = shape["barre"] if shape else None
        self.update()

    def paintEvent(self, _):
        if not self.name:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setPixelSize(16 if self.now else 14)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(TEXT if self.now else MUTED))
        sx, gx, top, gy = 6, 11, 44, 15
        head = QRectF(0, 0, 2 * sx + 5 * gx, 24)
        p.drawText(head, Qt.AlignCenter, p.fontMetrics().elidedText(self.name, Qt.ElideRight, self.width()))
        if not self.frets:
            return
        played = [x for x in self.frets if x > 0]
        base = min(played) if played and max(played) > 4 else 1
        grid = ink(80 if self.now else 50)
        p.setPen(QPen(grid, 1))
        for i in range(6):
            p.drawLine(QPointF(sx + i * gx, top), QPointF(sx + i * gx, top + 5 * gy))
        for j in range(6):
            p.drawLine(QPointF(sx, top + j * gy), QPointF(sx + 5 * gx, top + j * gy))
        if base == 1:
            p.setPen(QPen(grid, 3))
            p.drawLine(QPointF(sx, top), QPointF(sx + 5 * gx, top))
        else:
            f.setPixelSize(10)
            f.setWeight(QFont.Normal)
            p.setFont(f)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(sx + 5 * gx + 6, top, 20, gy), Qt.AlignLeft | Qt.AlignVCenter, f"{base}")
        mark = QColor(TEXT if self.now else MUTED)
        dot = QColor(WARM[1]) if self.now else QColor(TEXT)
        for i, fr in enumerate(self.frets):
            x, y = sx + i * gx, top - 8
            if fr < 0:
                p.setPen(QPen(mark, 1.3))
                p.drawLine(QPointF(x - 3, y - 3), QPointF(x + 3, y + 3))
                p.drawLine(QPointF(x - 3, y + 3), QPointF(x + 3, y - 3))
            elif fr == 0:
                p.setPen(QPen(mark, 1.3))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x, y), 3, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(dot)
        span = [i for i, fr in enumerate(self.frets) if self.barre and fr == self.barre]
        if len(span) >= 2:
            y = top + (self.barre - base + 0.5) * gy
            p.drawRoundedRect(QRectF(sx + span[0] * gx - 5, y - 5, (span[-1] - span[0]) * gx + 10, 10), 5, 5)
        for i, fr in enumerate(self.frets):
            if fr > 0 and not (len(span) >= 2 and fr == self.barre and span[0] <= i <= span[-1]):
                p.drawEllipse(QPointF(sx + i * gx, top + (fr - base + 0.5) * gy), 4.5, 4.5)


class GuitarPanel(QWidget):
    """Аккорды песни для гитары: тональность, каподастр, тон, лента и аппликатуры."""
    seek = Signal(float)
    find = Signal()
    changed = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 14)
        v.setSpacing(10)
        self.body = QWidget()
        b = QVBoxLayout(self.body)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.key = QLabel("")
        self.key.setObjectName("key")
        self.key.setToolTip(t("Тональность — по аккордам песни"))
        row.addWidget(self.key)
        row.addSpacing(26)
        self.capo_value = self._stepper(row, t("Каподастр"), self._capo)
        self.capo_hint = QPushButton("")
        self.capo_hint.setObjectName("action")
        self.capo_hint.setCursor(Qt.PointingHandCursor)
        self.capo_hint.setFocusPolicy(Qt.NoFocus)
        self.capo_hint.setToolTip(t("С каподастром на этом ладу больше аккордов берётся без баррэ"))
        self.capo_hint.clicked.connect(lambda: self._capo(self.suggest - self.capo))
        row.addSpacing(8)
        row.addWidget(self.capo_hint)
        row.addSpacing(22)
        self.tone_value = self._stepper(row, t("Тон"), self._tone)
        row.addStretch()
        b.addLayout(row)
        self.ticker = ChordTicker()
        self.ticker.seek.connect(self.seek)
        b.addWidget(self.ticker)
        dia = QHBoxLayout()
        dia.setSpacing(8)
        self.diagrams = [ChordDiagram() for _ in range(7)]
        for d in self.diagrams:
            dia.addWidget(d)
        dia.addStretch()
        b.addLayout(dia)
        v.addWidget(self.body)
        self.empty = QWidget()
        e = QHBoxLayout(self.empty)
        e.setContentsMargins(0, 0, 0, 0)
        self.find_btn = GradientButton(t("Подобрать аккорды"))
        self.find_btn.clicked.connect(self.find)
        e.addWidget(self.find_btn)
        self.find_note = QLabel("")
        self.find_note.setObjectName("sub")
        e.addSpacing(12)
        e.addWidget(self.find_note)
        e.addStretch()
        v.addWidget(self.empty)
        self.raw = []
        self.segments = []
        self.key_pc, self.key_alt = (0, False), None
        self.capo = 0
        self.transpose = 0
        self.suggest = 0
        self.current = None
        self.set_song([], (), 0, 0)

    def _stepper(self, row, caption, step):
        lab = QLabel(caption)
        lab.setObjectName("faint")
        row.addWidget(lab)
        row.addSpacing(4)
        value = QLabel("")
        value.setAlignment(Qt.AlignCenter)
        value.setMinimumWidth(44)
        for text, d in (("−", -1), (None, 0), ("+", 1)):
            if text is None:
                row.addWidget(value)
                continue
            btn = QPushButton(text)
            btn.setObjectName("text")
            btn.setFixedWidth(20)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(lambda _=False, d=d: step(d))
            row.addWidget(btn)
        return value

    def _capo(self, d):
        self.capo = min(max(self.capo + d, 0), 9)
        self._refresh()
        self.changed.emit()

    def _tone(self, d):
        self.transpose = min(max(self.transpose + d, -6), 6)
        self.suggest = guitar.capo_for(self.raw, self.transpose)
        self._refresh()
        self.changed.emit()

    def set_song(self, raw, downbeats, capo, transpose):
        self.raw = raw
        self.segments = guitar.tidy(raw)
        self.key_pc, self.key_alt = guitar.key_of(raw, alternative=True) if raw else ((0, False), None)
        self.capo, self.transpose = capo, transpose
        self.suggest = guitar.capo_for(raw, transpose) if raw else 0
        self.ticker.bars = np.asarray(downbeats, dtype=float)
        self.body.setVisible(bool(raw))
        self.empty.setVisible(not raw)
        self._refresh()

    def set_busy(self, text, idle):
        self.find_note.setText(text)
        self.find_btn.setEnabled(idle)

    def _refresh(self):
        shift = self.transpose - self.capo
        pc, minor = self.key_pc
        flat = guitar.flats(((pc + shift) % 12, minor))
        self.shapes = []
        for s in self.segments:
            c = guitar.parse(s["chord"])
            if c is None:
                self.shapes.append((s["start"], s["end"], None, None))
            else:
                self.shapes.append((s["start"], s["end"], guitar.name(c, shift, flat),
                                    guitar.fingering((c["root"] + shift) % 12, c["quality"])))
        self.ticker.items = [(a, b, n) for a, b, n, _ in self.shapes]
        key = guitar.key_name(self.key_pc, self.transpose) if self.raw else ""
        if key and self.key_alt:
            other = guitar.key_name(self.key_alt, self.transpose).split(" · ")[0]
            key += f", {t('или')} {other[0].lower()}{other[1:]}"
        self.key.setText(key)
        self.capo_value.setText(tf("{n} лад", n=self.capo) if self.capo else t("нет"))
        self.tone_value.setText(f"{self.transpose:+d}".replace("-", "−") if self.transpose else "0")
        self.capo_hint.setText(tf("удобнее — {n} лад", n=self.suggest))
        self.capo_hint.setVisible(bool(self.raw) and self.suggest > 0 and self.suggest != self.capo)
        self.current = None
        self.set_time(self.ticker.at)

    def set_time(self, at):
        self.ticker.at = at
        self.ticker.update()
        starts = [s[0] for s in self.shapes]
        i = max(int(np.searchsorted(starts, at, side="right")) - 1, 0) if starts else -1
        if i == self.current:
            return
        self.current = i
        # Сейчас звучащий аккорд и следующие по порядку, без повторов подряд.
        show = []
        for j in range(max(i, 0), len(self.shapes)):
            name, shape = self.shapes[j][2], self.shapes[j][3]
            if name is None or (show and show[-1][0] == name):
                continue
            show.append((name, shape, j == i))
            if len(show) == len(self.diagrams):
                break
        for d, item in zip(self.diagrams, show + [("", None, False)] * len(self.diagrams)):
            d.set(*item)


def _font(widget, px, weight=QFont.Normal):
    f = QFont(widget.font())
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def _line_at(lines, at):
    """Строка, которая поётся сейчас, или последняя спетая; до первой — -1."""
    starts = [ln["start"] for ln in lines]
    return int(np.searchsorted(starts, at + 0.15, side="right")) - 1


class Karaoke(QWidget):
    """Текст под звук: текущая строка крупно, спетое закрашивается по словам."""
    seek = Signal(float)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(176)
        self.lines = []
        self.at = 0.0
        self.current = -2

    def set_lines(self, lines):
        self.lines = lines
        self.current = -2
        self.update()

    def set_time(self, at):
        # Заливка, совпадающая со звуком точь-в-точь, кажется опоздавшей:
        # глаз ждёт слово чуть раньше, чем его слышно.
        self.at = at = at + 0.08
        i = _line_at(self.lines, at)
        if i != self.current or (0 <= i < len(self.lines) and at <= self.lines[i]["end"] + 0.2):
            self.current = i
            self.update()

    def _progress_x(self, line, fm, x0):
        """Докуда закрашена строка: целые спетые слова и доля текущего."""
        x, text = x0, ""
        for n, (s, e, w) in enumerate(line["words"]):
            word = (" " if n else "") + w
            left = fm.horizontalAdvance(text)
            text += word
            right = fm.horizontalAdvance(text)
            if self.at >= e:
                x = x0 + right
            elif self.at >= s:
                share = (self.at - s) / max(e - s, 0.05)
                lead = fm.horizontalAdvance(" ") if n else 0
                x = x0 + left + lead + (right - left - lead) * share
                break
            else:
                break
        return x

    def _fit(self, text, px, weight, width):
        f = _font(self, px, weight)
        while px > 13 and QFontMetricsF(f).horizontalAdvance(text) > width:
            px -= 1
            f = _font(self, px, weight)
        return f

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if not self.lines:
            return
        i = max(self.current, -1)
        rows = [(i - 1, 16, QFont.Normal, 36), (i, 27, QFont.DemiBold, 84), (i + 1, 17, QFont.Medium, 128),
                (i + 2, 15, QFont.Normal, 158)]
        for n, px, weight, y in rows:
            if not 0 <= n < len(self.lines):
                continue
            line = self.lines[n]
            text = " ".join(word for _, _, word in line["words"])
            f = self._fit(text, px, weight, w - 40)
            p.setFont(f)
            fm = QFontMetricsF(f)
            x0 = (w - fm.horizontalAdvance(text)) / 2
            base = y + fm.ascent() / 2 - 2
            if n != i:
                p.setPen(QColor(FAINT if n < i else MUTED))
                p.drawText(QPointF(x0, base), text)
                continue
            p.setPen(QColor(MUTED))
            p.drawText(QPointF(x0, base), text)
            sung = self._progress_x(line, fm, x0)
            if sung > x0:
                p.save()
                p.setClipRect(QRectF(0, 0, sung, h))
                path = QPainterPath()
                path.addText(QPointF(x0, base), f, text)
                p.fillPath(path, gradient(x0, 0, x0 + fm.horizontalAdvance(text), 0,
                                          ((0, WARM[0]), (1, WARM[1]))))
                p.restore()

    def mousePressEvent(self, e):
        i = max(self.current, -1)
        n = i + (-1 if e.position().y() < 56 else 0 if e.position().y() < 110 else 1)
        if 0 <= n < len(self.lines):
            self.seek.emit(self.lines[n]["start"])


class ChordSheet(QWidget):
    """Текст с аккордами над словами, как в песенниках: аккорд стоит над
    словом, на котором вступает; между куплетами — строки одних аккордов."""
    seek = Signal(float)
    PAD = 10

    def __init__(self):
        super().__init__()
        self.rows = []              # [(начало, конец, [(x, аккорд, время)], текст, [(x, слово, время)])]
        self.lines, self.chords = [], []
        self.at = 0.0
        self.current = -1
        self.setMouseTracking(True)

    def set_data(self, lines, chords):
        self.lines, self.chords = lines, [c for c in chords if c[2]]
        self._layout()

    def _layout(self):
        cf, tf_ = _font(self, 13, QFont.DemiBold), _font(self, 15)
        cm, tm = QFontMetricsF(cf), QFontMetricsF(tf_)
        rows, ci = [], 0
        chords = self.chords

        def chord_row(a, b):
            nonlocal ci
            items, x = [], 0.0
            while ci < len(chords) and chords[ci][0] < b:
                if chords[ci][0] >= a - 0.05 and (not items or items[-1][1] != chords[ci][2]):
                    items.append((x, chords[ci][2], chords[ci][0]))
                    x += cm.horizontalAdvance(chords[ci][2]) + 18
                ci += 1
            return items

        for n, line in enumerate(self.lines):
            nxt = self.lines[n + 1]["start"] if n + 1 < len(self.lines) else float("inf")
            gap_start = self.lines[n - 1]["end"] if n else 0.0
            # Проигрыш перед строкой — отдельной строкой аккордов, если в нём что-то звучит.
            if line["start"] - gap_start > 2.5:
                items = chord_row(gap_start, line["start"] - 0.3)
                for k in range(0, len(items), 8):
                    part = items[k:k + 8]
                    shift = part[0][0]
                    rows.append((part[0][2], line["start"], [(x - shift, c, s) for x, c, s in part], "", []))
            words, x = [], 0.0
            for s, _, w in line["words"]:
                words.append((x, w, s))
                x += tm.horizontalAdvance(w + " ")
            text = " ".join(w for _, w, _ in words)
            items, last = [], -1e9
            while ci < len(chords) and chords[ci][0] < nxt - 0.3:
                c_at, name = chords[ci][0], chords[ci][2]
                ci += 1
                if items and items[-1][1] == name:
                    continue
                pos = 0.0
                for wx, _, ws in words:
                    if ws <= c_at + 0.1:
                        pos = wx
                pos = max(pos, last)
                items.append((pos, name, c_at))
                last = pos + cm.horizontalAdvance(name) + 8
            rows.append((line["start"], nxt, items, text, words))
        rest = chord_row(self.lines[-1]["end"] if self.lines else 0.0, float("inf"))
        for k in range(0, len(rest), 8):
            part = rest[k:k + 8]
            shift = part[0][0]
            rows.append((part[0][2], float("inf"), [(x - shift, c, s) for x, c, s in part], "", []))
        self.rows = rows
        self.row_h = [(20 if r[2] else 0) + (24 if r[3] else 0) + 8 for r in rows]
        self.setFixedHeight(int(sum(self.row_h)) + 2 * self.PAD)
        self.current = -1
        self.update()

    def row_top(self, n):
        return self.PAD + sum(self.row_h[:n])

    def set_time(self, at):
        self.at = at
        starts = [r[0] for r in self.rows]
        i = int(np.searchsorted(starts, at + 0.15, side="right")) - 1
        if i != self.current:
            self.current = i
            self.update()
            return True
        return False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cf, tf_ = _font(self, 13, QFont.DemiBold), _font(self, 15)
        y = self.PAD
        x0 = 14
        for n, (_, _, items, text, _) in enumerate(self.rows):
            h = self.row_h[n]
            now = n == self.current
            if now:
                p.setPen(Qt.NoPen)
                p.setBrush(ink(10))
                p.drawRoundedRect(QRectF(2, y - 2, self.width() - 4, h - 2), 8, 8)
            cy = y
            if items:
                p.setFont(cf)
                for x, name, s in items:
                    playing = now and s <= self.at
                    p.setPen(QColor(WARM[1] if playing else WARM[0]))
                    p.drawText(QPointF(x0 + x, cy + 14), name)
                cy += 20
            if text:
                p.setFont(tf_)
                p.setPen(QColor(TEXT if now or n > self.current else MUTED))
                p.drawText(QPointF(x0, cy + 17), text)
            y += h

    def mousePressEvent(self, e):
        y = e.position().y()
        for n in range(len(self.rows)):
            if self.row_top(n) <= y < self.row_top(n + 1):
                self.seek.emit(self.rows[n][0])
                return


class LyricsPanel(QWidget):
    """Текст песни: караоке или текст с аккордами."""
    seek = Signal(float)
    find = Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 12)
        v.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.mode_btns = {}
        group = QButtonGroup(self)
        for key, text in (("karaoke", "Караоке"), ("chords", "С аккордами")):
            b = QPushButton(t(text))
            b.setObjectName("opt")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            group.addButton(b)
            row.addWidget(b)
            self.mode_btns[key] = b
        row.addSpacing(14)
        self.source = QLabel("")
        self.source.setObjectName("faint")
        row.addWidget(self.source)
        row.addStretch()
        v.addLayout(row)
        self.stack = QStackedWidget()
        self.karaoke = Karaoke()
        self.karaoke.seek.connect(self.seek)
        self.sheet = ChordSheet()
        self.sheet.seek.connect(self.seek)
        self.sheet_scroll = QScrollArea()
        self.sheet_scroll.setWidgetResizable(True)
        self.sheet_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sheet_scroll.setFixedHeight(300)
        self.sheet_scroll.setWidget(self.sheet)
        self.sheet_scroll.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.stack.addWidget(self.karaoke)
        self.stack.addWidget(self.sheet_scroll)
        v.addWidget(self.stack)
        self.empty = QWidget()
        e = QHBoxLayout(self.empty)
        e.setContentsMargins(0, 0, 0, 0)
        self.find_btn = GradientButton(t("Найти текст"))
        self.find_btn.clicked.connect(self.find)
        e.addWidget(self.find_btn)
        self.find_note = QLabel("")
        self.find_note.setObjectName("sub")
        e.addSpacing(12)
        e.addWidget(self.find_note)
        e.addStretch()
        v.addWidget(self.empty)
        self.touched = 0.0          # когда прокручивали руками: лист пару секунд не тянется за песней
        self.lines = []
        self.set_mode(self.settings.value("lyrics_mode", "karaoke"))
        self.set_song(None, [])

    def set_mode(self, key):
        key = key if key in self.mode_btns else "karaoke"
        self.mode_btns[key].setChecked(True)
        self.stack.setCurrentIndex(0 if key == "karaoke" else 1)
        self.settings.setValue("lyrics_mode", key)

    def set_song(self, lyrics, chords):
        self.lines = (lyrics or {}).get("lines", [])
        has = bool(self.lines)
        self.stack.setVisible(has)
        for b in self.mode_btns.values():
            b.setVisible(has)
        self.source.setText({"lrclib": t("текст — LRCLIB"), "whisper": t("текст распознан по голосу")}
                            .get((lyrics or {}).get("source"), "") if has else "")
        self.empty.setVisible(not has)
        self.karaoke.set_lines(self.lines)
        self.set_chords(chords)

    def set_chords(self, chords):
        self.sheet.set_data(self.lines, chords)

    def set_busy(self, text, idle):
        self.find_note.setText(text)
        self.find_btn.setEnabled(idle)

    def _scrolled(self, _):
        if not getattr(self, "_auto", False):
            self.touched = time.monotonic()

    def set_time(self, at):
        if self.stack.currentIndex() == 0:
            self.karaoke.set_time(at)
            return
        if self.sheet.set_time(at) and time.monotonic() - self.touched > 3 and self.sheet.current >= 0:
            top = self.sheet.row_top(self.sheet.current)
            bar = self.sheet_scroll.verticalScrollBar()
            want = int(top - self.sheet_scroll.height() / 3)
            self._auto = True
            bar.setValue(max(0, min(want, bar.maximum())))
            self._auto = False


SPEC_STOPS = ((0.0, (0, 0, 4)), (0.13, (28, 16, 68)), (0.25, (79, 18, 123)), (0.38, (129, 37, 129)),
              (0.5, (181, 54, 122)), (0.63, (229, 80, 100)), (0.75, (251, 135, 97)), (0.88, (254, 194, 135)),
              (1.0, (252, 253, 191)))
NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def spec_table():
    """Палитра magma: тишина — чёрная, громкое — светло-жёлтое."""
    out = []
    for k in range(256):
        x = k / 255
        for (a, ca), (b, cb) in zip(SPEC_STOPS, SPEC_STOPS[1:]):
            if a <= x <= b:
                f = (x - a) / (b - a)
                r, g, bl = (int(ca[j] + (cb[j] - ca[j]) * f) for j in range(3))
                out.append(0xFF000000 | (r << 16) | (g << 8) | bl)
                break
    return out


class SpecJob(QThread):
    done = Signal(object, object)

    def __init__(self, key, data):
        super().__init__()
        self.key, self.data = key, data
        self.stop = False

    def run(self):
        img = engine.spectrogram(self.data, lambda: self.stop)
        if img is not None:
            self.done.emit(self.key, img)


class Spectrum(QWidget):
    """Спектрограмма дорожки: частоты по логарифмической шкале, колесо —
    масштаб по времени, перетаскивание — сдвиг, щелчок — перемотка."""
    seek = Signal(float)
    AXIS = 46
    TIME = 22

    def __init__(self):
        super().__init__()
        self.setFixedHeight(280)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.img = None
        self.pixels = None
        self.duration = 0.0
        self.v0, self.v1 = 0.0, 0.0
        self.at = 0.0
        self.hover = None
        self.press = None
        self.note = ""
        self.table = spec_table()

    def set_image(self, pixels, duration):
        self.pixels = pixels
        if pixels is None:
            self.img = None
        else:
            h, w = pixels.shape
            self.img = QImage(pixels.data, w, h, w, QImage.Format_Indexed8)
            self.img.setColorTable(self.table)
        if duration != self.duration:
            self.duration = duration
            self.v0, self.v1 = 0.0, duration
        self.update()

    def _plot(self):
        return QRectF(self.AXIS, 4, self.width() - self.AXIS - 6, self.height() - self.TIME - 8)

    def _x(self, t):
        r = self._plot()
        return r.left() + (t - self.v0) / max(self.v1 - self.v0, 1e-6) * r.width()

    def _t(self, x):
        r = self._plot()
        return self.v0 + (x - r.left()) / max(r.width(), 1) * (self.v1 - self.v0)

    def _freq(self, y):
        r = self._plot()
        share = 1 - (y - r.top()) / max(r.height(), 1)
        return engine.SPEC_FMIN * (engine.SPEC_FMAX / engine.SPEC_FMIN) ** share

    def _y(self, f):
        r = self._plot()
        share = math.log(f / engine.SPEC_FMIN) / math.log(engine.SPEC_FMAX / engine.SPEC_FMIN)
        return r.bottom() - share * r.height()

    def set_time(self, at, playing):
        self.at = at
        span = self.v1 - self.v0
        if playing and span < self.duration - 0.01 and not (self.v0 <= at <= self.v1):
            self.v0 = max(0.0, min(at - span * 0.1, self.duration - span))
            self.v1 = self.v0 + span
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 4))
        p.drawRoundedRect(r, 6, 6)
        f = _font(self, 10)
        p.setFont(f)
        if self.img is None or not self.duration:
            p.setPen(QColor(MUTED))
            p.drawText(r, Qt.AlignCenter, self.note)
            return
        cols = self.img.width()
        a = self.v0 / self.duration * cols
        b = self.v1 / self.duration * cols
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(r, 6, 6)
        p.setClipPath(clip)
        ratio = self.devicePixelRatioF()
        key = (round(self.v0, 4), round(self.v1, 4), int(r.width()), int(r.height()), id(self.img), ratio)
        if getattr(self, "_cache_key", None) != key:
            part = self.img.copy(int(a), 0, max(int(b - a), 1), self.img.height()).convertToFormat(QImage.Format_RGB32)
            part = part.scaled(int(r.width() * ratio), int(r.height() * ratio), Qt.IgnoreAspectRatio,
                               Qt.SmoothTransformation)
            self._cache = QPixmap.fromImage(part)
            self._cache.setDevicePixelRatio(ratio)
            self._cache_key = key
        p.drawPixmap(r.topLeft(), self._cache)
        grid = QColor(255, 255, 255, 34)
        p.setPen(QPen(grid, 1))
        for fq in (50, 100, 200, 500, 1000, 2000, 5000, 10000):
            p.drawLine(QPointF(r.left(), self._y(fq)), QPointF(r.right(), self._y(fq)))
        x = self._x(self.at)
        p.fillRect(QRectF(x - 0.75, r.top(), 1.5, r.height()), QColor(255, 255, 255, 220))
        if self.hover is not None and r.contains(self.hover):
            p.setPen(QPen(QColor(255, 255, 255, 90), 1, Qt.DashLine))
            p.drawLine(QPointF(self.hover.x(), r.top()), QPointF(self.hover.x(), r.bottom()))
            p.drawLine(QPointF(r.left(), self.hover.y()), QPointF(r.right(), self.hover.y()))
        p.restore()
        p.setPen(QColor(MUTED))
        for fq, label in ((50, "50"), (100, "100"), (200, "200"), (500, "500"), (1000, "1k"), (2000, "2k"),
                          (5000, "5k"), (10000, "10k")):
            p.drawText(QRectF(0, self._y(fq) - 7, self.AXIS - 6, 14), Qt.AlignRight | Qt.AlignVCenter, label)
        p.drawText(QRectF(0, r.top() - 2, self.AXIS - 6, 14), Qt.AlignRight | Qt.AlignVCenter, t("Гц"))
        span = self.v1 - self.v0
        step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120) if span / s <= 12)
        tick = math.ceil(self.v0 / step) * step
        while tick <= self.v1:
            x = self._x(tick)
            label = f"{int(tick) // 60}:{tick % 60:04.1f}" if step < 1 else clock(tick)
            p.drawText(QRectF(x - 30, r.bottom() + 3, 60, 14), Qt.AlignCenter, label)
            tick += step
        if self.hover is not None and r.contains(self.hover) and self.pixels is not None:
            at, fq = self._t(self.hover.x()), self._freq(self.hover.y())
            col = min(int(at / self.duration * cols), cols - 1)
            row = min(max(int((self.hover.y() - r.top()) / r.height() * self.img.height()), 0), self.img.height() - 1)
            db = self.pixels[row, max(col, 0)] / 255 * engine.SPEC_RANGE - engine.SPEC_RANGE
            midi = 69 + 12 * math.log2(fq / 440)
            note = f"{NOTES[int(round(midi)) % 12]}{int(round(midi)) // 12 - 1}"
            text = f"{clock(at)}.{int(at * 10) % 10}  ·  {fq:,.0f} {t('Гц')}  ·  {note}  ·  {db:.0f} {t('дБ')}".replace(",", " ")
            fm = p.fontMetrics()
            box = QRectF(r.right() - fm.horizontalAdvance(text) - 18, r.top() + 6, fm.horizontalAdvance(text) + 12, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 160))
            p.drawRoundedRect(box, 5, 5)
            p.setPen(QColor(255, 255, 255, 230))
            p.drawText(box, Qt.AlignCenter, text)

    def wheelEvent(self, e):
        if not self.duration:
            return
        d = e.angleDelta()
        if abs(d.x()) > abs(d.y()):
            shift = -d.x() / 120 * (self.v1 - self.v0) * 0.1
            self._pan(shift)
            return
        at = self._t(e.position().x())
        k = 0.8 ** (d.y() / 120)
        span = min(max((self.v1 - self.v0) * k, 1.0), self.duration)
        share = (at - self.v0) / max(self.v1 - self.v0, 1e-6)
        self.v0 = at - share * span
        self.v1 = self.v0 + span
        self._pan(0)

    def _pan(self, shift):
        span = self.v1 - self.v0
        self.v0 = min(max(self.v0 + shift, 0.0), max(self.duration - span, 0.0))
        self.v1 = self.v0 + span
        self.update()

    def mousePressEvent(self, e):
        self.press = (e.position().x(), self.v0, False)

    def mouseMoveEvent(self, e):
        self.hover = e.position()
        if self.press is not None and e.buttons() & Qt.LeftButton:
            x0, v0, _ = self.press
            dx = e.position().x() - x0
            if abs(dx) > 3:
                self.press = (x0, v0, True)
                span = self.v1 - self.v0
                self.v0 = v0 - dx / max(self._plot().width(), 1) * span
                self.v1 = self.v0 + span
                self._pan(0)
                return
        self.update()

    def mouseReleaseEvent(self, e):
        if self.press is not None and not self.press[2] and self._plot().contains(e.position()):
            self.seek.emit(max(self._t(e.position().x()), 0.0))
        self.press = None

    def mouseDoubleClickEvent(self, e):
        self.v0, self.v1 = 0.0, self.duration
        self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()


class SpectrumPanel(QWidget):
    seek = Signal(float)
    pick = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 12)
        v.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(6)
        cap = QLabel(t("Спектрограмма"))
        cap.setObjectName("faint")
        row.addWidget(cap)
        self.track_btn = QPushButton("")
        self.track_btn.setObjectName("text")
        self.track_btn.setCursor(Qt.PointingHandCursor)
        self.track_btn.setFocusPolicy(Qt.NoFocus)
        self.track_btn.clicked.connect(self.pick)
        row.addWidget(self.track_btn)
        row.addStretch()
        v.addLayout(row)
        self.view = Spectrum()
        self.view.seek.connect(self.seek)
        v.addWidget(self.view)


class LyricsJob(QThread):
    """Текст песни со временем слов."""
    stage = Signal(str, object)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, folder: Path):
        super().__init__()
        self.setStackSize(STACK)
        self.folder = folder
        self.stop = False

    def run(self):
        try:
            self.stage.emit("Текст", None)
            info = engine.load_info(self.folder)
            def progress(kind, share):
                if self.stop:
                    raise engine.Stopped
                self.stage.emit("Загрузка модели" if kind == "download" else "Текст", share)

            found = engine.lyrics(self.folder, info, progress)
            engine.free_memory()
            engine.update_info(self.folder, lambda info: info.__setitem__("lyrics", found))
            self.done.emit(str(self.folder))
        except Exception:
            self.failed.emit(traceback.format_exc(limit=4))


class PlayButton(QWidget):
    clicked = Signal()

    def __init__(self, size=44):
        super().__init__()
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.playing = False
        self.hover = False
        self.spin = Spin(self)
        self.pulse = 0.0            # удар песни: 1 — сильная доля только что, гаснет за ~0,3 с

    def set_playing(self, on):
        self.playing = on
        self.spin.set(on)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.width()
        p.setPen(Qt.NoPen)
        p.setBrush(gradient(0, 0, s, s))
        p.drawEllipse(QRectF(0, 0, s, s))
        circle = QPainterPath()
        circle.addEllipse(QRectF(0, 0, s, s))
        paint_flow(p, circle, s / 2, s / 2, s / 2, self.spin)
        if self.pulse > 0.01 and self.spin.amount > 0:
            flash = QRadialGradient(s / 2, s / 2, s / 2)
            core, rim = QColor(255, 255, 255, int(170 * self.pulse * self.spin.amount)), QColor(255, 255, 255, 0)
            flash.setColorAt(0, core)
            flash.setColorAt(1, rim)
            p.setBrush(flash)
            p.drawEllipse(QRectF(0, 0, s, s))
        if self.hover:
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawEllipse(QRectF(0, 0, s, s))
        p.setBrush(QColor(DARK))
        c = s / 2
        if self.playing:
            p.drawRoundedRect(QRectF(c - 6.5, c - 7.5, 4.5, 15), 1.5, 1.5)
            p.drawRoundedRect(QRectF(c + 2, c - 7.5, 4.5, 15), 1.5, 1.5)
        else:
            p.drawPolygon(QPolygonF([QPointF(c - 4.5, c - 8), QPointF(c + 8.5, c), QPointF(c - 4.5, c + 8)]))

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class GradientButton(QPushButton):
    """Главная кнопка: тёплая половина градиента."""

    def __init__(self, text):
        super().__init__(text)
        self.setFixedHeight(34)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 40, 34)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(1.0 if self.isEnabled() else 0.35)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(gradient(0, 0, r.width(), 0, ((0, WARM[0]), (1, WARM[1]))))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self.underMouse() and self.isEnabled():
            p.setBrush(QColor(255, 255, 255, 34))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        f = QFont(self.font())
        f.setPixelSize(13)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(DARK))
        p.drawText(r, Qt.AlignCenter, self.text())


class Metronome(QPushButton):
    """«Метроном» с точкой, которая вспыхивает на ударах."""

    def __init__(self):
        super().__init__(t("Метроном"))
        self.setObjectName("text")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("padding-left: 16px;")
        self.flash = 0.0

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(6, self.height() / 2)
        if not self.isChecked():
            p.setPen(QPen(QColor(FAINT), 1.3))
            p.drawEllipse(c, 3.5, 3.5)
            return
        p.setPen(Qt.NoPen)
        color = QColor(WARM[1])
        color.setAlphaF(0.45 + 0.55 * self.flash)
        p.setBrush(color)
        p.drawEllipse(c, 3.5 + self.flash, 3.5 + self.flash)


class Thread(QWidget):
    """Тонкая полоса хода работы: доля или бегущий отрезок."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(2)
        self.value = None
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)

    def set(self, value):
        self.value = value
        if value is None and self.isVisible():
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def showEvent(self, e):
        self.set(self.value)

    def hideEvent(self, e):
        self.timer.stop()

    def _tick(self):
        self.phase = (self.phase + 0.01) % 1.3
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        w = self.width()
        p.fillRect(QRectF(0, 0, w, 2), ink(14))
        brush = gradient(0, 0, w, 0)
        if self.value is None:
            x = (self.phase - 0.3) * w
            p.fillRect(QRectF(max(x, 0), 0, min(x + w * 0.3, w) - max(x, 0), 2), brush)
        else:
            p.fillRect(QRectF(0, 0, w * min(self.value, 1), 2), brush)


class NewSong(QWidget):
    """Верх левой колонки: «Новая песня», а пока идёт разделение — его ход."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(48)
        self.setCursor(Qt.PointingHandCursor)
        self.status = ""
        self.hover = False
        self.share = 0.0
        self.spin = Spin(self)

    def set_status(self, text, share=0.0):
        self.status, self.share = text, share or 0.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if self.hover:
            p.setPen(Qt.NoPen)
            p.setBrush(ink(9))
            p.drawRoundedRect(r, 8, 8)
        paint_orb(p, ORB_X, self.height() / 2, 9, 9 * (0.1 + 0.4 * self.share), self.spin)
        if self.width() < 100:
            return
        f = QFont(self.font())
        f.setPixelSize(13)
        f.setWeight(QFont.Medium)
        p.setFont(f)
        p.setPen(QColor(TEXT))
        if self.status:
            p.drawText(QRectF(TEXT_X, 7, r.width() - TEXT_X - 4, 18), Qt.AlignVCenter, t("Новая песня"))
            f.setPixelSize(11)
            f.setWeight(QFont.Normal)
            p.setFont(f)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(TEXT_X, 25, r.width() - TEXT_X - 4, 16), Qt.AlignVCenter, self.status)
        else:
            p.drawText(QRectF(TEXT_X, 0, r.width() - TEXT_X - 4, self.height()), Qt.AlignVCenter,
                       t("Новая песня"))

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class SideToggle(QWidget):
    """Свернуть и развернуть левую колонку: значок боковой панели, как в Finder."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.hover = False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.hover:
            p.setPen(Qt.NoPen)
            p.setBrush(ink(14))
            p.drawRoundedRect(QRectF(self.rect()), 7, 7)
        c = QColor(TEXT if self.hover else MUTED)
        box = QRectF(7.5, 7.5, 13, 13)
        p.setPen(QPen(c, 1.3))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box, 2.5, 2.5)
        p.drawLine(QPointF(12, 8), QPointF(12, 20))

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class HistoryDelegate(QStyledItemDelegate):
    def __init__(self, family):
        super().__init__()
        self.family = family

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 48)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.State_Selected)
        if option.state & QStyle.State_MouseOver and not selected:
            p.setPen(Qt.NoPen)
            p.setBrush(ink(9))
            p.drawRoundedRect(r, 8, 8)
        if selected:
            p.setPen(Qt.NoPen)
            x = option.rect.left() + ORB_X
            p.setBrush(gradient(x - 4, r.center().y() - 4, x + 4, r.center().y() + 4))
            p.drawEllipse(QPointF(x, r.center().y()), 3.5, 3.5)
        f = QFont(self.family)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QColor(TEXT if selected else SOFT))
        left = option.rect.left() + TEXT_X
        width = int(r.right() - left - 6)
        title = p.fontMetrics().elidedText(index.data(Qt.DisplayRole), Qt.ElideRight, width)
        p.drawText(QRectF(left, r.top() + 6, width, 18), Qt.AlignVCenter, title)
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(left, r.top() + 24, width, 16), Qt.AlignVCenter,
                   index.data(Qt.UserRole + 1) or "")
        p.restore()


class History(QListWidget):
    """Список песен; края гаснут, когда есть что прокрутить."""

    def paintEvent(self, e):
        super().paintEvent(e)
        bar = self.verticalScrollBar()
        p = QPainter(self.viewport())
        w, h = self.viewport().width(), self.viewport().height()
        for show, y0, y1 in ((bar.value() > 0, 0, 28), (bar.value() < bar.maximum(), h, h - 28)):
            if show:
                g = QLinearGradient(0, y0, 0, y1)
                g.setColorAt(0, QColor(BG))
                c = QColor(BG)
                c.setAlpha(0)
                g.setColorAt(1, c)
                p.fillRect(QRectF(0, min(y0, y1), w, 28), g)


class SplitJob(QThread):
    stage = Signal(str, object)     # текст, доля (None — без доли)
    done = Signal(str)
    failed = Signal(str)
    needs_access = Signal(str)

    def __init__(self, source, link, title):
        super().__init__()
        self.setStackSize(STACK)
        self.source, self.link, self.title = source, link, title
        self.stop = False

    def run(self):
        folder = None
        try:
            WORK.mkdir(parents=True, exist_ok=True)
            source, title = self.source, self.title
            if self.link:
                self.stage.emit("Скачивание", 0.0)
                source, title = engine.download(self.link, WORK / "links",
                                                lambda f: self.stage.emit("Скачивание", f),
                                                lambda: self.stop)
            folder = unique(OUT_DIR / safe_name(title))
            folder.mkdir(parents=True)
            self.stage.emit("Подготовка", None)
            wav = engine.decode(source, folder / f"{engine.default_file('original')}.wav")

            def progress(kind, share):
                self.stage.emit("Загрузка модели" if kind == "download" else "Разделение", share)

            self.stage.emit("Разделение", None)
            started = time.time()
            engine.separate(wav, folder, progress)
            took = time.time() - started
            engine.free_memory()
            if self.stop:
                raise RuntimeError("отменено")
            self.stage.emit("Темп", None)
            beat = engine.tempo(wav)
            engine.free_memory()
            self.stage.emit("Аккорды", None)
            found = engine.chords(engine.track(folder, "music"))
            engine.free_memory()
            import soundfile as sf
            engine.save_info(folder, {
                "title": title, "source": self.link or str(self.source), "took": round(took, 1),
                "duration": round(sf.info(str(wav)).duration, 2), "chords": found, **beat})
            if self.stop:
                raise RuntimeError("отменено")
            self.done.emit(str(folder))
        except Exception as e:
            # Отменённое или сорвавшееся разделение не оставляет полупустую папку.
            if folder is not None and not (folder / engine.INFO).exists():
                shutil.rmtree(folder, ignore_errors=True)
            if self.stop:
                return
            if isinstance(e, links.NeedsAccess):
                self.needs_access.emit(str(e))
            if isinstance(e, links.SourceError):
                self.failed.emit("SourceError: " + str(e))
            else:
                self.failed.emit(traceback.format_exc(limit=4))


class StemJob(QThread):
    """Одну дорожку — на части: голос, музыку или барабаны."""
    stage = Signal(str, object)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, folder: Path, parent: str, mode: str):
        super().__init__()
        self.setStackSize(STACK)
        self.folder, self.parent, self.mode = folder, parent, mode
        self.stop = False

    def run(self):
        try:
            def progress(kind, share):
                if self.stop:
                    raise engine.Stopped
                self.stage.emit({"download": "Загрузка модели", "timbre": "По тембру"}.get(kind, "Раскладка"),
                                share)

            self.stage.emit("Раскладка", None)
            info = engine.load_info(self.folder)
            mode, _, count = self.mode.partition(":")
            runs = None
            if mode == "singers":
                keys, names, files = engine.split_singers(self.folder, self.parent, info, progress,
                                                          int(count or 0))
                runs = info.get("singer_runs", {}).get(self.parent)
                none = "Поёт один исполнитель"
            elif mode == "timbre":
                keys, names, files = engine.split_timbre(self.folder, self.parent, info, progress,
                                                         int(count or 0))
                none = "Один инструмент"
            elif mode == "channels":
                keys, names, files = engine.split_channels(self.folder, self.parent, info)
                none = "Каналы одинаковые"
            else:
                keys, names, files = engine.split(self.folder, self.parent, progress)
                none = engine.SPLITS[self.parent]["none"]
            engine.free_memory()

            def change(info):
                if keys:
                    info.setdefault("splits", {})[self.parent] = keys
                    info.setdefault("names", {}).update(names)
                    info.setdefault("files", {}).update(files)
                    if runs is not None:
                        info.setdefault("singer_runs", {})[self.parent] = runs
                        info.get("nosplit", {}).pop(f"{self.parent}:singers", None)
                    if "other" in keys:
                        # Тембр у остатка один — делить его ещё раз незачем.
                        info.setdefault("nosplit", {})["other:timbre"] = "Один инструмент"
                elif not count:
                    info.setdefault("nosplit", {})[f"{self.parent}:{mode}"] = none

            engine.update_info(self.folder, change)
            self.done.emit(str(self.folder))
        except Exception:
            self.failed.emit(traceback.format_exc(limit=4))


class ChordsJob(QThread):
    """Аккорды для песни, разделённой до того, как они появились."""
    stage = Signal(str, object)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, folder: Path):
        super().__init__()
        self.setStackSize(STACK)
        self.folder = folder
        self.stop = False

    def run(self):
        try:
            self.stage.emit("Аккорды", None)
            src = engine.track(self.folder, "music")
            found = engine.chords(src if src.exists() else engine.track(self.folder, "original"))
            engine.free_memory()
            engine.update_info(self.folder, lambda info: info.__setitem__("chords", found))
            self.done.emit(str(self.folder))
        except Exception:
            self.failed.emit(traceback.format_exc(limit=4))


class ExportJob(QThread):
    """Сохранение: [(файл, [(wav, громкость)])]. Сведение и MP3 — секунды на песню."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, items):
        super().__init__()
        self.items = items

    def run(self):
        try:
            self.done.emit([engine.export(parts, dst) for dst, parts in self.items])
        except Exception as e:
            self.failed.emit(str(e) or type(e).__name__)


class VoiceJob(QThread):
    """Образец → чистый голос → Seed-VC отдельным процессом → кавер с музыкой."""
    stage = Signal(str, object)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, folder: Path, reference: Path, steps: int, shift: int):
        super().__init__()
        self.setStackSize(STACK)
        self.folder, self.reference, self.steps, self.shift = folder, reference, steps, shift
        self.stop = False

    def run(self):
        try:
            work = WORK / "reference"
            shutil.rmtree(work, ignore_errors=True)
            self.stage.emit("Образец голоса", None)
            ref = engine.reference_voice(self.reference, work)
            engine.free_memory()
            name = safe_name(self.reference.stem)
            voice, mix = (("Voice", "Cover") if i18n.current() == "en" else ("Голос", "Кавер"))
            out = unique(self.folder / f"{voice} — {name}.wav")
            cover = self.folder / out.name.replace(f"{voice} — ", f"{mix} — ", 1)

            def progress(kind, share):
                self.stage.emit("Модели голоса" if kind == "models" else "Новый голос", share)

            vocals = engine.track(self.folder, "vocals")
            engine.change_voice(vocals, ref, out, self.steps, self.shift, progress, lambda: self.stop)
            self.stage.emit("Кавер", None)
            engine.make_cover(out, vocals, engine.track(self.folder, "music"), cover)
            info = engine.load_info(self.folder)
            info.setdefault("voices", []).append({
                "file": out.name, "cover": cover.name, "name": self.reference.stem,
                "steps": self.steps, "shift": self.shift})
            engine.save_info(self.folder, info)
            self.done.emit(str(self.folder))
        except Exception:
            if not self.stop:
                self.failed.emit(traceback.format_exc(limit=4))


def paint_gear(p, cx, cy, color):
    """Шестерёнка тем же контуром, что значок боковой панели."""
    body = QPainterPath()
    body.addEllipse(QPointF(cx, cy), 4.6, 4.6)
    for k in range(8):
        tooth = QPainterPath()
        tooth.addRoundedRect(QRectF(-1.35, -7.0, 2.7, 2.9), 0.5, 0.5)
        body = body.united(QTransform().translate(cx, cy).rotate(k * 45).map(tooth))
    hole = QPainterPath()
    hole.addEllipse(QPointF(cx, cy), 1.8, 1.8)
    p.setPen(QPen(color, 1.3))
    p.setBrush(Qt.NoBrush)
    p.drawPath(body.subtracted(hole))


class PrefsEntry(QWidget):
    """Низ левой колонки: «Настройки» — значок по той же вертикали, что круг
    «Новой песни», подпись — по линии названий песен."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(36)
        self.setCursor(Qt.PointingHandCursor)
        self.hover = False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if self.hover:
            p.setPen(Qt.NoPen)
            p.setBrush(ink(9))
            p.drawRoundedRect(r, 8, 8)
        c = QColor(TEXT if self.hover else MUTED)
        paint_gear(p, ORB_X, self.height() / 2, c)
        if self.width() < 100:
            return
        f = QFont(self.font())
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(c)
        p.drawText(QRectF(TEXT_X, 0, r.width() - TEXT_X - 4, self.height()), Qt.AlignVCenter, t("Настройки"))

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class SettingsWindow(QDialog):
    """Настройки своим окном, как у остальных приложений: группы строк в духе
    Severance — название слева, состояние и действия справа."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setObjectName("root")
        self.resize(540, 660)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("settings")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)

    def build(self):
        """Собирается заново при каждом открытии: места моделей и язык могли смениться."""
        import models_home
        import support
        self.setWindowTitle(t("Настройки"))
        keep = self.scroll.verticalScrollBar().value()
        inner = QWidget()
        inner.setObjectName("settingsInner")
        v = QVBoxLayout(inner)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(6)

        base = models_home.folder()
        off = "" if base is None or models_home.mounted(base) else t(" — недоступна")
        g = self._group(v, "Модели")
        reset = self._button(t("Сбросить"), lambda: self._folder(None)) if base else None
        self._row(g, t("Папка для моделей"), t("Куда ставятся новые модели"),
                  models_home.label(base) + off,
                  [b for b in (reset, self._button(t("Выбрать папку…"), self._pick)) if b])
        sep = engine.models_dir(engine.BEST_MODEL)
        voice = engine.voice_home()
        whisper = models_home.resolve(engine.WHISPER)
        for name, sub, where, ready in (
                (t("Разделение"), "BS-RoFormer, Mel-RoFormer, MDX23C, demucs",
                 models_home.label(sep), (sep / engine.BEST_MODEL).exists()),
                (t("Новый голос"), "Seed-VC", models_home.label(voice), (voice / "checkpoints").exists()),
                (t("Текст"), "Whisper large-v3", models_home.where(engine.WHISPER), whisper is not None)):
            self._row(g, name, sub, where if ready else tf("установится в {where}", where=where))

        g = self._group(v, "Доступ")
        self._row(g, t("Полный доступ к диску"), t("Для записей ВКонтакте, открытых в браузере"), "",
                  [self._button(t("Открыть настройки"), self.win.open_disk_access)])

        g = self._group(v, "Приложение")
        self._row(g, t("Язык"), "", "", self._options(
            (("ru", "Русский"), ("en", "English")), i18n.current(), self._lang))
        self._row(g, t("Оформление"), "", "", self._options(
            zip(THEMES, (t("Как в системе"), t("Светлое"), t("Тёмное"))), self.win.theme(), self._theme))

        g = self._group(v, "")
        self._row(g, t("Поддержать"), "", "", support.link_buttons(t("Скопировано"), "action"))

        v.addStretch(1)
        sign = QLabel(f'{APP} · {AUTHOR} · <a href="{URL}" style="color:{LINK}">{SITE}</a>')
        sign.setObjectName("faint")
        sign.setAlignment(Qt.AlignCenter)
        sign.setOpenExternalLinks(True)
        v.addWidget(sign)
        self.scroll.setWidget(inner)
        # Окно не уже содержимого: иначе правый край строк обрезался.
        need = inner.minimumSizeHint().width() + self.scroll.verticalScrollBar().sizeHint().width() + 2
        self.setMinimumWidth(need)
        if self.width() < need:
            self.resize(need, self.height())
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(keep))

    def _group(self, v, title):
        if v.count():
            v.addSpacing(14)
        if title:
            cap = QLabel(t(title))
            cap.setObjectName("faint")
            cap.setContentsMargins(4, 0, 0, 0)
            v.addWidget(cap)
        frame = QFrame()
        frame.setObjectName("group")
        box = QVBoxLayout(frame)
        box.setContentsMargins(16, 2, 14, 2)
        box.setSpacing(0)
        v.addWidget(frame)
        return box

    def _row(self, box, title, sub="", state="", widgets=()):
        if box.count():
            rule = QFrame()
            rule.setObjectName("rule")
            rule.setFixedHeight(1)
            box.addWidget(rule)
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 10)
        row.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(QLabel(title))
        if sub:
            s = QLabel(sub)
            s.setObjectName("sub")
            col.addWidget(s)
        row.addLayout(col, 1)
        if state:
            # Длинный путь сокращается посередине: строка не раздвигает окно.
            st = QLabel()
            st.setObjectName("sub")
            st.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            short = st.fontMetrics().elidedText(state, Qt.ElideMiddle, 210)
            st.setText(short)
            if short != state:
                st.setToolTip(state)
            row.addWidget(st)
        for w in widgets:
            row.addWidget(w)
        box.addLayout(row)

    def _button(self, text, fn):
        b = QPushButton(text)
        b.setObjectName("action")
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(fn)
        return b

    def _options(self, items, now, pick):
        group = QButtonGroup(self)
        out = []
        for key, label in items:
            b = QPushButton(label)
            b.setObjectName("opt")
            b.setCheckable(True)
            b.setChecked(key == now)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, k=key: pick(k))
            group.addButton(b)
            out.append(b)
        return out

    def _folder(self, path):
        import models_home
        models_home.set_folder(path)
        self.build()

    def _pick(self):
        import models_home
        path = QFileDialog.getExistingDirectory(self, t("Папка для моделей"),
                                                str(models_home.folder() or Path.home()))
        if path:
            self._folder(path)

    def _lang(self, code):
        self.win.set_language(code)
        self.build()

    def _theme(self, name):
        self.win.set_theme(name)
        self.build()


class FitJob(QThread):
    """Своя запись под исполнение оригинала → новая дорожка голоса и кавер."""
    stage = Signal(str, object)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, folder: Path, take: Path):
        super().__init__()
        self.setStackSize(STACK)
        self.folder, self.take = folder, take
        self.stop = False

    def run(self):
        try:
            stages = {"voice": "Голос записи", "align": "Подгонка по времени",
                      "analyse": "Разбор голоса", "render": "Новый голос"}
            name = safe_name(self.take.stem)
            voice, mix = (("Voice", "Cover") if i18n.current() == "en" else ("Голос", "Кавер"))
            out = unique(self.folder / f"{voice} — {name}.wav")
            cover = self.folder / out.name.replace(f"{voice} — ", f"{mix} — ", 1)
            lead = engine.track(self.folder, "lead")
            vocals = engine.track(self.folder, "vocals")
            engine.fit_voice(self.take, lead if lead.exists() else vocals, out, WORK / "take",
                             lambda kind, share: self.stage.emit(stages[kind], share), lambda: self.stop)
            engine.free_memory()
            self.stage.emit("Кавер", None)
            engine.make_cover(out, vocals, engine.track(self.folder, "music"), cover)
            info = engine.load_info(self.folder)
            info.setdefault("voices", []).append({"file": out.name, "cover": cover.name,
                                                  "name": self.take.stem, "fit": True})
            engine.save_info(self.folder, info)
            self.done.emit(str(self.folder))
        except Exception:
            if not self.stop:
                self.failed.emit(traceback.format_exc(limit=4))


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle(APP)
        self.setAcceptDrops(True)
        self.settings = QSettings("local", os.environ.get("SEVERANCE_SETTINGS", APP))
        g = self.settings.value("geometry")
        if g is not None:
            self.restoreGeometry(g)
        else:
            self.resize(1180, 760)
        self.setMinimumSize(960, 620)
        self.family = font_family()
        use_palette(self.skin())
        self.setStyleSheet(style(self.family))
        self.job = None
        self.job_kind = ""
        self.job_folder = None
        self.job_text = ""
        self.job_share = None
        self.job_started = 0.0
        self.alive = set()
        self.words_job = self.words_folder = None
        self.words_text = ""
        self.words_tried = set()
        self.words_share = None
        self.all_folder = None
        self.skipped = set()
        self.folder = None
        self.lanes = {}
        self.children = {}
        self.parent_of = {}
        self.nosplit = {}
        self.saved = {}             # папка → что звучало и с какой громкостью
        self.job_parent = None
        self.reference = None
        self.mix_gains = {}         # что звучит → громкость, множителем
        self.exporting = None
        self.singer_parents = {}    # дорожка → её части по исполнителям
        self.undo = []              # переносы кусков между исполнителями: что было до
        self.split_all_on = False
        self.mix_saver = QTimer(self)
        self.mix_saver.setSingleShot(True)
        self.mix_saver.setInterval(600)
        self.mix_saver.timeout.connect(self._save_mix)
        self.beat_times = np.zeros(0)
        self.strong_beats = set()
        self.player = Player()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        rail = QWidget()
        self.rail = rail
        rail.setFixedWidth(RAIL)
        rl = QVBoxLayout(rail)
        self.rail_box = rl
        rl.setContentsMargins(12, 10, 8, 12)
        rl.setSpacing(6)
        top = QHBoxLayout()
        top.setContentsMargins(ORB_X - 14, 0, 0, 0)
        self.rail_btn = SideToggle()
        self.rail_btn.clicked.connect(self.toggle_rail)
        top.addWidget(self.rail_btn)
        top.addStretch()
        rl.addLayout(top)
        self.new_song = NewSong()
        self.new_song.clicked.connect(self.show_start)
        rl.addWidget(self.new_song)
        self.history = History()
        self.history.setObjectName("history")
        self.history.setItemDelegate(HistoryDelegate(self.family))
        self.history.setMouseTracking(True)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.history.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history.customContextMenuRequested.connect(self._history_menu)
        self.history.itemClicked.connect(lambda it: self.open_result(Path(it.data(Qt.UserRole))))
        rl.addWidget(self.history, 1)
        rl.addStretch(0)            # свёрнутая колонка: без списка всё остаётся наверху
        self.prefs = PrefsEntry()
        self.prefs.clicked.connect(self.show_settings)
        rl.addWidget(self.prefs)
        self.settings_win = SettingsWindow(self)
        outer.addWidget(rail)
        line = QFrame()
        line.setFixedWidth(1)
        self.divider = line
        outer.addWidget(line)

        self.pages = QStackedWidget()
        self.start_page = self._build_start()
        self.work_page = self._build_work()
        self.result_page = self._build_result()
        for page in (self.start_page, self.work_page, self.result_page):
            self.pages.addWidget(page)
        outer.addWidget(self.pages, 1)

        self.clock = QTimer(self)
        self.clock.setTimerType(Qt.PreciseTimer)
        self.clock.setInterval(16)
        self.smooth = None          # (время песни, время часов) для плавного хода
        self.clock.timeout.connect(self._tick)
        self.clock.start()
        self._build_menu()
        self.apply_theme()
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _s: self.apply_theme())
        self.set_rail(self.settings.value("rail", True, type=bool))
        QTimer.singleShot(600, self._ask_access_once)
        self._fill_history()
        self.pages.setCurrentWidget(self.start_page)

    def _build_start(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(40, 30, 40, 40)
        v.setSpacing(0)
        v.addStretch(3)
        self.orb = Orb(250, clickable=True)
        self.orb.clicked.connect(self.choose)
        v.addWidget(self.orb, 0, Qt.AlignHCenter)
        v.addSpacing(22)
        hello = QLabel(t("Перетащите песню или видео"))
        hello.setObjectName("hello")
        hello.setAlignment(Qt.AlignCenter)
        v.addWidget(hello)
        v.addSpacing(2)
        pick = QPushButton(t("или выберите файл"))
        pick.setObjectName("text")
        pick.setCursor(Qt.PointingHandCursor)
        pick.setFocusPolicy(Qt.NoFocus)
        pick.clicked.connect(self.choose)
        v.addWidget(pick, 0, Qt.AlignHCenter)
        v.addSpacing(30)
        row = QGridLayout()
        row.setHorizontalSpacing(12)
        row.setColumnStretch(0, 1)
        row.setColumnStretch(2, 1)
        self.link = QLineEdit()
        self.link.setObjectName("link")
        self.link.setPlaceholderText(t("Ссылка: YouTube, VK, SoundCloud…"))
        self.link.setFixedWidth(400)
        self.link.textChanged.connect(lambda t: self.link_go.setVisible(bool(t.strip())))
        self.link.returnPressed.connect(self.start_link)
        # Пустая колонка отступа не получает — пустышка нулевой ширины уравнивает края.
        row.addWidget(QWidget(), 0, 0)
        row.addWidget(self.link, 0, 1)
        self.link_go = QPushButton(t("Разделить"))
        self.link_go.setObjectName("text")
        self.link_go.setCursor(Qt.PointingHandCursor)
        self.link_go.setFocusPolicy(Qt.NoFocus)
        self.link_go.clicked.connect(self.start_link)
        keep = self.link_go.sizePolicy()
        keep.setRetainSizeWhenHidden(True)
        self.link_go.setSizePolicy(keep)
        self.link_go.setVisible(False)
        # Боковые колонки растягиваются поровну — поле стоит ровно по центру,
        # какой бы ширины ни оказалась кнопка после стилей.
        row.addWidget(self.link_go, 0, 2, Qt.AlignLeft | Qt.AlignVCenter)
        v.addLayout(row)
        v.addSpacing(16)
        self.start_note = QLabel("")
        self.start_note.setObjectName("error")
        self.start_note.setAlignment(Qt.AlignCenter)
        self.start_note.setWordWrap(True)
        self.start_note.setMaximumWidth(520)
        v.addWidget(self.start_note, 0, Qt.AlignHCenter)
        v.addStretch(4)
        return page

    def _build_work(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(40, 30, 40, 40)
        v.setSpacing(0)
        v.addStretch(3)
        self.work_title = ElideLabel("")
        self.work_title.setObjectName("song")
        self.work_title.setAlignment(Qt.AlignHCenter)
        v.addWidget(self.work_title)
        v.addSpacing(18)
        self.work_orb = Orb(270)
        v.addWidget(self.work_orb, 0, Qt.AlignHCenter)
        v.addSpacing(18)
        self.work_stage = QLabel("")
        self.work_stage.setObjectName("stage")
        self.work_stage.setAlignment(Qt.AlignCenter)
        v.addWidget(self.work_stage)
        v.addSpacing(2)
        self.work_time = QLabel("")
        self.work_time.setObjectName("faint")
        self.work_time.setAlignment(Qt.AlignCenter)
        v.addWidget(self.work_time)
        v.addSpacing(14)
        cancel = QPushButton(t("Отменить"))
        cancel.setObjectName("text")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setFocusPolicy(Qt.NoFocus)
        cancel.clicked.connect(self.abort)
        v.addWidget(cancel, 0, Qt.AlignHCenter)
        v.addStretch(4)
        return page

    def _build_result(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(30, 22, 26, 16)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(20)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addStretch()
        self.title = ElideLabel("")
        self.title.setObjectName("title")
        titles.addWidget(self.title)
        self.sub = QLabel("")
        self.sub.setObjectName("sub")
        titles.addWidget(self.sub)
        head.addLayout(titles, 1)
        tempo = QVBoxLayout()
        tempo.setSpacing(0)
        self.bpm = QLabel("")
        self.bpm.setObjectName("bpm")
        self.bpm.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        tempo.addWidget(self.bpm)
        self.bpm_unit = QLabel("")
        self.bpm_unit.setObjectName("unit")
        self.bpm_unit.setAlignment(Qt.AlignRight)
        tempo.addWidget(self.bpm_unit)
        head.addLayout(tempo)
        v.addLayout(head)
        v.addSpacing(18)
        self.guitar = GuitarPanel()
        self.guitar.seek.connect(self.seek)
        self.guitar.find.connect(self.find_chords)
        self.guitar.changed.connect(self._save_guitar)
        self.guitar.setVisible(False)
        v.addWidget(self.guitar)
        self.lyrics = LyricsPanel(self.settings)
        self.lyrics.seek.connect(self.seek)
        self.lyrics.find.connect(self.find_lyrics)
        self.lyrics.setVisible(False)
        v.addWidget(self.lyrics)
        self.guitar.changed.connect(lambda: self.lyrics.set_chords(self._sheet_chords()))
        self.spectrum = SpectrumPanel()
        self.spectrum.seek.connect(self.seek)
        self.spectrum.pick.connect(self._pick_spectrum)
        self.spectrum.setVisible(False)
        v.addWidget(self.spectrum)
        self.spec_key = None
        self.spec_cache = {}
        self.tracks = {}

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self.lanes_box = QVBoxLayout(host)
        self.lanes_box.setContentsMargins(0, 0, 4, 0)
        self.lanes_box.setSpacing(4)
        self.scroll.setWidget(host)
        v.addWidget(self.scroll, 1)

        self.voice_bar = QWidget()
        vb = QHBoxLayout(self.voice_bar)
        vb.setContentsMargins(0, 12, 0, 4)
        vb.setSpacing(6)
        self.mode_btns = self._options(vb, ((t("Тембр образца"), 0), (t("Запись под оригинал"), 1)),
                                       "voice_mode", 0)
        self.mode_btns[0].setToolTip(t("Исходное пение голосом образца"))
        self.mode_btns[1].setToolTip(t("Своя запись песни ложится под оригинал: время и мелодия — "
                                       "от исходного голоса, тембр и слова — от записи"))
        for b in self.mode_btns.values():
            b.clicked.connect(self._voice_mode)
        vb.addSpacing(22)
        self.ref_caption = self._caption(t("Образец"))
        vb.addWidget(self.ref_caption)
        self.ref_btn = QPushButton(t("выбрать…"))
        self.ref_btn.setObjectName("text")
        self.ref_btn.setCursor(Qt.PointingHandCursor)
        self.ref_btn.setFocusPolicy(Qt.NoFocus)
        self.ref_btn.setToolTip(t("Песня, запись или видео с нужным голосом: музыка уберётся сама,"
                                  " возьмутся 10 самых громких секунд голоса"))
        self.ref_btn.clicked.connect(self._pick_reference)
        vb.addWidget(self.ref_btn)
        # Тон и качество — только у смены тембра: запись под оригинал берёт
        # мелодию оригинала в октаве своего голоса сама.
        self.timbre_box = QWidget()
        tb = QHBoxLayout(self.timbre_box)
        tb.setContentsMargins(22, 0, 0, 0)
        tb.setSpacing(6)
        tb.addWidget(self._caption(t("Тон"), t("Октава вниз или вверх — когда образец ниже"
                                               " или выше исходного голоса")))
        self.shift_btns = self._options(tb, (("−12", -12), ("0", 0), ("+12", 12)), "shift", 0)
        tb.addSpacing(22)
        tb.addWidget(self._caption(t("Качество"), t("Быстро — песня за ~2 мин,"
                                                    " чисто — за ~3 мин и ближе к образцу")))
        self.steps_btns = self._options(tb, ((t("быстро"), 10), (t("чисто"), 30)), "steps", 30)
        vb.addWidget(self.timbre_box)
        vb.addStretch()
        self.voice_go = GradientButton(t("Сменить голос"))
        self.voice_go.setEnabled(False)
        self.voice_go.clicked.connect(self.change_voice)
        vb.addWidget(self.voice_go)
        self.voice_bar.setVisible(False)
        v.addWidget(self.voice_bar)
        self._voice_mode()
        v.addSpacing(10)

        self.job_line = Thread()
        self.job_line.setVisible(False)
        v.addWidget(self.job_line)
        v.addSpacing(10)
        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        self.play = PlayButton()
        self.play.clicked.connect(self.toggle)
        bottom.addWidget(self.play)
        self.time = QLabel("0:00 / 0:00")
        self.time.setObjectName("sub")
        self.time.setMinimumWidth(92)
        bottom.addWidget(self.time)
        # Ход работы — своей строкой над панелью: в одну с переключателями не помещается.
        self.job_row = QWidget()
        jobs = QHBoxLayout(self.job_row)
        jobs.setContentsMargins(0, 0, 0, 0)
        jobs.setSpacing(14)
        self.job_row.setVisible(False)
        self.job_label = QLabel("")
        self.job_label.setObjectName("sub")
        tabular = self.job_label.font()
        tabular.setFeature(QFont.Tag("tnum"), 1)
        self.job_label.setFont(tabular)
        self.job_cancel = QPushButton(t("Отменить"))
        self.job_cancel.setObjectName("text")
        self.job_cancel.setCursor(Qt.PointingHandCursor)
        self.job_cancel.setFocusPolicy(Qt.NoFocus)
        self.job_cancel.clicked.connect(self.abort)
        self.job_cancel.setVisible(False)
        jobs.addWidget(self.job_cancel)
        self.job_skip = QPushButton(t("Пропустить"))
        self.job_skip.setObjectName("text")
        self.job_skip.setCursor(Qt.PointingHandCursor)
        self.job_skip.setFocusPolicy(Qt.NoFocus)
        self.job_skip.clicked.connect(self.skip_step)
        self.job_skip.setVisible(False)
        jobs.addWidget(self.job_skip)
        # Подпись — после кнопок, а цифры в ней одной ширины: проценты и секунды
        # меняются каждый миг, и кнопки за подписью дёргались вбок.
        jobs.addWidget(self.job_label)
        jobs.addStretch()
        v.addWidget(self.job_row)
        bottom.addStretch()
        self.metro = Metronome()
        self.metro.setToolTip(t("Щелчки на найденных ударах — проверить темп на слух"))
        self.metro.toggled.connect(lambda on: setattr(self.player.mixer, "metronome", on))
        bottom.addWidget(self.metro)
        self.chords_toggle = QPushButton(t("Аккорды"))
        self.chords_toggle.setObjectName("text")
        self.chords_toggle.setCheckable(True)
        self.chords_toggle.setCursor(Qt.PointingHandCursor)
        self.chords_toggle.setFocusPolicy(Qt.NoFocus)
        self.chords_toggle.toggled.connect(self.guitar.setVisible)
        self.chords_toggle.toggled.connect(lambda on: self.settings.setValue("chords", on))
        self.chords_toggle.setChecked(self.settings.value("chords", False, type=bool))
        bottom.addWidget(self.chords_toggle)
        self.lyrics_toggle = self._panel_toggle(t("Текст"), self.lyrics, "lyrics")
        self.lyrics_toggle.toggled.connect(lambda on: on and self.find_lyrics(auto=True))
        bottom.addWidget(self.lyrics_toggle)
        self.spec_toggle = self._panel_toggle(t("Спектрограмма"), self.spectrum, "spectrum")
        self.spec_toggle.toggled.connect(lambda on: on and self._update_spectrum())
        bottom.addWidget(self.spec_toggle)
        self.voice_toggle = QPushButton(t("Новый голос"))
        self.voice_toggle.setObjectName("text")
        self.voice_toggle.setCheckable(True)
        self.voice_toggle.setCursor(Qt.PointingHandCursor)
        self.voice_toggle.setFocusPolicy(Qt.NoFocus)
        self.voice_toggle.toggled.connect(self.voice_bar.setVisible)
        bottom.addWidget(self.voice_toggle)
        self.save_btn = QPushButton(t("Сохранить"))
        self.save_btn.setObjectName("text")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setFocusPolicy(Qt.NoFocus)
        self.save_btn.clicked.connect(self._save_menu)
        bottom.addWidget(self.save_btn)
        finder = QPushButton(t("В Finder"))
        finder.setObjectName("text")
        finder.setCursor(Qt.PointingHandCursor)
        finder.setFocusPolicy(Qt.NoFocus)
        finder.clicked.connect(lambda: self.folder and self._reveal(self.folder))
        bottom.addWidget(finder)
        v.addLayout(bottom)
        return page

    def _panel_toggle(self, text, panel, key):
        b = QPushButton(text)
        b.setObjectName("text")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        b.toggled.connect(panel.setVisible)
        b.toggled.connect(lambda on: self.settings.setValue(key, on))
        b.setChecked(self.settings.value(key, False, type=bool))
        return b

    def _caption(self, text, tip=""):
        lab = QLabel(text)
        lab.setObjectName("faint")
        lab.setToolTip(tip)
        return lab

    def _options(self, layout, items, key, default):
        cur = int(self.settings.value(key, default))
        buttons = {}
        # Своя группа на каждый выбор: autoExclusive объединил бы все кнопки панели.
        group = QButtonGroup(self)
        for text, value in items:
            b = QPushButton(text)
            b.setObjectName("opt")
            b.setCheckable(True)
            group.addButton(b)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setChecked(value == cur)
            b.clicked.connect(lambda _=False, v=value: self.settings.setValue(key, v))
            layout.addWidget(b)
            buttons[value] = b
        return buttons

    def show_start(self):
        self.pages.setCurrentWidget(self.work_page if self.job_kind == "split" else self.start_page)
        self.history.clearSelection()

    def choose(self):
        if self.job is not None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, t("Песня"), str(self.settings.value("dir", str(Path.home() / "Music"))),
            t("Звук и видео") + " (" + " ".join("*" + e for e in sorted(MEDIA_EXT)) + ")")
        if path:
            self.settings.setValue("dir", str(Path(path).parent))
            self.start(Path(path), "")

    def start_link(self):
        link = self.link.text().strip()
        if link:
            self.start(None, link)

    def _media(self, e):
        for u in e.mimeData().urls():
            if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in MEDIA_EXT:
                return Path(u.toLocalFile())
        return None

    def dragEnterEvent(self, e):
        if self.job is None and self._media(e) is not None:
            e.acceptProposedAction()
            self.orb.set_hot(True)

    def dragLeaveEvent(self, e):
        self.orb.set_hot(False)

    def dropEvent(self, e):
        self.orb.set_hot(False)
        path = self._media(e)
        if path is not None and self.job is None:
            self.start(path, "")

    def start(self, source, link):
        if self.job is not None:
            return
        self.player.pause()
        self.play.set_playing(False)
        self.start_note.setText("")
        title = source.stem if source else ""
        self.work_title.setText(title or link)
        self.work_orb.value = 0.0
        self.work_orb.set_split(0.0, busy=True)
        job = SplitJob(source, link, title)
        job.needs_access.connect(self.show_access)
        self._run(job, "split", None)
        self.history.clearSelection()
        self.pages.setCurrentWidget(self.work_page)

    def _next_split(self):
        """Что «разложить всё» делит следующим: первая сверху неразложенная дорожка,
        у которой остался способ деления. Новые части встают в дерево — дойдёт и до них."""
        for key in self.lanes:
            if key == "all" or key in self.skipped or self.children.get(key):
                continue
            for mode, _ in SPLIT_MODES.get(key, ()):
                if f"{key}:{mode}" not in self.nosplit:
                    return key, mode
        return None

    def split_all(self):
        if self.job is None and self.folder is not None:
            self.split_all_on, self.all_folder, self.skipped = True, self.folder, set()
            self._split_next()

    def _split_next(self):
        """Шаг «разложить всё»: сначала текст — он короткий, и караоке готово
        раньше, — потом дорожки сверху вниз."""
        if not self.split_all_on or self.job is not None or self.words_job is not None:
            return
        nxt = None
        if self.folder == self.all_folder:
            if "lyrics" not in self.skipped and not engine.load_info(self.folder).get("lyrics"):
                nxt = "lyrics"
            else:
                nxt = self._next_split()
        if nxt is None:
            self.split_all_on, self.skipped = False, set()
            self._busy()
        elif nxt == "lyrics":
            self.skipped.add("lyrics")
            self.find_lyrics()
        else:
            self.split_stem(*nxt)

    def skip_step(self):
        """«Разложить всё» дальше без того, что делится сейчас."""
        if self.job is not None and self.job_kind == "stem":
            self.skipped.add(self.job_parent)
            self.job.stop = True
            self.job, self.job_kind = None, ""
        elif self.words_job is not None:
            self.words_job.stop = True
            self.words_job = None
            self._words_busy()
        self._busy()
        QTimer.singleShot(0, self._split_next)

    def _split_items(self, menu, key):
        """Способы разложить дорожку: где число частей можно задать — подменю
        «Определить само / Число …»; невозможные — серые, с причиной."""
        for m, text in SPLIT_MODES.get(key, ()):
            why = t(self.nosplit.get(f"{key}:{m}") or "")
            text = t(text)
            if m in COUNTED:
                many = menu.addMenu(text)
                auto = many.addAction(t("Определить само") + (f" — {why.lower()}" if why else ""),
                                      lambda m=m: self.split_stem(key, m))
                auto.setEnabled(not why and self.job is None)
                ask = many.addAction(t(COUNTED[m]), lambda m=m: self.split_count(key, m))
                ask.setEnabled(self.job is None)
            elif not self.children.get(key):
                act = menu.addAction(f"{text} — {why.lower()}" if why else text,
                                     lambda m=m: self.split_stem(key, m))
                act.setEnabled(not why and self.job is None)

    def split_count(self, key, mode):
        """Своё число частей: по исполнителям — из названия трека или сколько уже есть."""
        have = len(self.children.get(key, []))
        hint = engine.artists_in_title(self._song_title()) if mode == "singers" else 0
        title = t("По исполнителям") if mode == "singers" else t("По тембру")
        label = t("Сколько исполнителей") if mode == "singers" else t("Сколько инструментов")
        n, ok = QInputDialog.getInt(self, title, label, max(hint, have, 2), 2, 12)
        if ok:
            self.split_stem(key, f"{mode}:{n}")

    def split_stem(self, key, mode=None):
        if key == "all":
            self.split_all()
            return
        if self.job is not None or self.folder is None:
            return
        modes = SPLIT_MODES.get(key, ())
        refused = any(f"{key}:{m}" in self.nosplit for m in COUNTED)
        if mode is None and (len(modes) > 1 or (refused and modes[0][0] in COUNTED)):
            # Несколько способов или автоматика уже отказала — меню у курсора.
            menu = QMenu(self)
            self._split_items(menu, key)
            menu.exec(QCursor.pos())
            return
        mode = mode or modes[0][0]
        self.player.pause()
        self.play.set_playing(False)
        self.job_parent = key
        self._run(StemJob(self.folder, key, mode), "stem", self.folder)

    def find_lyrics(self, auto=False):
        """Текст считается своим потоком, окно им не занято. При включённом
        «Тексте» он ищется сам, как только открыта песня без текста."""
        folder = self.folder
        if self.words_job is not None or folder is None:
            return
        if auto and (not self.lyrics_toggle.isChecked() or folder in self.words_tried
                     or engine.load_info(folder).get("lyrics")):
            return
        self.words_tried.add(folder)
        job = LyricsJob(folder)
        self.words_job, self.words_folder, self.words_text, self.words_share = job, folder, "", None
        self.alive.add(job)
        job.stage.connect(self._words_stage)
        job.done.connect(self._words_done)
        job.failed.connect(self._words_failed)
        job.finished.connect(lambda j=job: self.alive.discard(j))
        self._words_busy()
        job.start()

    def _words_busy(self):
        here = self.words_job is not None and self.words_folder == self.folder
        self.lyrics.set_busy(self.words_text if here else "", self.words_job is None)

    def _words_stage(self, text, share):
        if self.sender() is self.words_job:
            self.words_share = share
            self.words_text = f"{t(text)} · {int(share * 100)}%" if share is not None else f"{t(text)}…"
            self._words_busy()
            self._busy()

    def _words_done(self, folder):
        if self.sender() is not self.words_job:
            return
        self.words_job = None
        if Path(folder) == self.folder:
            self.lyrics.set_song(engine.load_info(self.folder).get("lyrics"), self._sheet_chords())
        self._words_busy()
        self._busy()
        QTimer.singleShot(0, self._split_next)

    def _words_failed(self, text):
        if self.sender() is not self.words_job:
            return
        self.words_job = None
        self._words_busy()
        self._busy()
        QTimer.singleShot(0, self._split_next)
        if self.words_folder == self.folder:
            last = text.strip().splitlines()[-1] if text.strip() else t("ошибка")
            self.lyrics.set_busy(tf("Не вышло: {e}", e=re.sub(r"^[\w.]+(Error|Exception): ", "", last)[:160]), True)

    def find_chords(self):
        if self.job is None and self.folder is not None:
            self._run(ChordsJob(self.folder), "chords", self.folder)

    def _voice_mode(self):
        """Смена тембра (Seed-VC) или своя запись под оригинал. Без окружения
        Seed-VC остаётся только второе."""
        timbre = engine.voice_python() is not None
        for b in self.mode_btns.values():
            b.setVisible(timbre)
        fit = not timbre or self._value(self.mode_btns) == 1
        self.timbre_box.setVisible(not fit)
        self.ref_caption.setText(t("Запись") if fit else t("Образец"))
        self.voice_go.setText(t("Подставить запись") if fit else t("Сменить голос"))
        self.voice_go.updateGeometry()
        if self.reference is None:
            self.ref_btn.setToolTip(t("Своя запись этой песни: музыка уберётся сама") if fit else
                                    t("Песня, запись или видео с нужным голосом: музыка уберётся сама,"
                                      " возьмутся 10 самых громких секунд голоса"))

    def change_voice(self):
        if self.job is not None or self.folder is None or self.reference is None:
            return
        self.player.pause()
        self.play.set_playing(False)
        if engine.voice_python() is None or self._value(self.mode_btns) == 1:
            self._run(FitJob(self.folder, self.reference), "voice", self.folder)
            return
        self._run(VoiceJob(self.folder, self.reference, self._value(self.steps_btns),
                           self._value(self.shift_btns)), "voice", self.folder)

    def _run(self, job, kind, folder):
        self.job, self.job_kind, self.job_folder = job, kind, folder
        self.job_text, self.job_share = "", None
        self.alive.add(job)
        job.stage.connect(self._stage)
        job.done.connect(self._done)
        job.failed.connect(self._failed)
        job.finished.connect(lambda j=job: self.alive.discard(j))
        self.job_started = time.time()
        self._busy()
        job.start()

    def abort(self):
        if self.job is None:
            if self.split_all_on and self.words_job is not None:
                self.words_job.stop = True
                self.words_job = None
                self.split_all_on = False
                self._words_busy()
                self._busy()
            return
        self.job.stop = True
        kind = self.job_kind
        self.job = None
        self.job_kind = ""
        self.split_all_on = False
        self._busy()
        if kind == "split":
            self.pages.setCurrentWidget(self.start_page)

    def _stage(self, text, share):
        if self.sender() is not self.job:
            return
        self.job_text, self.job_share = text, share
        if self.job_kind == "split":
            if text == "Разделение" and share is not None:
                self.work_orb.set_split(share * 0.9)
            else:
                self.work_orb.set_split(self.work_orb.target, busy=True)
        self._busy()

    def _status(self):
        """Строка хода под дорожками; в «разложить всё» — что именно делится сейчас."""
        if self.job is not None and self.job_kind != "split" and self.job_folder == self.folder:
            if not (self.split_all_on and self.job_kind == "stem"):
                return self._job_status(), self.job_share
            lane = self.lanes.get(self.job_parent)
            text = lane.title if lane else t("Раскладка")
            if self.job_text not in ("", "Раскладка"):
                text += f" · {t(self.job_text).lower()}"
            share = self.job_share
            return text + (f" · {int(share * 100)}%" if share is not None else "…"), share
        if self.split_all_on and self.words_job is not None and self.words_folder == self.folder:
            return self.words_text, self.words_share
        return "", None

    def _job_status(self):
        text = t(self.job_text or "Подготовка")
        return f"{text} · {int(self.job_share * 100)}%" if self.job_share is not None else f"{text}…"

    def _busy(self):
        """Всё, что зависит от того, идёт ли работа и какая."""
        idle = self.job is None
        split = self.job_kind == "split"
        self.new_song.set_status(self._job_status() if split else "",
                                 self.work_orb.value if split else 0.0)
        self.new_song.spin.set(not idle)
        self.work_orb.spin.set(split)
        if split:
            self.work_stage.setText(self._job_status())
        here = not idle and not split and self.job_folder == self.folder
        status, share = self._status()
        # Между шагами «разложить всё» строка не прячется: иначе всё окно над
        # ней на миг подпрыгивало.
        chain = self.split_all_on and self.folder == self.all_folder
        shown_ = bool(status) or chain
        if status or not chain:
            self.job_label.setText(status)
        self.job_row.setVisible(shown_)
        self.job_label.setVisible(shown_)
        self.job_cancel.setVisible(shown_)
        self.job_skip.setVisible(shown_ and self.split_all_on)
        self.job_line.setVisible(shown_)
        if shown_:
            self.job_line.set(share)
        self.voice_go.setEnabled(idle and self.reference is not None and self.folder is not None)
        for k, lane in self.lanes.items():
            modes = SPLIT_MODES.get(k, ())
            left = [m for m, _ in modes if f"{k}:{m}" not in self.nosplit]
            if k == "all":
                live = idle and not self.split_all_on and self._next_split() is not None
                text = t("разложить всё") if live else ""
                if (lane.split_text, lane.split_live) != (text, live):
                    lane.split_text, lane.split_live, lane.split_tip = text, live, ""
                    lane.update()
                continue
            if not modes or self.children.get(k):
                text, live = "", False
            elif here and self.job_kind == "stem" and self.job_parent == k:
                text, live = (t("раскладка") + f" · {int(self.job_share * 100)}%" if self.job_share is not None
                              and self.job_text == "Раскладка" else self._job_status().lower()), False
            elif not left and any(f"{k}:{m}" in self.nosplit for m in COUNTED):
                why = next(self.nosplit[f"{k}:{m}"] for m in COUNTED if f"{k}:{m}" in self.nosplit)
                text, live = t(why).lower(), idle and not self.split_all_on
            elif not left:
                text, live = t(self.nosplit[f"{k}:{modes[-1][0]}"]).lower(), False
            else:
                text, live = t("разложить"), idle and not self.split_all_on
            if (lane.split_text, lane.split_live) != (text, live):
                lane.split_text, lane.split_live = text, live
                tips = [t(x) for m, x in modes if m in left]
                lane.split_tip = t(" или ").join(tips[:1] + [x[0].lower() + x[1:] for x in tips[1:]])
                lane.update()
        chords = here and self.job_kind == "chords"
        self.guitar.set_busy(self._job_status() if chords else "", idle)

    def _done(self, folder):
        if self.sender() is not self.job:
            return
        kind = self.job_kind
        self.job = None
        self.job_kind = ""
        self._busy()
        self._fill_history()
        folder = Path(folder)
        if kind == "split":
            self.work_orb.set_split(1.0)
            if self.pages.currentWidget() is self.work_page:
                QTimer.singleShot(420, lambda: self.open_result(folder))
        elif folder == self.folder:
            self.open_result(folder)
        if kind == "stem" and self.split_all_on:
            QTimer.singleShot(0, self._split_next)

    def _failed(self, text):
        if self.sender() is not self.job:
            return
        kind = self.job_kind
        self.job = None
        self.job_kind = ""
        self.split_all_on = False
        last = text.strip().splitlines()[-1] if text.strip() else t("ошибка")
        last = re.sub(r"^[\w.]+(Error|Exception): ", "", last)[:240]
        self._busy()
        if kind == "split":
            self.start_note.setText(last if text.startswith("SourceError: ") else tf("Не вышло: {e}", e=last))
            self.pages.setCurrentWidget(self.start_page)
        else:
            self.job_label.setText(tf("Не вышло: {e}", e=last))
            self.job_label.setVisible(True)
            self.job_row.setVisible(True)

    def _fill_history(self):
        """Порядок — свежие сверху; прокрутка и выбор остаются на месте."""
        bar = self.history.verticalScrollBar()
        keep = bar.value()
        chosen = str(self.folder) if self.folder and self.pages.currentWidget() is self.result_page else None
        self.history.clear()
        items = []
        if OUT_DIR.exists():
            for f in OUT_DIR.iterdir():
                info = engine.load_info(f) if f.is_dir() else {}
                if info:
                    st = f.stat()
                    items.append((getattr(st, "st_birthtime", st.st_mtime), f, info))
        for _, f, info in sorted(items, key=lambda x: x[0], reverse=True):
            it = QListWidgetItem(info.get("title") or f.name)
            it.setData(Qt.UserRole, str(f))
            parts = [f"{info['bpm']:g} BPM"] if info.get("bpm") else []
            if info.get("duration"):
                parts.append(clock(info["duration"]))
            it.setData(Qt.UserRole + 1, " · ".join(parts))
            self.history.addItem(it)
            if str(f) == chosen:
                it.setSelected(True)
        bar.setValue(keep)

    def _history_menu(self, pos):
        it = self.history.itemAt(pos)
        if it is None:
            return
        folder = Path(it.data(Qt.UserRole))
        menu = QMenu(self)
        menu.addAction(t("Показать в Finder"), lambda: self._reveal(folder))
        busy = self.job is not None and self.job_folder == folder
        trash = menu.addAction(t("В корзину"), lambda: self._trash(folder))
        trash.setEnabled(not busy)
        menu.exec(self.history.viewport().mapToGlobal(pos))

    def _trash(self, folder: Path):
        if self.folder == folder:
            self.player.stop()
            self.play.set_playing(False)
            self.folder = None
            self.pages.setCurrentWidget(self.start_page)
        QFile.moveToTrash(str(folder))
        self._fill_history()

    def open_result(self, folder: Path):
        info = engine.load_info(folder)
        if not info:
            return
        same = folder == self.folder
        at = self.player.position() if same else 0.0
        scroll = self.scroll.verticalScrollBar().value() if same else 0
        if self.folder is not None and self.lanes:
            self.saved[str(self.folder)] = self._lane_state()
        self.player.stop()
        self.play.set_playing(False)
        self.folder = folder
        while self.lanes_box.count():
            item = self.lanes_box.takeAt(0)
            if item.widget():
                # Удалится, когда окно вернётся в свой цикл; до тех пор — не видна.
                item.widget().hide()
                item.widget().deleteLater()
        self.lanes = {}
        tracks = {}
        file = lambda k: folder / f"{engine.stem_file(info, k, folder)}.wav"
        names = info.get("names", {})
        splits = dict(info.get("splits", {}))
        if info.get("instruments") and "music" not in splits:
            splits["music"] = info["instruments"]
        self.children = {p: [k for k in ks if file(k).exists()] for p, ks in splits.items()}
        self.children = {p: ks for p, ks in self.children.items() if len(ks) >= 2}
        self.parent_of = {k: p for p, ks in self.children.items() for k in ks}
        # Старые записи — без режима: «vocals» значит модель.
        self.nosplit = {(k if ":" in k else f"{k}:model"): v for k, v in info.get("nosplit", {}).items()}
        original = engine.read_wav(file("original")) if file("original").exists() else None
        top = 0.0
        if original is not None:
            step = max(len(original) // 1600, 1)
            mono = original[:step * 1600, 0].astype(np.float32) + original[:step * 1600, 1]
            top = float(np.sqrt((mono.reshape(-1, step) ** 2).mean(axis=1)).max()) / 65536.0

        def add(key, title, colors, path, depth=0, data=None, height=None, indent=0):
            data = engine.read_wav(path) if data is None else data
            tracks[key] = data
            lane = Lane(key, title, colors, path, height or (64, 48, 42)[min(depth, 2)], depth + indent)
            lane.set_audio(data, top)
            lane.mute_clicked.connect(self._mute_clicked)
            lane.solo_clicked.connect(self._solo_clicked)
            lane.split_clicked.connect(self.split_stem)
            lane.gain_changed.connect(self._gain_changed)
            lane.seek.connect(self.seek)
            lane.reveal.connect(self._reveal)
            lane.save.connect(self.export_lane)
            lane.selected.connect(self._lane_selected)
            lane.context.connect(self._lane_menu)
            self.lanes_box.addWidget(lane)
            self.lanes[key] = lane

        def colors(key):
            if "_ch" in key and key.rsplit("_ch", 1)[1].isdigit():
                return colors(key.rsplit("_ch", 1)[0])
            for mark, palette in (("_s", SINGERS), ("_i", INSTRUMENTS), ("inst", INSTRUMENTS)):
                if mark in key and key.rsplit(mark, 1)[1].isdigit():
                    c = palette[(int(key.rsplit(mark, 1)[1]) - 1) % len(palette)]
                    return (c, c)
            return LANES.get(key, LANES["other"])

        def tree(key, depth=0):
            if file(key).exists():
                add(key, shown(names.get(key) or engine.FILES[key]), colors(key), file(key), depth, indent=1)
                for k in self.children.get(key, []):
                    tree(k, depth + 1)

        # Всё, кроме оригинала, — под «Разложенным»: одна точка выключает всё
        # разложенное разом, громкость и соло — тоже на всё. Волна — сумма частей.
        voices = [v for v in info.get("voices", []) if (folder / v["file"]).exists()]
        whole = [k for k in ("vocals", "music") if file(k).exists()]
        if whole:
            parts = [engine.read_wav(file(k)).astype(np.int32) for k in whole]
            size = max(len(x) for x in parts)
            total = np.zeros((size, 2), np.int32)
            for x in parts:
                total[:len(x)] += x
            add("all", t("Разложенный"), (WARM[0], "#3cc8f0"), None,
                data=np.clip(total, -32768, 32767).astype(np.int16), height=56)
        tree("vocals")
        for i, v in enumerate(voices):
            add(f"voice{i}", tf("Новый голос · {name}", name=v["name"]), VOICE, folder / v["file"], height=56, indent=1)
        tree("music")
        if whole:
            self.children["all"] = [k for k in self.lanes if k != "all" and k not in self.parent_of]
            for k in self.children["all"]:
                self.parent_of[k] = "all"
        if original is not None:
            self.lanes_box.addSpacing(10)
            add("original", t("Оригинал"), LANES["original"], file("original"), data=original, height=40)
            for k in self.children.get("original", []):
                tree(k, 1)
        self.lanes_box.addStretch(1)

        # Что звучит. Песня открыта впервые — по умолчанию: без оригинала, а есть
        # новый голос — он вместо исходного. Уже открывалась — как оставили; новые
        # части наследуют разложенную дорожку, новый голос включается сам.
        saved = self.saved.get(str(folder))
        mix = info.get("mix", {})
        newest = f"voice{len(voices) - 1}" if voices else None
        for key, lane in self.lanes.items():
            if saved and key in saved:
                lane.muted, lane.solo, lane.db = saved[key]["muted"], saved[key]["solo"], saved[key]["db"]
                continue
            if key in mix:
                lane.db = None if mix[key] <= -90 else float(mix[key])
            if saved and self.parent_of.get(key) in saved:
                lane.muted = saved[self.parent_of[key]]["muted"]
            elif saved and key != newest:
                lane.muted = self._root(key) == "original"
            else:
                lane.muted = self._root(key) == "original" or (key.startswith("voice") and key != newest)
        if newest is not None and (not saved or newest not in saved):
            for k in self._leaves("vocals") if "vocals" in self.lanes else []:
                self.lanes[k].muted = True
            for k in self.lanes:
                if k.startswith("voice"):
                    self.lanes[k].muted = k != newest
        self.singer_parents = {p: ks for p, ks in self.children.items()
                               if ks and all(k.startswith(f"{p}_s") for k in ks)}
        for parent in self._movable():
            for k in [parent] + self.children[parent]:
                if k in self.lanes:
                    self.lanes[k].selectable = True
        self.player.mixer.load(tracks, info.get("beats", []), info.get("downbeats", []))
        self.beat_times = np.asarray(info.get("beats", []), dtype=float)
        self.strong_beats = {round(float(b), 3) for b in info.get("downbeats", [])}
        bpm = float(info.get("bpm") or 0)
        self.play.spin.tempo = min(max(bpm / 110, 0.6), 1.8) if bpm else 1.0
        self._mix()
        g = info.get("guitar", {})
        self.guitar.set_song(info.get("chords", []), info.get("downbeats", []),
                             int(g.get("capo", 0)), int(g.get("transpose", 0)))
        self.tracks = tracks
        self.lyrics.set_song(info.get("lyrics"), self._sheet_chords())
        self._words_busy()
        self.find_lyrics(auto=True)
        if not same:
            self.spec_key = None
        self._update_spectrum()
        self.title.setText(info.get("title") or folder.name)
        dur = self.player.mixer.length / engine.SR
        self.sub.setText(clock(dur))
        self.bpm.setText(f"{info['bpm']:g}" if info.get("bpm") else "")
        meter = f" · {info['meter']}/4" if info.get("meter") else ""
        self.bpm_unit.setText(f"BPM{meter}" if info.get("bpm") else "")
        self.pages.setCurrentWidget(self.result_page)
        for i in range(self.history.count()):
            it = self.history.item(i)
            it.setSelected(it.data(Qt.UserRole) == str(folder))
        if at:
            self.player.seek(at)
        if scroll:
            QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(scroll))
        self._busy()
        self._tick()

    def _lane_state(self):
        return {k: {"muted": lane.muted, "solo": lane.solo, "db": lane.db} for k, lane in self.lanes.items()}

    def _leaves(self, key):
        """Дорожки, которые звучат вместо key: сама она или все её части."""
        kids = self.children.get(key)
        if not kids:
            return [key]
        return [leaf for k in kids for leaf in self._leaves(k)]

    def _mute_clicked(self, key):
        leaves = self._leaves(key)
        off = any(not self.lanes[k].muted for k in leaves)
        for k in leaves:
            self.lanes[k].muted = off
        if off:
            for k in [key] + leaves:
                self.lanes[k].solo = False
        self._mix()

    def _solo_clicked(self, key):
        self.lanes[key].solo = not self.lanes[key].solo
        self._mix()

    def _gain_changed(self):
        self._mix()
        self.mix_saver.start()

    def _save_mix(self):
        if self.folder is None:
            return
        mix = {k: (-99 if lane.db is None else lane.db) for k, lane in self.lanes.items() if lane.db != 0}
        engine.update_info(self.folder, lambda info: info.__setitem__("mix", mix))

    def _save_guitar(self):
        if self.folder is not None:
            g = {"capo": self.guitar.capo, "transpose": self.guitar.transpose}
            engine.update_info(self.folder, lambda info: info.__setitem__("guitar", g))

    def _value(self, buttons):
        return next(v for v, b in buttons.items() if b.isChecked())

    def _pick_reference(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("Образец голоса"), str(self.settings.value("dir", str(Path.home() / "Music"))),
            t("Звук и видео") + " (" + " ".join("*" + e for e in sorted(MEDIA_EXT)) + ")")
        if path:
            self.reference = Path(path)
            self.ref_btn.setText(self.ref_btn.fontMetrics().elidedText(self.reference.stem, Qt.ElideMiddle, 200))
            self.ref_btn.setToolTip(self.reference.name)
            self._busy()

    def _mix(self):
        """Звучат только неразложенные дорожки. Соло на разложенной — все её части;
        громкость части — её собственная, умноженная на громкость всех старших."""
        lanes = self.lanes
        leaves = [k for k in lanes if not self.children.get(k)]
        soloed = [k for k in lanes if lanes[k].solo]
        if soloed:
            active = {leaf for k in soloed for leaf in self._leaves(k)}
        else:
            active = {k for k in leaves if not lanes[k].muted}
        gains = {}
        for k in leaves:
            g, cur = 1.0, k
            while cur is not None:
                db = lanes[cur].db
                g *= 0.0 if db is None else 10 ** (db / 20)
                cur = self.parent_of.get(cur)
            gains[k] = g
        self.mix_gains = {k: gains[k] for k in active}
        self.player.mixer.gains = {k: int(round(g * 1024)) for k, g in gains.items()}
        self.player.mixer.active = active
        for k, lane in lanes.items():
            own = self._leaves(k)
            lane.group = bool(self.children.get(k))
            if lane.group:
                on = [x for x in own if not lanes[x].muted]
                lane.muted = not on
                lane.partial = 0 < len(on) < len(own)
            lane.audible = any(x in active for x in own)
            lane.update()

    def toggle(self):
        if self.player.playing:
            self.player.pause()
        else:
            self.player.play()
        self.smooth = None
        self.play.set_playing(self.player.playing)

    def seek(self, seconds):
        self.player.seek(seconds)
        self.smooth = None
        self._tick()

    def _smooth_position(self):
        """Звуковая карта забирает звук кусками, и позиция по ней прыгает на
        20–40 мс. Между её показаниями время идёт по часам, расхождение
        выбирается плавно; большое (перемотка, пауза) — сразу."""
        raw = self.player.position()
        now = time.monotonic()
        if not self.player.playing or self.smooth is None:
            self.smooth = (raw, now)
            return raw
        at, then = self.smooth
        guess = at + (now - then)
        err = raw - guess
        at = raw if abs(err) > 0.12 else guess + err * 0.08
        self.smooth = (at, now)
        return at

    def _tick(self):
        if self.job is not None:
            elapsed = clock(time.time() - self.job_started)
            if self.job_kind == "split":
                self.work_time.setText(elapsed)
                self.new_song.set_status(self._job_status(), self.work_orb.value)
            elif self.job_label.isVisible():
                self.job_label.setText(f"{self._status()[0]}  {elapsed}")
        if not self.player.mixer.length:
            return
        at = self._smooth_position()
        total = self.player.mixer.length / engine.SR
        if self.player.playing and self.player.mixer.pos >= self.player.mixer.length and at >= total - 0.05:
            self.player.pause()
            self.player.seek(0)
            self.play.set_playing(False)
        for lane in self.lanes.values():
            if abs(lane.at - at) > 0.002:
                # Перерисовывается только полоса между старым и новым местом курсора.
                x0, x1 = lane.playhead_x(), lane.playhead_x(at)
                lane.at = at
                lane.update(int(min(x0, x1)) - 3, 0, int(abs(x1 - x0)) + 7, lane.height())
        if self.guitar.isVisible() and abs(self.guitar.ticker.at - at) > 0.005:
            self.guitar.set_time(at)
        if self.lyrics.isVisible():
            self.lyrics.set_time(at)
        if self.spectrum.isVisible() and abs(self.spectrum.view.at - at) > 0.005:
            self.spectrum.view.set_time(at, self.player.playing)
        self.time.setText(f"{clock(at)} / {clock(total)}")
        if self.player.playing and len(self.beat_times):
            i = int(np.searchsorted(self.beat_times, at, side="right")) - 1
            if i >= 0:
                beat = self.beat_times[i]
                strong = round(float(beat), 3) in self.strong_beats
                pulse = (1.0 if strong else 0.55) * math.exp(-(at - beat) * 9)
            else:
                pulse = 0.0
            if abs(pulse - self.play.pulse) > 0.01:
                self.play.pulse = pulse
                self.play.update()
        elif self.play.pulse:
            self.play.pulse = 0.0
            self.play.update()
        if self.metro.isChecked() and self.player.playing and len(self.beat_times):
            i = int(np.searchsorted(self.beat_times, at)) - 1
            since = at - self.beat_times[i] if i >= 0 else 1.0
            flash = max(0.0, 1 - since / 0.12)
            if abs(flash - self.metro.flash) > 0.02:
                self.metro.flash = flash
                self.metro.update()

    def _movable(self):
        """Группы, где куски переносятся между частями: части сами не разложены.
        Левый и правый каналы — не части одного звука, их не перекладывают."""
        return [p for p, ks in self.children.items()
                if p != "all" and ks and not any(self.children.get(k) for k in ks)
                and not all("_ch" in k for k in ks)]

    def _root(self, key):
        while self.parent_of.get(key) not in (None, "all"):
            key = self.parent_of[key]
        return key

    def _sheet_chords(self):
        return [(a, b, n) for a, b, n, _ in self.guitar.shapes]

    def _show_spectrum(self, key):
        self.spec_key = key
        self.spec_toggle.setChecked(True)
        self._update_spectrum()

    def _pick_spectrum(self):
        menu = QMenu(self)
        for k, lane in self.lanes.items():
            act = menu.addAction(lane.title, lambda k=k: self._show_spectrum(k))
            act.setCheckable(True)
            act.setChecked(k == self.spec_key)
        menu.exec(self.spectrum.track_btn.mapToGlobal(self.spectrum.track_btn.rect().bottomLeft()))

    def _update_spectrum(self):
        if self.folder is None or not self.lanes or not self.spec_toggle.isChecked():
            return
        if self.spec_key not in self.lanes:
            self.spec_key = "original" if "original" in self.lanes else next(iter(self.lanes))
        key = self.spec_key
        self.spectrum.track_btn.setText(self.lanes[key].title)
        duration = self.player.mixer.length / engine.SR
        ident = (str(self.folder), key, self.lanes[key].path and str(self.lanes[key].path))
        if ident in self.spec_cache:
            self.spectrum.view.set_image(self.spec_cache[ident], duration)
            return
        self.spectrum.view.note = t("Считается…")
        self.spectrum.view.set_image(None, duration)
        job = SpecJob(ident, self.tracks[key])
        job.done.connect(lambda ident, img, d=duration: self._spectrum_ready(ident, img, d))
        job.finished.connect(lambda j=job: self.alive.discard(j))
        self.alive.add(job)
        job.start()

    def _spectrum_ready(self, ident, img, duration):
        if len(self.spec_cache) > 6:
            self.spec_cache.pop(next(iter(self.spec_cache)))
        self.spec_cache[ident] = img
        if self.folder is not None and ident == (str(self.folder), self.spec_key,
                                                 self.lanes.get(self.spec_key) and self.lanes[self.spec_key].path
                                                 and str(self.lanes[self.spec_key].path)):
            self.spectrum.view.set_image(img, duration)

    def _lane_menu(self, key, at):
        lane = self.lanes.get(key)
        if lane is None:
            return
        menu = QMenu(self)
        parent = key if key in self._movable() else self.parent_of.get(key)
        if lane.sel and parent in self._movable() and self.job is None:
            a, b = lane.sel
            give = menu.addMenu(tf("Отдать {a}–{b}", a=clock(a), b=clock(b)))
            for k in self.children[parent]:
                if k != key and k in self.lanes:
                    give.addAction(self.lanes[k].title, lambda k=k: self.move_part(key, a, b, k))
            give.addSeparator()
            new = t("Новому исполнителю") if parent in self.singer_parents else t("Новой дорожке")
            give.addAction(new, lambda: self.move_part(key, a, b, ""))
            menu.addAction(t("Снять выделение"), lane.clear_sel)
            menu.addSeparator()
        if SPLIT_MODES.get(key):
            self._split_items(menu, key)
            menu.addSeparator()
        if key != "all" and not self.children.get(key):
            why = self.nosplit.get(f"{key}:channels")
            act = menu.addAction(t("Левый и правый каналы") + (f" — {t(why).lower()}" if why else ""),
                                 lambda: self.split_stem(key, "channels"))
            act.setEnabled(not why and self.job is None)
        menu.addAction(t("Спектрограмма"), lambda: self._show_spectrum(key))
        menu.addSeparator()
        if key not in ("all", "original"):
            menu.addAction(t("Переименовать…"), lambda: self.rename_lane(key))
        menu.addAction(t("Сохранить дорожку…"), lambda: self.export_lane(key))
        menu.addAction(t("Показать в Finder"), lambda: self._reveal(lane.path))
        if lane.db != 0:
            menu.addAction(t("Громкость — 0 дБ"), lambda: lane._set_db(0.0))
        menu.exec(at)

    def _lane_selected(self, key):
        for k, lane in self.lanes.items():
            if k != key:
                lane.clear_sel()

    def _singer_state(self, info, parent):
        keys = list(info.get("splits", {}).get(parent, []))
        files = [engine.stem_file(info, k, self.folder) for k in keys]
        runs = info.get("singer_runs", {}).get(parent) or engine.runs_from_files(self.folder, files)
        return {"keys": keys, "names": {k: info.get("names", {}).get(k) for k in keys},
                "files": {k: info.get("files", {}).get(k) for k in keys}, "runs": runs}

    def _apply_singers(self, parent, state):
        """Дорожки исполнителей заново из общей по разметке; пустые — убираются."""
        info = engine.load_info(self.folder)
        keys, runs = list(state["keys"]), [list(r) for r in state["runs"]]
        used = sorted({w for _, _, w in runs})
        keep = [keys[i] for i in used]
        runs = [[a, b, used.index(w)] for a, b, w in runs]
        for k in keys:
            if k not in keep and state["files"].get(k):
                (self.folder / f"{state['files'][k]}.wav").unlink(missing_ok=True)
        src = self.folder / f"{engine.stem_file(info, parent, self.folder)}.wav"
        engine.render_singers(self.folder, src, runs, [state["files"][k] for k in keep])

        def change(info):
            info.setdefault("splits", {})[parent] = keep
            info.setdefault("names", {}).update({k: state["names"][k] for k in keep})
            info.setdefault("files", {}).update({k: state["files"][k] for k in keep})
            info.setdefault("singer_runs", {})[parent] = runs
        engine.update_info(self.folder, change)
        self.open_result(self.folder)

    def move_part(self, src, a, b, target):
        """Кусок [a, b) — другой части или новой. ⌘Z возвращает как было."""
        if self.job is not None or self.folder is None:
            return
        parent = src if src in self.children else self.parent_of.get(src)
        if parent not in self.singer_parents:
            if parent in self._movable():
                self._move_audio(parent, src, a, b, target)
            return
        info = engine.load_info(self.folder)
        state = self._singer_state(info, parent)
        self.undo.append(("singers", self.folder, parent, json.loads(json.dumps(state))))
        if not target:
            n = max(int(k.rsplit("_s", 1)[1]) for k in state["keys"]) + 1
            target = f"{parent}_s{n}"
            stem = engine.stem_file(info, parent, self.folder)
            state["keys"].append(target)
            state["names"][target] = f"Исполнитель {n}"
            state["files"][target] = f"{stem} — {engine.part_word('singer')} {n}"
        state["runs"] = engine.move_singer(state["runs"], a, b, state["keys"].index(target))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._apply_singers(parent, state)
        finally:
            QApplication.restoreOverrideCursor()

    def _move_audio(self, parent, src, a, b, target):
        """Части инструментов и барабанов — маски одного звука: кусок звука
        переходит из части в часть. С родителя — из всех частей в одну."""
        info = engine.load_info(self.folder)
        keys = list(self.children[parent])
        before = {f: json.loads(json.dumps(info.get(f, {}))) for f in ("splits", "names", "files")}
        files = {k: engine.stem_file(info, k, self.folder) for k in keys}
        if not target:
            stem = engine.stem_file(info, parent, self.folder)
            timbre = all("_i" in k for k in keys)
            mark, base = ("_i", "инструмент") if timbre else ("_p", "часть")
            word = engine.part_word("timbre") if timbre else ("part" if i18n.current() == "en" else "часть")
            n = 1 + max([int(k.rsplit(mark, 1)[1]) for k in keys
                         if mark in k and k.rsplit(mark, 1)[1].isdigit()] + [len(keys)])
            target = f"{parent}{mark}{n}"
            files[target] = f"{stem} — {word} {n}"
            length = len(engine.read_wav(self.folder / f"{files[keys[0]]}.wav"))
            engine.write_wav(self.folder / f"{files[target]}.wav", np.zeros((length, 2), np.int16))

            def change(info):
                info.setdefault("splits", {})[parent] = keys + [target]
                info.setdefault("names", {})[target] = f"{base.capitalize()} {n}"
                info.setdefault("files", {})[target] = files[target]
            engine.update_info(self.folder, change)
            made = files[target]
        else:
            made = None
        sources = [files[k] for k in keys if k != target] if src == parent else [files[src]]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            saved = engine.move_audio(self.folder, sources, files[target], a, b)
        finally:
            QApplication.restoreOverrideCursor()
        self.undo.append(("audio", self.folder, parent, {"saved": saved, "made": made, "info": before}))
        self.open_result(self.folder)

    def undo_move(self):
        if not self.undo or self.job is not None:
            return
        kind, folder, parent, state = self.undo.pop()
        if folder != self.folder:
            self.undo.clear()
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if kind == "singers":
                self._apply_singers(parent, state)
                return
            engine.restore_audio(folder, state["saved"])
            if state["made"]:
                (folder / f"{state['made']}.wav").unlink(missing_ok=True)

                def change(info):
                    for f, v in state["info"].items():
                        info[f] = v
                engine.update_info(folder, change)
            self.open_result(folder)
        finally:
            QApplication.restoreOverrideCursor()

    def rename_lane(self, key):
        lane = self.lanes.get(key)
        if lane is None or self.folder is None:
            return
        text, ok = QInputDialog.getText(self, t("Имя"), "", QLineEdit.Normal, lane.title)
        text = text.strip()
        if ok and text and text != lane.title:
            engine.update_info(self.folder, lambda info: info.setdefault("names", {}).__setitem__(key, text))
            self.open_result(self.folder)

    def _export_kind(self):
        kind = str(self.settings.value("export", "mp3"))
        return kind if kind in engine.EXPORT else "mp3"

    def _save_menu(self):
        if self.folder is None:
            return
        menu = QMenu(self)
        menu.addAction(t("Как слышно сейчас…"), self.export_mix)
        menu.addAction(t("Без некоторых дорожек…"), self.export_without)
        menu.addAction(t("Все дорожки…"), self.export_all)
        menu.addSeparator()
        group = QActionGroup(menu)
        for kind in engine.EXPORT:
            act = menu.addAction(kind.upper())
            act.setCheckable(True)
            act.setChecked(kind == self._export_kind())
            act.triggered.connect(lambda _=False, k=kind: self.settings.setValue("export", k))
            group.addAction(act)
        at = self.save_btn.mapToGlobal(QPoint(0, 0))
        menu.exec(QPoint(at.x(), at.y() - menu.sizeHint().height() - 4))

    def _song_title(self):
        return self.title.text() or (self.folder.name if self.folder else APP)

    def _ask_file(self, name):
        """Куда сохранить один файл. Формат — по выбранному типу, он же запоминается."""
        kind = self._export_kind()
        kinds = [kind] + [k for k in engine.EXPORT if k != kind]
        filters = [f"{k.upper()} (*.{k})" for k in kinds]
        start = Path(str(self.settings.value("export_dir", str(Path.home() / "Music"))))
        path, chosen = QFileDialog.getSaveFileName(self, t("Сохранить"), str(start / f"{safe_name(name)}.{kind}"),
                                                   ";;".join(filters), filters[0])
        if not path:
            return None
        kind = kinds[filters.index(chosen)] if chosen in filters else kind
        path = Path(path)
        if path.suffix.lower().lstrip(".") not in engine.EXPORT:
            path = path.with_name(path.name + "." + kind)
        self.settings.setValue("export", path.suffix.lower().lstrip("."))
        self.settings.setValue("export_dir", str(path.parent))
        return path

    def _mix_name(self):
        """«(минус)», если звучит только музыка; «(голос)» — только голоса."""
        active = set(self.mix_gains)
        leaves = {k for k in self.lanes if not self.children.get(k) and k != "original"}
        voices = {k for k in leaves if k.startswith("voice")}
        voices |= set(self._leaves("vocals")) if "vocals" in self.lanes else set()
        title = self._song_title()
        if active == leaves - {k for k in voices if k.startswith("voice")} and \
                all(abs(self.mix_gains[k] - 1.0) < 1e-6 for k in active):
            return title
        if active and not active & voices and "original" not in active:
            return tf("{title} (минус)", title=title)
        if active and active <= voices:
            return tf("{title} (голос)", title=title)
        return tf("{title} (микс)", title=title)

    def export_mix(self):
        parts = [(self.lanes[k].path, g) for k, g in self.mix_gains.items() if g > 0]
        if not parts:
            QMessageBox.information(self, APP, t("Все дорожки выключены."))
            return
        path = self._ask_file(self._mix_name())
        if path:
            self._run_export([(path, parts)])

    def export_without(self):
        """Вся песня без отмеченных дорожек; сведение в окне не трогается."""
        keys = [k for k in self.lanes if k not in ("all", "original")
                and not k.startswith("voice") and self._root(k) in ("vocals", "music")]
        if not keys:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(t("Без некоторых дорожек"))
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(6)
        v.addWidget(QLabel(t("Что убрать")))
        boxes = {}

        def follow(key, on):
            # Убрана группа — убраны и её части: отмечать их по одной незачем.
            for kid in self.children.get(key, []):
                if kid in boxes:
                    boxes[kid].setChecked(on)
                    boxes[kid].setEnabled(not on)

        for k in keys:
            box = QCheckBox(self.lanes[k].title)
            box.setStyleSheet(f"margin-left: {(self.lanes[k].depth - 1) * 18}px;")
            box.toggled.connect(lambda on, key=k: follow(key, on))
            boxes[k] = box
            v.addWidget(box)
        v.addSpacing(8)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton(t("Отмена"))
        cancel.setObjectName("text")
        cancel.clicked.connect(dlg.reject)
        save = QPushButton(t("Сохранить"))
        save.setObjectName("text")
        save.clicked.connect(dlg.accept)
        row.addWidget(cancel)
        row.addWidget(save)
        v.addLayout(row)
        if dlg.exec() != QDialog.Accepted:
            return
        gone = {k for k, b in boxes.items() if b.isChecked()}

        def removed(key):
            while key is not None:
                if key in gone:
                    return True
                key = self.parent_of.get(key)
            return False

        leaves = [k for root in ("vocals", "music") if root in self.lanes for k in self._leaves(root)]
        parts = [(self.lanes[k].path, 1.0) for k in leaves if not removed(k)]
        if not parts:
            QMessageBox.information(self, APP, t("Все дорожки выключены."))
            return
        top = [k for k in keys if k in gone and not removed(self.parent_of.get(k))]
        title = self._song_title()
        name = tf("{title} (убраны: {what})", title=title,
                  what=", ".join(self.lanes[k].title.lower() for k in top)) if top else title
        path = self._ask_file(name)
        if path:
            self._run_export([(path, parts)])

    def export_lane(self, key):
        lane = self.lanes.get(key)
        if lane is None:
            return
        path = self._ask_file(f"{self._song_title()} — {lane.title}")
        if path:
            parts = [(lane.path, 1.0)] if lane.path else [(self.lanes[k].path, 1.0) for k in self._leaves(key)]
            self._run_export([(path, parts)])

    def export_all(self):
        start = str(self.settings.value("export_dir", str(Path.home() / "Music")))
        where = QFileDialog.getExistingDirectory(self, t("Папка для дорожек"), start)
        if not where:
            return
        self.settings.setValue("export_dir", where)
        kind, title = self._export_kind(), self._song_title()
        items = [(unique(Path(where) / f"{safe_name(f'{title} — {lane.title}')}.{kind}"), [(lane.path, 1.0)])
                 for k, lane in self.lanes.items() if k != "original" and lane.path]
        self._run_export(items)

    def _run_export(self, items):
        if self.exporting is not None:
            return
        job = ExportJob(items)
        job.done.connect(self._export_done)
        job.failed.connect(self._export_failed)
        job.finished.connect(lambda j=job: self.alive.discard(j))
        self.alive.add(job)
        self.exporting = job
        self.save_btn.setEnabled(False)
        self.save_btn.setText(t("Сохранение…"))
        job.start()

    def _export_done(self, paths):
        self.exporting = None
        self.save_btn.setEnabled(True)
        self.save_btn.setText(t("Сохранить"))
        if paths:
            self._reveal(paths[0])

    def _export_failed(self, text):
        self.exporting = None
        self.save_btn.setEnabled(True)
        self.save_btn.setText(t("Сохранить"))
        QMessageBox.warning(self, APP, tf("Не сохранилось: {e}", e=text))

    def _reveal(self, path: Path):
        path = path or self.folder
        if path is None:
            return
        if sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", "-R", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path if path.is_dir() else path.parent)))

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Undo):
            self.undo_move()
            return
        if (e.key() == Qt.Key_Space and not self.link.hasFocus()
                and self.pages.currentWidget() is self.result_page):
            self.toggle()
        else:
            super().keyPressEvent(e)

    def _build_menu(self):
        if getattr(self, "menubar", None) is not None:
            self.menubar.deleteLater()
        bar = self.menubar = QMenuBar(self)
        about = QAction(tf("О программе {name}", name=APP), self)
        about.setMenuRole(QAction.AboutRole)
        about.triggered.connect(self.show_about)
        menu = bar.addMenu(APP)
        menu.addAction(about)
        prefs = QAction(t("Настройки…"), self)
        prefs.setMenuRole(QAction.PreferencesRole)
        prefs.setShortcut(QKeySequence.Preferences)
        prefs.triggered.connect(self.show_settings)
        menu.addAction(prefs)
        view = bar.addMenu(t("Вид"))
        self.rail_act = QAction(t("Скрыть боковую панель") if getattr(self, "rail_open", True)
                                else t("Показать боковую панель"), self)
        self.rail_act.setMenuRole(QAction.NoRole)
        self.rail_act.setShortcut(QKeySequence("Ctrl+Meta+S"))
        self.rail_act.triggered.connect(self.toggle_rail)
        view.addAction(self.rail_act)
        view.addSeparator()
        for title, items, now, pick in (
                (t("Язык"), (("ru", "Русский"), ("en", "English")), i18n.current(), self.set_language),
                (t("Оформление"), zip(THEMES, (t("Как в системе"), t("Светлое"), t("Тёмное"))),
                 self.theme(), self.set_theme)):
            sub = view.addMenu(title)
            group = QActionGroup(sub)
            for key, label in items:
                act = sub.addAction(label)
                act.setMenuRole(QAction.NoRole)
                act.setCheckable(True)
                act.setChecked(key == now)
                act.triggered.connect(lambda _=False, k=key, f=pick: f(k))
                group.addAction(act)

    def theme(self):
        name = self.settings.value("theme", "system")
        return name if name in THEMES else "system"

    def skin(self):
        name = self.theme()
        if name != "system":
            return name
        return "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"

    def set_theme(self, name):
        self.settings.setValue("theme", name)
        self.apply_theme()

    def apply_theme(self):
        use_palette(self.skin())
        self.setStyleSheet(style(self.family))
        self.divider.setStyleSheet(f"background: {wash(0.06)};")
        for lane in self.lanes.values():
            lane._pix = {}
        for w in self.findChildren(QWidget):
            w.update()

    def set_language(self, lang):
        if lang == i18n.current():
            return
        i18n.set_current(lang)
        self.retranslate()

    def retranslate(self):
        """Перевод собранного окна: ключ ищется по видимой надписи; то, что
        собирается из данных песни, — заново."""
        for w in self.findChildren(QWidget):
            for get, put in (("text", "setText"), ("toolTip", "setToolTip"),
                             ("placeholderText", "setPlaceholderText")):
                if not (hasattr(w, get) and hasattr(w, put)):
                    continue
                try:
                    cur = getattr(w, get)()
                except TypeError:
                    continue
                key = i18n.key_of(cur) if isinstance(cur, str) and cur else None
                if key:
                    getattr(w, put)(t(key))
        self._build_menu()
        self.set_rail(self.rail_open)
        self.guitar._refresh()
        if self.folder is not None and self.pages.currentWidget() is self.result_page:
            self.open_result(self.folder)
        self._busy()
        for w in self.findChildren(QWidget):
            w.update()

    def toggle_rail(self):
        self.set_rail(not self.rail_open)

    def set_rail(self, open_):
        """Свёрнутая колонка — узкая полоса по вертикали значка: «Новая песня»
        и кнопка свёртки остаются на месте, список песен прячется."""
        self.rail_open = bool(open_)
        self.rail.setFixedWidth(RAIL if self.rail_open else RAIL_SLIM)
        m = self.rail_box.contentsMargins()
        side = (12, 8) if self.rail_open else (0, 0)
        self.rail_box.setContentsMargins(side[0], m.top(), side[1], m.bottom())
        self.history.setVisible(self.rail_open)
        self.new_song.setToolTip("" if self.rail_open else t("Новая песня"))
        self.new_song.update()
        self.prefs.setToolTip("" if self.rail_open else t("Настройки"))
        self.prefs.update()
        tip = t("Скрыть боковую панель") if self.rail_open else t("Показать боковую панель")
        self.rail_btn.setToolTip(tip + " · ⌃⌘S")
        self.rail_act.setText(tip)
        self.settings.setValue("rail", self.rail_open)

    def show_settings(self):
        self.settings_win.build()
        self.settings_win.show()
        self.settings_win.raise_()
        self.settings_win.activateWindow()
    def _ask_access_once(self):
        """Каждый запуск — стук в закрытые файлы браузеров: macOS вносит Severance в список
        полного доступа. Спрашиваем один раз, если браузер есть, а его данные закрыты."""
        links.knock()
        if self.settings.value("access_asked") or links.cookie_browsers() or not links.installed_browsers():
            return
        self.settings.setValue("access_asked", "1")
        self.show_access()

    def show_access(self, reason=""):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.NoIcon)
        box.setText(t("Нужен полный доступ к диску"))
        box.setInformativeText(t("Системные настройки → Конфиденциальность и безопасность → "
                                 "Полный доступ к диску"))
        go = box.addButton(t("Открыть настройки"), QMessageBox.AcceptRole)
        box.addButton(t("Не сейчас"), QMessageBox.RejectRole)
        box.setDefaultButton(go)
        box.exec()
        if box.clickedButton() is go:
            self.open_disk_access()

    def open_disk_access(self):
        links.knock()
        import subprocess
        subprocess.run(["open", links.DISK_ACCESS])

    def show_about(self):
        box = QMessageBox(self)
        box.setIconPixmap(app_icon().pixmap(72, 72))
        box.setTextFormat(Qt.RichText)
        box.setText(f"<b>{APP}</b>")
        import support
        box.setInformativeText(f'<nobr>{AUTHOR} · <a href="{URL}">{SITE}</a></nobr><br><br>'
                               f'{t("Поддержать")}<br><nobr>{support.links_html()}</nobr>')
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        # Ссылки ведёт support.follow: адрес кошелька копируется, а не открывается.
        for lab in box.findChildren(QLabel):
            lab.setOpenExternalLinks(False)
            lab.linkActivated.connect(lambda url: support.follow(url, t("Скопировано")))
        box.addButton(t("Закрыть"), QMessageBox.AcceptRole)
        box.exec()

    def closeEvent(self, e):
        self.settings.setValue("geometry", self.saveGeometry())
        self.player.stop()
        super().closeEvent(e)


def _proxy_env():
    """yt-dlp и ffmpeg берут прокси из переменных окружения, а у приложения из
    Finder их нет — переносим системные. Свои адреса — мимо прокси."""
    import urllib.request
    found = urllib.request.getproxies()
    for scheme in ("http", "https"):
        if found.get(scheme):
            os.environ.setdefault(f"{scheme}_proxy", found[scheme])
    skip = [x for x in (os.environ.get("no_proxy") or found.get("no") or "").split(",") if x.strip()]
    os.environ["no_proxy"] = ",".join(dict.fromkeys(skip + ["localhost", "127.0.0.1", "::1"]))


def main():
    _proxy_env()
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setApplicationDisplayName(APP)
    w = Window()
    w.show()
    QTimer.singleShot(0, lambda: print(f"окно через {time.time() - T0:.2f} с", flush=True))
    code = app.exec()
    w.settings.sync()
    # Поток разделения на GPU прервать нельзя, а живой QThread при выходе
    # роняет процесс — выходим жёстко.
    os._exit(code or 0)


if __name__ == "__main__":
    main()
