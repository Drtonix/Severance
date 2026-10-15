"""Язык интерфейса. Ключ перевода — сама русская строка."""
import os
import re

from PySide6.QtCore import QLocale, QSettings

LANGS = ("ru", "en")
SETTINGS = os.environ.get("SEVERANCE_SETTINGS", "Severance")

EN = {
    "Куда ставятся новые модели": "Where new models go",
    "Настройки": "Settings",
    "Настройки…": "Settings…",
    "Модели": "Models",
    "Доступ": "Access",
    "Приложение": "App",
    "Полный доступ к диску": "Full Disk Access",
    "Для записей ВКонтакте, открытых в браузере": "For VK tracks opened in a browser",
    "установится в {where}": "will be installed to {where}",
    "Поддержать": "Support",
    "Скопировано": "Copied",
    "Сбросить": "Reset",
    " — недоступна": " — unavailable",
    "Папка недоступна: {where}": "Folder unavailable: {where}",
    "{gb} ГБ, установится в {where}": "{gb} GB, will be installed to {where}",
    "В {where}": "To {where}",
    "В другую папку…": "To another folder…",
    "Папка для модели": "Folder for this model",
    "Папка для моделей…": "Models folder…",
    " (установится)": " (will be installed)",
    "Текст": "Lyrics",
    "Тембр образца": "Sample's timbre",
    "Запись под оригинал": "Recording to original",
    "Исходное пение голосом образца": "The original singing in the sample's voice",
    "Своя запись песни ложится под оригинал: время и мелодия — от исходного голоса, тембр и слова — от записи":
        "Your recording of the song is fitted to the original: timing and melody from the original voice,"
        " timbre and words from the recording",
    "Своя запись этой песни: музыка уберётся сама": "Your recording of this song: the music is removed",
    "Подставить запись": "Fit recording",
    "Запись": "Recording",
    "Голос записи": "Recording's voice",
    "Подгонка по времени": "Fitting the timing",
    "Разбор голоса": "Analysing the voice",
    "Без некоторых дорожек…": "Without some tracks…",
    "Без некоторых дорожек": "Without some tracks",
    "Что убрать": "What to leave out",
    "{title} (убраны: {what})": "{title} (removed: {what})",
    "Отмена": "Cancel",
    "Пропустить": "Skip",
    "или": "or",
    "Караоке": "Karaoke",
    "С аккордами": "With chords",
    "Найти текст": "Find lyrics",
    "текст — LRCLIB": "lyrics from LRCLIB",
    "текст распознан по голосу": "lyrics recognised from the voice",
    "Спектрограмма": "Spectrogram",
    "Считается…": "Computing…",
    "Гц": "Hz",
    "Левый и правый каналы": "Left and right channels",
    "Каналы одинаковые": "The channels are identical",
    "Левый канал": "Left channel",
    "Правый канал": "Right channel",
    "Голос": "Vocals", "Музыка": "Music", "Оригинал": "Original",
    "Основной голос": "Lead vocal", "Бэк-вокал": "Backing vocals",
    "Барабаны": "Drums", "Бас": "Bass", "Гитара": "Guitar", "Клавишные": "Keys",
    "Другие инструменты": "Other instruments", "Остальное": "Other",
    "Бочка": "Kick", "Малый": "Snare", "Томы": "Toms", "Хай-хэт": "Hi-hat", "Тарелки": "Cymbals",
    "Разложенный": "Separated",
    "Новый голос · {name}": "New voice · {name}",
    "Бэк-вокала в песне нет": "No backing vocals in this song",
    "Музыка на инструменты не делится": "The music doesn't split into instruments",
    "Барабаны не делятся": "The drums don't split",
    "Поёт один исполнитель": "One singer",
    "Один инструмент": "One instrument",
    "Основной голос и бэк-вокал": "Lead and backing vocals",
    "По исполнителям": "By singer",
    "Барабаны, бас, гитара, клавишные и другие инструменты": "Drums, bass, guitar, keys and other instruments",
    "Бочка, малый, томы, хай-хэт и тарелки": "Kick, snare, toms, hi-hat and cymbals",
    "По тембру: инструмент 1, 2…": "By timbre: instrument 1, 2…",
    "По тембру": "By timbre",
    "Число исполнителей…": "Number of singers…",
    "Число инструментов…": "Number of instruments…",
    "Сколько исполнителей": "How many singers",
    "Сколько инструментов": "How many instruments",
    "Определить само": "Detect automatically",
    "разложить": "split",
    "разложить всё": "split all",
    "раскладка": "splitting",
    " или ": " or ",
    "выкл": "off", "дБ": "dB", "соло": "solo", "Вернуть 0 дБ": "Back to 0 dB",
    "Отдать {a}–{b}": "Move {a}–{b} to",
    "Новому исполнителю": "New singer", "Новой дорожке": "New track",
    "Снять выделение": "Clear selection",
    "Переименовать…": "Rename…",
    "Сохранить дорожку…": "Save track…",
    "Показать в Finder": "Show in Finder",
    "Громкость — 0 дБ": "Volume — 0 dB",
    "Имя": "Name",
    "Тональность — по аккордам песни": "Key — from the song's chords",
    "Каподастр": "Capo",
    "С каподастром на этом ладу больше аккордов берётся без баррэ":
        "With the capo on this fret more chords are played without barre",
    "Тон": "Pitch",
    "Подобрать аккорды": "Find chords",
    "{n} лад": "fret {n}",
    "нет": "none",
    "удобнее — {n} лад": "easier — fret {n}",
    "Метроном": "Metronome",
    "Щелчки на найденных ударах — проверить темп на слух": "Clicks on the detected beats — check the tempo by ear",
    "минор": "minor", "мажор": "major",
    "Новая песня": "New song",
    "Скачивание": "Downloading",
    "Подготовка": "Preparing",
    "Загрузка модели": "Loading the model",
    "Разделение": "Separating",
    "Темп": "Tempo",
    "Аккорды": "Chords",
    "Раскладка": "Splitting",
    "Образец голоса": "Voice sample",
    "Модели голоса": "Voice models",
    "Новый голос": "New voice",
    "Кавер": "Cover",
    "отменено": "cancelled",
    "ошибка": "error",
    "Не вышло: {e}": "Failed: {e}",
    "Перетащите песню или видео": "Drop a song or a video",
    "или выберите файл": "or choose a file",
    "Ссылка: YouTube, VK, SoundCloud…": "Link: YouTube, VK, SoundCloud…",
    "Разделить": "Separate",
    "Отменить": "Cancel",
    "Образец": "Sample",
    "выбрать…": "choose…",
    "Песня, запись или видео с нужным голосом: музыка уберётся сама,"
    " возьмутся 10 самых громких секунд голоса":
        "A song, recording or video with the voice you want: the music is removed,"
        " the 10 loudest seconds of voice are used",
    "Октава вниз или вверх — когда образец ниже или выше исходного голоса":
        "An octave down or up — when the sample is lower or higher than the original voice",
    "Качество": "Quality",
    "Быстро — песня за ~2 мин, чисто — за ~3 мин и ближе к образцу":
        "Fast — a song in ~2 min, clean — ~3 min and closer to the sample",
    "быстро": "fast", "чисто": "clean",
    "Сменить голос": "Change voice",
    "Сохранить": "Save",
    "Сохранение…": "Saving…",
    "В Finder": "In Finder",
    "Песня": "Song",
    "Звук и видео": "Audio and video",
    "В корзину": "Move to Trash",
    "Как слышно сейчас…": "As it sounds now…",
    "Все дорожки…": "All tracks…",
    "Все дорожки выключены.": "All tracks are muted.",
    "Папка для дорожек": "Folder for tracks",
    "Не сохранилось: {e}": "Not saved: {e}",
    "{title} (минус)": "{title} (instrumental)",
    "{title} (голос)": "{title} (vocals)",
    "{title} (микс)": "{title} (mix)",
    "О программе {name}": "About {name}",
    "Полный доступ к диску…": "Full Disk Access…",
    "Вид": "View",
    "Язык": "Language",
    "Оформление": "Appearance",
    "Как в системе": "System",
    "Светлое": "Light",
    "Тёмное": "Dark",
    "Скрыть боковую панель": "Hide sidebar",
    "Показать боковую панель": "Show sidebar",
    "Выбрать папку…": "Choose folder…",
    "Закрыть": "Close",
    "Папка для моделей": "Models folder",
    "Нужен полный доступ к диску": "Full Disk Access is needed",
    "Системные настройки → Конфиденциальность и безопасность → Полный доступ к диску":
        "System Settings → Privacy & Security → Full Disk Access",
    "Открыть настройки": "Open Settings",
    "Не сейчас": "Not now",
    "нечего сохранять": "nothing to save",
    "не скачалось: {name}": "not downloaded: {name}",
    "нет окружения смены голоса": "the voice changer is not installed",
    "смена голоса не установлена": "the voice changer is not installed",
    "не вышло": "failed",
    "Не скачалось: ": "Not downloaded: ",
    "Нужен полный доступ к диску.": "Full Disk Access is needed.",
    "Во ВКонтакте не выполнен вход ни в одном браузере ({names}). Войдите и повторите.":
        "You're not signed in to VK in any browser ({names}). Sign in and try again.",
    "ВКонтакте не отдал эту запись: возможно, она удалена или закрыта.":
        "VK didn't return this track: it may be deleted or private.",
    "Поток записи ВКонтакте не скачался: ": "The VK track stream didn't download: ",
    "ВКонтакте изменил устройство плеера: адрес записи не разобрать.":
        "VK changed its player: the track address can't be read.",
    "Этот сайт не поддерживается.": "This site isn't supported.",
    "Сайт отдаёт эту запись только после входа.": "The site gives this track only after signing in.",
    "По ссылке ничего нет: запись удалена или закрыта.": "Nothing at this link: the track is deleted or private.",
    "Сайт не ответил. Проверьте интернет.": "The site didn't respond. Check the internet connection.",
    "{mb} МБ/с": "{mb} MB/s",
    "МБ/с": "MB/s",
    "ещё {h} ч {m} мин": "{h} h {m} min left",
    "ещё {m} мин": "{m} min left",
    "в очереди": "queued",
    ", перед ней {n}": ", {n} ahead",
    ", следующая": ", next",
    "не вышло: {e}": "failed: {e}",
}

