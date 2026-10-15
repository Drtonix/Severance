#!/bin/zsh
# Иконка собирается из документа Icon Composer: один слой с половинами круга на
# прозрачном фоне, подложку и тень macOS рисует сама и по-своему для светлой и
# тёмной темы. Варианты лежат в Assets.car; .icns остаётся для старых систем.
set -e
cd "${0:A:h}/.."
PY=${PY:-./.venv/bin/python}
ACTOOL=/Applications/Xcode.app/Contents/Developer/usr/bin/actool
ICTOOL="/Applications/Xcode.app/Contents/Applications/Icon Composer.app/Contents/Executables/ictool"

"$PY" icon/drawicon.py icon/AppIcon.icon/Assets/halves.png layer
"$PY" icon/drawicon.py icon/AppIcon-1024.png

if [ -x "$ACTOOL" ]; then
    OUT=$(mktemp -d)
    "$ACTOOL" icon/AppIcon.icon --compile "$OUT" --platform macosx \
        --minimum-deployment-target 26.0 --app-icon AppIcon \
        --output-partial-info-plist "$OUT/partial.plist" >/dev/null
    cp "$OUT/Assets.car" icon/Assets.car
    # .icns рисуем тем же движком, что и каталог, иначе запасной значок
    # отличается от того, что показывает док.
    rm -rf "$OUT/set.iconset" && mkdir -p "$OUT/set.iconset"
    for sz in 16 32 128 256 512; do
        "$ICTOOL" icon/AppIcon.icon --export-image --platform macOS --rendition Default \
            --output-file "$OUT/set.iconset/icon_${sz}x${sz}.png" --width $sz --height $sz --scale 1 >/dev/null
        "$ICTOOL" icon/AppIcon.icon --export-image --platform macOS --rendition Default \
            --output-file "$OUT/set.iconset/icon_${sz}x${sz}@2x.png" --width $sz --height $sz --scale 2 >/dev/null
    done
    # ictool отдаёт скруглённый квадрат во всю картинку, а у значков macOS
    # поля: 100 точек из 1024 с каждой стороны. Без них значок крупнее соседей.
    "$PY" - "$OUT/set.iconset" <<'PAD'
import sys
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
QGuiApplication([])
for f in Path(sys.argv[1]).glob("*.png"):
    img = QImage(str(f))
    n = img.width()
    body = round(n * 824 / 1024)
    out = QImage(n, n, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    off = (n - body) // 2
    p.drawImage(off, off, img.scaled(body, body, Qt.IgnoreAspectRatio,
                                     Qt.SmoothTransformation))
    p.end()
    out.save(str(f))
PAD
    iconutil -c icns "$OUT/set.iconset" -o icon/AppIcon.icns
    # Windows: квадрат со скруглением во всю картинку, без полей macOS.
    mkdir -p "$OUT/ico"
    for sz in 16 24 32 48 64 128 256; do
        "$ICTOOL" icon/AppIcon.icon --export-image --platform macOS --rendition Default \
            --output-file "$OUT/ico/$sz.png" --width $sz --height $sz --scale 1 >/dev/null
    done
    "$PY" icon/make_ico.py "$OUT/ico" icon/AppIcon.ico
    rm -rf "$OUT"
    echo "готово: Assets.car со всеми темами и запасной AppIcon.icns"
else
    rm -rf /tmp/iconset.iconset && mkdir -p /tmp/iconset.iconset
    for sz in 16 32 64 128 256 512; do
        sips -z $sz $sz icon/AppIcon-1024.png --out /tmp/iconset.iconset/icon_${sz}x${sz}.png >/dev/null
        sips -z $((sz*2)) $((sz*2)) icon/AppIcon-1024.png --out /tmp/iconset.iconset/icon_${sz}x${sz}@2x.png >/dev/null
    done
    iconutil -c icns /tmp/iconset.iconset -o icon/AppIcon.icns
    echo "готово: только AppIcon.icns — actool не найден"
fi
