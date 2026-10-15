#!/bin/zsh
# Образ для установки: приложение и ярлык «Программы». После build_app.sh.
set -e
cd "${0:A:h}"
OUT="$PWD/build"
DMG="$OUT/Severance.dmg"

[ -d "$OUT/Severance.app" ] || { echo "Сначала ./build_app.sh"; exit 1; }

say() { print -P "%F{green}==>%f $*"; }

say "сборка образа"
rm -f "$DMG"
PY=./.venv/bin/python
[ -x "$PY" ] || PY=python3
"$PY" -m dmgbuild -s dmg_settings.py Severance "$DMG"

say "готово: $(du -sh "$DMG" | cut -f1)  ->  $DMG"
