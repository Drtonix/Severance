#!/bin/zsh
# Самодостаточный Severance.app. Внутри два Python: основной — окно, разделение
# и BPM; второй — смена голоса. Seed-VC требует numpy<2 и распространяется
# под GPL-3.0, поэтому живёт отдельной программой со своими библиотеками.
set -e
setopt null_glob
cd "${0:A:h}"
SRC="$PWD"
OUT="$SRC/build"
APP="$OUT/Severance.app"
REL="https://github.com/astral-sh/python-build-standalone/releases/download/20260901"
PY_URL="$REL/cpython-3.12.14%2B20260901-aarch64-apple-darwin-install_only_stripped.tar.gz"
VPY_URL="$REL/cpython-3.11.16%2B20260901-aarch64-apple-darwin-install_only_stripped.tar.gz"

say() { print -P "%F{green}==>%f $*"; }

rm -rf "$APP"
mkdir -p "$OUT" "$APP/Contents/MacOS" "$APP/Contents/Resources"
RES="$APP/Contents/Resources"

say "переносимый Python"
[ -f "$OUT/python.tar.gz" ] || curl -fsSL "$PY_URL" -o "$OUT/python.tar.gz"
[ -f "$OUT/python311.tar.gz" ] || curl -fsSL "$VPY_URL" -o "$OUT/python311.tar.gz"
mkdir -p "$RES/python" "$RES/voice/python"
tar xzf "$OUT/python.tar.gz" -C "$RES/python" --strip-components=1
tar xzf "$OUT/python311.tar.gz" -C "$RES/voice/python" --strip-components=1
PY="$RES/python/bin/python3"
VPY="$RES/voice/python/bin/python3"

say "библиотеки"
# Версии — ровно те, на которых всё проверено: снимок окружений разработки.
# Не uv export: тот теряет у mlx-cpu пометку «только Linux».
uv pip freeze -q --python .venv/bin/python > "$OUT/req.txt"
uv pip freeze -q --python voice/.venv/bin/python > "$OUT/req_voice.txt"
uv pip install -q --python "$PY" --break-system-packages -r "$OUT/req.txt"
uv pip install -q --python "$VPY" --break-system-packages -r "$OUT/req_voice.txt"

say "чистка лишнего"
SP="$RES/python/lib/python3.12/site-packages"
VSP="$RES/voice/python/lib/python3.11/site-packages"
# Нужны виджеты и QtMultimedia — на нём проигрыватель. Остальное выкидываем.
for m in Qt3D QtCharts QtDataVis QtDesigner QtQuick3D QtSensors QtSerial QtSql \
         QtTest QtBluetooth QtNfc QtRemoteObjects QtScxml QtSpatialAudio \
         QtStateMachine QtTextToSpeech QtHelp QtUiTools QtPdf QtMultimediaQuick \
         QtWebEngine QtWebView QtWebChannel QtWebSockets QtPositioning \
         QtLocation QtQuick QtQml QtGraphs QtVirtualKeyboard QtHttpServer; do
    rm -rf "$SP/PySide6/Qt/lib/${m}"*.framework "$SP/PySide6/${m}"* 2>/dev/null || true
done
rm -rf "$SP/PySide6/Qt/translations" "$SP/PySide6/Qt/qml" \
       "$SP/PySide6/Designer.app" "$SP/PySide6/assistant.app" \
       "$SP/PySide6/linguist.app" "$SP/PySide6/examples" 2>/dev/null || true
# Заголовки C++ у torch нужны только для сборки расширений.
rm -rf "$SP/torch/include" "$VSP/torch/include" "$SP/torch/share" "$VSP/torch/share"
for d in "$RES/python/lib" "$RES/voice/python/lib"; do
    find "$d" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
    find "$d" -name "test" -type d -prune -exec rm -rf {} + 2>/dev/null || true
done

say "байт-код"
# Заранее, а не при первом запуске: из свежего бандла Python иначе компилирует
# каждый импортируемый модуль. unchecked-hash — байт-код не сверяется с датами
# файлов, копирование бандла его не портит. Окружение смены голоса не трогаем:
# там 365 МБ байт-кода, а нужна малая часть — она запишется при первой смене.
"$PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$RES/python/lib/python3.12" >/dev/null 2>&1 || true

say "ffmpeg"
# Своя сборка: готовые либо x86_64, либо с --enable-nonfree (распространять
# нельзя). Здесь arm64 и чистый LGPL 2.1, с сетью и системным TLS macOS.
mkdir -p "$RES/app/bin" "$OUT/tools"
if [ ! -f "$OUT/tools/ffmpeg" ]; then
    say "  сборка ffmpeg из исходников, это несколько минут"
    rm -rf "$OUT/ffsrc"; mkdir -p "$OUT/ffsrc"
    curl -fsSL "https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz" -o "$OUT/ffsrc/ff.tar.xz"
    tar xf "$OUT/ffsrc/ff.tar.xz" -C "$OUT/ffsrc" --strip-components=1
    ( cd "$OUT/ffsrc" && ./configure --prefix="$OUT/ffsrc/out" --disable-doc \
        --disable-ffplay --disable-debug --enable-small --disable-autodetect \
        --enable-zlib --enable-videotoolbox --enable-securetransport >/dev/null 2>&1 \
      && make -j"$(sysctl -n hw.ncpu)" >/dev/null 2>&1 \
      && make install >/dev/null 2>&1 )
    cp "$OUT/ffsrc/out/bin/ffmpeg" "$OUT/ffsrc/out/bin/ffprobe" "$OUT/tools/"
    rm -rf "$OUT/ffsrc"
fi
cp "$OUT/tools/ffmpeg" "$OUT/tools/ffprobe" "$RES/app/bin/"
chmod +x "$RES/app/bin/"*

