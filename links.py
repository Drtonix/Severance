"""Песня по ссылке: yt-dlp для сайтов, свой путь — для музыки ВКонтакте.

Музыку ВК yt-dlp не берёт вовсе, а сам ВК отдаёт её только вошедшим. Вход —
cookies браузера, как у Konspekt: тот браузер, где есть сессия ВК. Папки
браузеров macOS закрывает от других программ — без «Полного доступа к диску»
cookies не прочитать, и об этом говорит NeedsAccess.

Ссылку на поток спрашиваем так же, как веб-плеер ВК: сначала через API с
токеном веб-версии, потом через старый адрес плеера. Поток — HLS, его
скачивает ffmpeg; адрес в ответе бывает перемешан — тогда он раскладывается
обратно по ключу (алгоритм плеера ВК, как в vk_api).
"""
import json
import re
import subprocess
import urllib.parse
from pathlib import Path

from i18n import t

DISK_ACCESS = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"


class SourceError(Exception):
    """Ошибка ссылки: текст показывается человеку как есть."""


class NeedsAccess(SourceError):
    """Нужен вход на сайт, а данные браузеров закрыты."""


# Где какой браузер держит cookies (как в Konspekt). Safari — в защищённой
# папке, остальные macOS тоже закрывает без полного доступа к диску.
COOKIE_STORES = {
    "chrome": ["Library/Application Support/Google/Chrome/*/Cookies",
               "Library/Application Support/Google/Chrome/*/Network/Cookies"],
    "safari": ["Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies"],
    "firefox": ["Library/Application Support/Firefox/Profiles/*/cookies.sqlite"],
    "brave": ["Library/Application Support/BraveSoftware/Brave-Browser/*/Cookies",
              "Library/Application Support/BraveSoftware/Brave-Browser/*/Network/Cookies"],
    "edge": ["Library/Application Support/Microsoft Edge/*/Cookies",
             "Library/Application Support/Microsoft Edge/*/Network/Cookies"],
}
TITLES = {"chrome": "Chrome", "safari": "Safari", "firefox": "Firefox", "brave": "Brave", "edge": "Edge"}
INSTALLED = {"chrome": "Library/Application Support/Google/Chrome",
             "safari": "Library/Safari",
             "firefox": "Library/Application Support/Firefox",
             "brave": "Library/Application Support/BraveSoftware/Brave-Browser",
             "edge": "Library/Application Support/Microsoft Edge"}


def knock():
    """Попытка прочитать закрытые файлы браузеров. Отказ macOS запоминает и вносит
    программу в список «Полного доступа к диску» — остаётся включить переключатель."""
    for rel in ("Library/Safari/Bookmarks.plist", "Library/Application Support/Google/Chrome/Local State"):
        try:
            with open(Path.home() / rel, "rb") as f:
                f.read(1)
        except OSError:
            pass


def installed_browsers():
    return [b for b, p in INSTALLED.items() if (Path.home() / p).exists()]


def cookie_browsers():
    """Браузеры, чьи cookies читаются прямо сейчас."""
    out = []
    for name, patterns in COOKIE_STORES.items():
        try:
            paths = [p for pat in patterns for p in Path.home().glob(pat)]
        except OSError:
            continue
        for path in paths:
            try:
                with open(path, "rb") as f:
                    f.read(1)
                out.append(name)
                break
            except OSError:
                pass
    return out


VK_HOST = re.compile(r"(?:^|//|\.)vk\.(?:com|ru)/", re.I)
VK_AUDIO = re.compile(r"audio(-?\d+)_(\d+)(?:_([0-9a-f]+))?")
VK_APP = 6287487            # веб-версия ВК: её токен выдаётся по cookies сессии


def is_vk_audio(url):
    return bool(VK_HOST.search(url) and VK_AUDIO.search(url))