_BACK = {v: k for k, v in EN.items()}
# Названия, которые программа даёт частям сама: «Исполнитель 2», «Инструмент 3».
NUMBERED = {"Исполнитель": "Singer", "Инструмент": "Instrument", "Часть": "Part"}
_NUMBERED = re.compile(r"^(" + "|".join(NUMBERED) + r") (\d+)$")
_lang = None


def current():
    global _lang
    if _lang is None:
        saved = QSettings("local", SETTINGS).value("lang", "")
        if saved in LANGS:
            _lang = saved
        else:
            _lang = "ru" if QLocale.system().language() == QLocale.Russian else "en"
    return _lang


def set_current(lang):
    global _lang
    if lang in LANGS:
        _lang = lang
        QSettings("local", SETTINGS).setValue("lang", lang)


def key_of(text):
    if text in EN:
        return text
    return _BACK.get(text)


def t(s):
    return EN.get(s, s) if current() == "en" else s


def tf(fmt, **kw):
    return t(fmt).format(**kw)


def shown(name):
    """Имя дорожки для показа: свои названия частей — переводом, имена,
    которые дал человек, — как есть."""
    if current() != "en" or not name:
        return name
    m = _NUMBERED.match(name)
    if m:
        return f"{NUMBERED[m.group(1)]} {m.group(2)}"
    return EN.get(name, name)


# Подписи хода загрузки моделей — тоже на языке приложения.
import models_home  # noqa: E402

models_home.set_translator(t)
