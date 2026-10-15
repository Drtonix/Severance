"""Значок: круг, расколотый надвое, — половины разошлись по линии разреза.

Градиент один на весь круг, от тёплого к холодному: голос и музыка — одна
песня, разведённая на две. Тем же кругом в окне показан ход разделения.
"""
import math
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPolygonF)

S = 1024
BACK = QColor("#121216")
STOPS = ((0.0, "#ffb15c"), (0.34, "#ff5a7a"), (0.68, "#8a5cff"), (1.0, "#3cc8f0"))
TILT = math.radians(18)    # наклон разреза от вертикали


def gradient(x0, y0, x1, y1):
    g = QLinearGradient(x0, y0, x1, y1)
    for at, c in STOPS:
        g.setColorAt(at, QColor(c))
    return g


def halves(cx, cy, r, gap):
    """Две половины круга, раздвинутые поперёк разреза на gap и сдвинутые вдоль него."""
    dx, dy = math.sin(TILT), -math.cos(TILT)        # вдоль разреза (вверх)
    nx, ny = math.cos(TILT), math.sin(TILT)         # поперёк, вправо
    big = r * 3
    out = []
    for side in (-1, 1):
        plane = QPolygonF([
            QPointF(cx + dx * big, cy + dy * big),
            QPointF(cx + dx * big + nx * big * side, cy + dy * big + ny * big * side),
            QPointF(cx - dx * big + nx * big * side, cy - dy * big + ny * big * side),
            QPointF(cx - dx * big, cy - dy * big),
        ])
        cut = QPainterPath()
        cut.addPolygon(plane)
        disc = QPainterPath()
        disc.addEllipse(QPointF(cx, cy), r, r)
        half = disc.intersected(cut)
        shift = QPointF(nx * gap * side - dx * gap * 0.55 * side, ny * gap * side - dy * gap * 0.55 * side)
        out.append(half.translated(shift))
    return out


def paint(p: QPainter, cx, cy, r, gap):
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(gradient(cx - r, cy - r, cx + r, cy + r)))
    for half in halves(cx, cy, r, gap):
        p.drawPath(half)


def draw(path, layer=False):
    QGuiApplication.instance() or QGuiApplication([])
    img = QImage(S, S, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    if not layer:
        p.fillRect(QRectF(0, 0, S, S), BACK)
    paint(p, S / 2, S / 2, S * 0.30, S * 0.035)
    p.end()
    img.save(path)


if __name__ == "__main__":
    draw(sys.argv[1] if len(sys.argv) > 1 else "icon/AppIcon-1024.png",
         len(sys.argv) > 2 and sys.argv[2] == "layer")