say "исходники"
cp app.py engine.py guitar.py i18n.py links.py models_home.py support.py "$RES/app/"
cp voice/convert.py voice/singers.py "$RES/voice/"
# Отпечатки голосов TitaNet (sherpa-onnx): в репозитории не лежат — 97 МБ.
TITANET="voice/models/nemo_en_titanet_large.onnx"
if [ ! -f "$TITANET" ]; then
    mkdir -p voice/models
    curl -fsSL "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_large.onnx" -o "$TITANET"
fi
echo "d51abcf31717ef28162f26acb9d44dd4127c3d44c9b8624f699f3425daca8e77  $TITANET" | shasum -a 256 -c - >/dev/null
cp -R voice/models "$RES/voice/"
"$PY" -m compileall -q --invalidation-mode unchecked-hash "$RES/app" >/dev/null

say "лицензии"
LIC="$RES/Лицензии"
mkdir -p "$LIC"
# find, а не шаблон: zsh на пустом совпадении падает, а с set -e рвёт сборку.
for sp in "$SP" "$VSP"; do
    find "$sp" -maxdepth 1 -type d -name "*.dist-info" | while read -r d; do
        pkg=$(basename "$d" .dist-info)
        find "$d" -maxdepth 2 \( -name "LICENSE*" -o -name "COPYING*" -o -name "NOTICE*" \) \
            -type f 2>/dev/null | while read -r f; do
            mkdir -p "$LIC/$pkg"
            cp "$f" "$LIC/$pkg/" 2>/dev/null || true
        done
    done
done
cat > "$LIC/О лицензиях.txt" <<'LICNOTE'
Из чего собран Severance и на каких условиях.

Qt / PySide6 — LGPL 3.0
    Библиотеки Qt лежат в приложении отдельными файлами и не вкомпилированы
    в него, поэтому их можно заменить своими сборками. Исходники:
    https://download.qt.io/official_releases/qt/

ffmpeg — LGPL 2.1 или новее
    Собран без компонентов под GPL: ./configure --disable-doc --disable-ffplay
    --disable-debug --enable-small --disable-autodetect --enable-zlib
    --enable-videotoolbox --enable-securetransport
    Исходники: https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz

Seed-VC — GPL 3.0
    Смена голоса. Отдельная программа: Resources/voice, свой Python и свои
    библиотеки; Severance запускает её и читает только готовый звук.
    Исходники: https://github.com/Plachtaa/seed-vc

Python — PSF License
LICNOTE

say "интерпретатор в MacOS"
# macOS зовёт программу по имени файла процесса: питон из Resources даёт
# в доке ракету и имя «python3». Интерпретатор кладём в MacOS под именем
# приложения; он статический, свою установку находит по PYTHONHOME.
cp "$RES/python/bin/python3.12" "$APP/Contents/MacOS/Severance"

say "оболочка"
cat > "$APP/Contents/MacOS/launcher" <<'LAUNCH'
#!/bin/zsh
zmodload zsh/datetime
export SEVERANCE_T0=$EPOCHREALTIME
LOG="$HOME/Library/Logs/Severance.log"
mkdir -p "$HOME/Library/Logs"
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG")" -gt 5000000 ]; then : > "$LOG"; fi
exec >> "$LOG" 2>&1
echo "=== запуск $(date) ==="
DIR="${0:A:h}"
RES="$DIR/../Resources"
export PATH="$RES/app/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONHOME="$RES/python"
# Бандл подписан и после установки не меняется: любая запись внутрь — и macOS
# при следующем запуске проверяет все 2,5 ГБ заново. Байт-код собран заранее.
export PYTHONDONTWRITEBYTECODE=1
export NUMBA_CACHE_DIR="$HOME/Library/Caches/Severance/numba"
cd "$RES/app"
exec "$DIR/Severance" "$RES/app/app.py"
LAUNCH
chmod +x "$APP/Contents/MacOS/launcher"
# Assets.car — значок в светлом и тёмном варианте; icns — для старых систем.
cp icon/AppIcon.icns "$RES/AppIcon.icns"
cp icon/Assets.car "$RES/Assets.car"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleDevelopmentRegion</key><string>ru</string>
<key>CFBundleLocalizations</key><array><string>ru</string><string>en</string></array>
<key>CFBundleDisplayName</key><string>Severance</string>
<key>CFBundleExecutable</key><string>launcher</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundleIconName</key><string>AppIcon</string>
<key>CFBundleIdentifier</key><string>space.bdub.severance</string>
<key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
<key>CFBundleName</key><string>Severance</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSDocumentsFolderUsageDescription</key><string>Severance открывает песни из папки «Документы».</string>
<key>NSDownloadsFolderUsageDescription</key><string>Severance открывает песни из папки «Загрузки».</string>
<key>NSDesktopFolderUsageDescription</key><string>Severance открывает песни с рабочего стола.</string>
<key>NSRemovableVolumesUsageDescription</key><string>Severance открывает песни с внешних дисков.</string>
<key>NSHumanReadableCopyright</key><string>DrTonix · bdub.space</string>
</dict></plist>
PLIST

say "подпись"
# Без подписи первый запуск после установки — около 29 с: macOS проверяет
# неподписанный бандл целиком. С подписью (ad hoc, без сертификата) — около 7 с,
# дальше — меньше секунды.
codesign --force --deep --sign - "$APP" 2>/dev/null
codesign --verify --deep --strict "$APP"

say "готово: $(du -sh "$APP" | cut -f1)  ->  $APP"

# Копия в build — не второе приложение в Launchpad и Spotlight: снимаем с учёта.
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u "$APP" >/dev/null 2>&1 || true