def _vk_session():
    """yt-dlp с cookies того браузера, где есть сессия ВК."""
    from yt_dlp import YoutubeDL
    readable = cookie_browsers()
    if not readable:
        raise NeedsAccess(t("Нужен полный доступ к диску."))
    for browser in readable:
        y = YoutubeDL({"cookiesfrombrowser": (browser,), "quiet": True, "no_warnings": True})
        try:
            jar = y.cookiejar
        except Exception:
            y.close()
            continue
        if any(c.name == "remixsid" and "vk." in c.domain for c in jar):
            return y
        y.close()
    raise SourceError(t("Во ВКонтакте не выполнен вход ни в одном браузере ({names}). Войдите и повторите.")
                      .format(names=", ".join(TITLES[b] for b in readable)))


def _post(y, url, data, referer="https://vk.ru/"):
    from yt_dlp.networking import Request
    req = Request(url, data=urllib.parse.urlencode(data).encode(), headers={
        "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://vk.ru", "Referer": referer})
    return y.urlopen(req).read().decode("utf-8", "replace")


def _vk_by_api(y, ids):
    """Токен веб-версии по cookies → audio.getById."""
    from yt_dlp.networking import Request
    raw = _post(y, "https://login.vk.ru/?act=web_token", {"version": 1, "app_id": VK_APP})
    data = json.loads(raw).get("data") or {}
    token, user = data.get("access_token"), data.get("user_id")
    if not token:
        raise ValueError(f"web_token: {json.loads(raw).get('type', 'нет токена')}")
    q = urllib.parse.urlencode({"audios": ids, "access_token": token, "v": "5.199"})
    j = json.loads(y.urlopen(Request("https://api.vk.ru/method/audio.getById?" + q)).read())
    if "error" in j:
        e = j["error"]
        raise ValueError(f"audio.getById: {e.get('error_code')} {e.get('error_msg')}")
    a = (j.get("response") or [{}])[0]
    return {"url": a.get("url", ""), "artist": a.get("artist", ""), "title": a.get("title", ""),
            "duration": a.get("duration", 0), "user": user}


def _vk_by_player(y, ids):
    """Старый адрес веб-плеера: ответ — массивы, адрес — третий элемент."""
    for act, field in (("reload_audios", "audio_ids"), ("reload_audio", "ids")):
        raw = _post(y, f"https://vk.ru/al_audio.php?act={act}", {"al": 1, field: ids})
        try:
            j = json.loads(raw.strip().removeprefix("<!--"))
        except ValueError:
            continue
        item = _first_audio(j)
        if item:
            return {"url": item[2] or "", "artist": item[4] if len(item) > 4 else "",
                    "title": item[3] if len(item) > 3 else "", "duration": item[5] if len(item) > 5 else 0,
                    "user": None}
    raise ValueError("al_audio: в ответе нет записи")


def _first_audio(o):
    if isinstance(o, list) and len(o) > 5 and isinstance(o[0], int) and isinstance(o[2], str):
        return o
    if isinstance(o, dict):
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            r = _first_audio(v)
            if r:
                return r
    return None


def vk_download(url, folder: Path, progress=None, stop=None):
    """Аудиозапись ВК → файл. Возвращает (файл, название)."""
    owner, aid, key = VK_AUDIO.search(url).groups()
    ids = "_".join(x for x in (owner, aid, key) if x)
    y = _vk_session()
    tried = []
    track = None
    with y:
        for way in (_vk_by_api, _vk_by_player):
            try:
                track = way(y, ids)
                if track.get("url"):
                    break
                tried.append(f"{way.__name__}: пустой адрес")
            except Exception as e:
                tried.append(f"{way.__name__}: {e}")
        print("ВК:", "; ".join(tried) or "адрес получен", flush=True)
        if not track or not track.get("url"):
            raise SourceError(t("ВКонтакте не отдал эту запись: возможно, она удалена или закрыта."))
        stream = track["url"]
        if "audio_api_unavailable" in stream:
            user = track.get("user") or _vk_user(y)
            stream = decode_url(stream, int(user))
    title = " - ".join(x for x in (track.get("artist"), track.get("title")) if x) or f"vk{owner}_{aid}"
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / f"vk{owner}_{aid}.mka"
    _fetch_stream(stream, dst, float(track.get("duration") or 0), progress, stop)
    return dst, _clean_title(title)


def _vk_user(y):
    raw = _post(y, "https://login.vk.ru/?act=web_token", {"version": 1, "app_id": VK_APP})
    return (json.loads(raw).get("data") or {}).get("user_id") or 0


def _clean_title(text):
    import html
    return html.unescape(text).strip()


def _fetch_stream(url, dst: Path, duration, progress=None, stop=None):
    """HLS или MP3 по адресу → файл, как есть, без перекодирования."""
    import engine
    tmp = dst.with_name(dst.name + ".part")
    cmd = [engine.tool("ffmpeg"), "-v", "error", "-y", "-nostdin", "-i", url, "-vn", "-c:a", "copy",
           "-f", "matroska", "-progress", "pipe:1", str(tmp)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in p.stdout:
        if stop and stop():
            p.kill()
            raise SourceError(t("отменено"))
        if line.startswith("out_time_us=") and duration and progress:
            try:
                progress(min(int(line.split("=")[1]) / 1e6 / duration, 1.0))
            except ValueError:
                pass
    err = p.stderr.read()
    if p.wait() != 0 or not tmp.exists() or tmp.stat().st_size < 10_000:
        tmp.unlink(missing_ok=True)
        raise SourceError(t("Поток записи ВКонтакте не скачался: ") + (err.strip().splitlines() or ["ffmpeg"])[-1][:160])
    tmp.replace(dst)


# Перемешанный адрес плеера ВК («audio_api_unavailable.mp3?extra=…#…»).
_VK_ABC = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/="


def decode_url(url, user_id):
    extra, ops = url.split("?extra=", 1)[1].split("#", 1)
    text = _o(extra)
    for op in reversed(_o(ops).split("\t")):
        cmd, *arg = op.split("\v")
        arg = arg[0] if arg else None
        if cmd == "v":
            text = text[::-1]
        elif cmd == "r":
            text = _r(text, int(arg))
        elif cmd == "x":
            text = "".join(chr(ord(c) ^ ord(arg[0])) for c in text)
        elif cmd == "s":
            text = _s(text, int(arg))
        elif cmd == "i":
            text = _s(text, int(arg) ^ user_id)
        else:
            raise SourceError(t("ВКонтакте изменил устройство плеера: адрес записи не разобрать."))
    return text


def _o(s):
    out, n, acc = [], 0, 0
    for ch in s:
        k = _VK_ABC.find(ch)
        if k == -1:
            continue
        acc = (acc << 6) + k if n % 4 else k
        n += 1
        if (n - 1) % 4:
            out.append(chr(0xFF & (acc >> (-2 * n & 6))))
    return "".join(out)


def _r(s, shift):
    abc = _VK_ABC + _VK_ABC
    out = []
    for ch in s:
        k = abc.find(ch)
        out.append(abc[(k - shift) % len(abc)] if k != -1 else ch)
    return "".join(out)


def _s(s, seed):
    n = len(s)
    if not n:
        return s
    order, e = [], seed
    for a in range(n - 1, -1, -1):
        e = (n * (a + 1) ^ e + a) % n
        order.append(e)
    order.reverse()
    chars = list(s)
    for a in range(1, n):
        j = order[n - 1 - a]
        chars[a], chars[j] = chars[j], chars[a]
    return "".join(chars)


def human_error(text):
    """Ошибка yt-dlp → фраза для человека; None — если не узнали."""
    t = text.lower()
    if "unsupported url" in t:
        return t("Этот сайт не поддерживается.")
    if any(k in t for k in ("sign in", "log in", "login", "logged-in", "cookies", "private")):
        return t("Сайт отдаёт эту запись только после входа.")
    if any(k in t for k in ("http error 404", "not found", "does not exist", "unavailable")):
        return t("По ссылке ничего нет: запись удалена или закрыта.")
    if any(k in t for k in ("timed out", "connection", "network", "resolve", "unable to download webpage")):
        return t("Сайт не ответил. Проверьте интернет.")
    return None
