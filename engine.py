"""Разделение песни: голос и музыка, дальше — на части, BPM и аккорды.

Голос и музыка — BS-RoFormer (песня 4:08 за ~40 с на M4 Max). Дальше каждая
дорожка раскладывается своей моделью: музыка — BS-Roformer-SW на шесть
инструментов, барабаны — MDX23C DrumSep на бочку, малый, томы, хай-хэт и
тарелки, голос — караоке-модель на основной и бэк. Все — mlx-audio-separator.
BPM — Beat This!, аккорды — lv-chordia; обе на torch, по несколько секунд.
"""
import gc
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

import i18n

HERE = Path(__file__).resolve().parent
SR = 44100
APP_DIR = Path.home() / "Library" / "Application Support" / "Severance"
MODELS = APP_DIR / "models"
# Seed-VC кладёт свои веса в ./checkpoints от текущей папки — запускается отсюда.
VOICE_HOME = APP_DIR / "voice"


def model_home(kind):
    """Куда класть новые модели: в общую папку моделей всех приложений
    (models_home), если она выбрана и диск подключён, иначе к себе."""
    import models_home
    base = models_home.folder()
    if base is not None and models_home.mounted(base):
        return Path(base) / "Severance" / kind
    return APP_DIR / kind


def models_dir(model):
    """Папка разделителя: где модель уже лежит, иначе — куда качать новые."""
    for d in (MODELS, model_home("models")):
        if (d / model).exists():
            return d
    return model_home("models")


def voice_home():
    """Папка весов Seed-VC: где они уже есть, иначе — куда качать новые."""
    for d in (VOICE_HOME, model_home("voice")):
        if (d / "checkpoints").exists():
            return d
    return model_home("voice")
INFO = "severance.json"

# Лучший по сумме оценок вокал и музыка одной моделью: SDR вокала 12,97 на
# многопесенном наборе MVSEP, обе дорожки за один проход.
BEST_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
# Для образца голоса: четыре модели demucs вместе чище одной шестидорожечной.
FAST_MODEL = "htdemucs_ft"
# Ключ → имя файла в папке песни: файлы перетаскивают в другие программы как есть.
FILES = {"vocals": "Голос", "music": "Музыка", "original": "Оригинал",
         "lead": "Основной голос", "back": "Бэк-вокал",
         "drums": "Барабаны", "bass": "Бас", "guitar": "Гитара", "piano": "Клавишные",
         "other": "Другие инструменты",
         "kick": "Бочка", "snare": "Малый", "toms": "Томы", "hh": "Хай-хэт", "cymbals": "Тарелки"}
FILES_EN = {"vocals": "Vocals", "music": "Music", "original": "Original",
            "lead": "Lead vocal", "back": "Backing vocals",
            "drums": "Drums", "bass": "Bass", "guitar": "Guitar", "piano": "Keys",
            "other": "Other instruments",
            "kick": "Kick", "snare": "Snare", "toms": "Toms", "hh": "Hi-hat", "cymbals": "Cymbals"}
# Так дорожки звались раньше — песни, разложенные тогда, открываются по-старому.
LEGACY = {"other": "Остальное"}
# Части, которые программа называет сама, в имени файла: «Песня — исполнитель 2».
PART_WORDS = {"singer": ("исполнитель", "singer"), "timbre": ("инструмент", "instrument")}


def default_file(key: str) -> str:
    """Имя файла новой дорожки — на языке интерфейса."""
    return (FILES_EN if i18n.current() == "en" else FILES)[key]


def part_word(kind: str) -> str:
    ru, en = PART_WORDS[kind]
    return en if i18n.current() == "en" else ru


def drop_parts(folder: Path, stem: str, kind: str):
    """Старые части перед новой раскладкой — с именами на любом из языков."""
    for word in PART_WORDS[kind]:
        for old in folder.glob(f"{stem} — {word} *.wav"):
            old.unlink(missing_ok=True)


def track(folder: Path, key: str, info: dict = None) -> Path:
    """Файл дорожки песни: тот, что есть на диске, под каким бы языком он ни
    был назван."""
    return folder / f"{stem_file(load_info(folder) if info is None else info, key, folder)}.wav"
# Что из чего раскладывается. stems — выход модели → наша дорожка (несколько
# выходов могут слиться в одну); fold — куда уходят тихие дорожки; rest — куда
# уходит не разнесённый моделью остаток.
SPLITS = {
    "vocals": {"model": "mel_band_roformer_karaoke_becruily.ckpt",
               "stems": {"vocals": "lead", "instrumental": "back"},
               "order": ("lead", "back"), "fold": "lead", "rest": "back",
               "none": "Бэк-вокала в песне нет"},
    "music": {"model": "BS-Roformer-SW.ckpt",
              "stems": {"drums": "drums", "bass": "bass", "guitar": "guitar", "piano": "piano",
                        "other": "other", "vocals": "other"},
              "order": ("drums", "bass", "guitar", "piano", "other"), "fold": "other", "rest": "other",
              "none": "Музыка на инструменты не делится"},
    "drums": {"model": "MDX23C-DrumSep-aufr33-jarredou.ckpt",
              "stems": {"kick": "kick", "snare": "snare", "toms": "toms", "hh": "hh",
                        "ride": "cymbals", "crash": "cymbals"},
              "order": ("kick", "snare", "toms", "hh", "cymbals"), "fold": "cymbals",
              "none": "Барабаны не делятся"},
}
# Тише этого относительно целой дорожки — части в песне нет, а дорожка —
# просачивание соседей. Такие уходят в fold.
QUIET_DB = -30.0


def tool(name: str) -> str:
    own = HERE / "bin" / (name + (".exe" if sys.platform == "win32" else ""))
    return str(own) if own.exists() else (shutil.which(name) or name)


def decode(src, dst: Path) -> Path:
    """Любой звук или видео → WAV 44,1 кГц стерео: оба разделителя ждут его."""
    r = subprocess.run([tool("ffmpeg"), "-v", "error", "-y", "-i", str(src), "-vn",
                        "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)],
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip()[-300:] or "ffmpeg")
    return dst


def read_wav(path) -> np.ndarray:
    """WAV → int16 [кадры, 2]: в памяти вдвое меньше float, для плеера хватает."""
    import soundfile as sf
    data, sr = sf.read(str(path), dtype="int16", always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    return np.ascontiguousarray(data[:, :2])


def write_wav(path, data: np.ndarray):
    import soundfile as sf
    sf.write(str(path), data, SR, subtype="PCM_16")


EXPORT = ("mp3", "wav", "flac")


def export(parts, dst: Path):
    """Дорожки — в один файл: parts — [(wav, множитель громкости)].

    Сумма громче 0 дБ не срезается, а вся становится тише ровно настолько:
    поднятая громкость частей не превращается в хрип. MP3 — свой кодировщик
    (lameenc): в ffmpeg приложения его нет."""
    import soundfile as sf
    mix, rate = None, SR
    for path, gain in parts:
        data, rate = sf.read(str(path), dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        data = data[:, :2] * gain
        if mix is None:
            mix = data
            continue
        if len(data) > len(mix):
            mix, data = data, mix
        mix[:len(data)] += data
    if mix is None:
        raise ValueError(i18n.t("нечего сохранять"))
    peak = float(np.abs(mix).max()) if len(mix) else 0.0
    if peak > 0.999:
        mix *= 0.999 / peak
    kind = dst.suffix.lower().lstrip(".")
    tmp = dst.with_name(dst.name + ".part")
    if kind == "mp3":
        import lameenc
        enc = lameenc.Encoder()
        enc.set_bit_rate(320)
        enc.set_in_sample_rate(rate)
        enc.set_channels(2)
        enc.set_quality(2)
        pcm = np.round(np.clip(mix, -1.0, 1.0) * 32767).astype(np.int16)
        tmp.write_bytes(enc.encode(pcm.tobytes()) + enc.flush())
    else:
        sf.write(str(tmp), mix, rate, format=kind.upper(), subtype="PCM_16")
    tmp.replace(dst)
    return dst


def _download(url, path, progress=None):
    """Вместо загрузчика mlx-audio-separator: тот пишет файл сразу под
    окончательным именем, и оборванная загрузка выдаёт себя за модель.
    Здесь — во временный файл, с докачкой после обрыва."""
    import requests
    path = Path(path)
    if path.is_file():
        return
    part = path.with_name(path.name + ".part")
    for attempt in range(8):
        have = part.stat().st_size if part.exists() else 0
        try:
            r = requests.get(url, stream=True, timeout=60,
                             headers={"Range": f"bytes={have}-"} if have else {})
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 404:
            raise RuntimeError(f"Failed to download file from {url}, response code: 404")
        if r.status_code == 416:        # уже всё скачано
            break
        if r.status_code not in (200, 206):
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            have = 0
        total = have + int(r.headers.get("content-length") or 0)
        try:
            with open(part, "ab" if have else "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
                    have += len(chunk)
                    if progress and total:
                        progress("download", have / total)
        except (requests.RequestException, OSError):
            time.sleep(2 * (attempt + 1))
            continue
        if not total or have >= total:
            break
    else:
        raise RuntimeError(i18n.tf("не скачалось: {name}", name=path.name))
    part.rename(path)


class Stopped(Exception):
    """Работа отменена: бросается из хода работы между кусками."""


# Текст считается своим потоком рядом с разделением; MLX из двух потоков
# сразу не работает, поэтому модели по очереди.
GPU = threading.RLock()
# Отпущенные буферы MLX по умолчанию держит у себя, и на раскладке память видеокарты
# доходила до 8,5 ГБ при 0,1 ГБ свободных: macOS начинала сжимать чужую память,
# подтормаживали окна и прерывался звук. С пределом 0,5 ГБ — около 6 ГБ и 2 ГБ
# свободных, раскладка дольше на 0–9%.
MLX_CACHE = 512 * 2**20


def _mlx_ready():
    import mlx.core as mx
    mx.set_cache_limit(MLX_CACHE)


def run_model(model: str, src: Path, out: Path, progress=None) -> dict:
    """Модель mlx-audio-separator → {имя выхода в нижнем регистре: файл}.
    progress(kind, share): «download» — загрузка модели, «split» — разделение.
    Модель при первом запуске качается и переводится в MLX; переведённые веса
    сохраняются — дальше без пересчёта."""
    from mlx_audio_separator import Separator
    import mlx_audio_separator.separator.architectures.mdxc_separator as mdxc

    def steps(it, *_, **__):
        # Цикл по кускам песни: шаги идут ровно по времени работы модели.
        items = list(it)
        for i, x in enumerate(items):
            if progress:
                progress("split", i / max(len(items), 1))
            yield x

    where = models_dir(model)
    where.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    saved = mdxc.tqdm
    mdxc.tqdm = steps
    try:
        sep = Separator(model_file_dir=str(where), output_dir=str(out), output_format="WAV",
                        save_converted_safetensors=True, log_level=30)
        sep.download_file_if_not_exists = lambda url, path: _download(url, path, progress)
        with GPU:
            _mlx_ready()
            sep.load_model(model)
            files = sep.separate(str(src))
    finally:
        mdxc.tqdm = saved
    # Сбой разделитель пишет в журнал и отдаёт пустой список — без этой
    # проверки он выглядел бы как «делить нечего» и запоминался навсегда.
    if getattr(sep, "failed_files", None):
        raise RuntimeError(sep.failed_files[0][1] or "separation failed")
    stems = {}
    for f in files:
        p = Path(f) if Path(f).is_absolute() else out / f
        m = re.search(r"_\(([^)]+)\)_", p.name)
        stems[(m.group(1) if m else p.stem).lower()] = p
    return stems


def separate(wav: Path, out: Path, progress=None) -> dict:
    """Голос и музыка BS-RoFormer."""
    tmp = out / ".split"
    stems = run_model(BEST_MODEL, wav, tmp, progress)
    result = {}
    for name, key in (("vocals", "vocals"), ("instrumental", "music")):
        result[key] = stems[name].rename(out / f"{default_file(key)}.wav")
    shutil.rmtree(tmp, ignore_errors=True)
    return result


def split(folder: Path, parent: str, progress=None) -> list:
    """Дорожку parent — на части по SPLITS. Тихие части уходят в fold, остаток,
    который модель не разнесла, — в rest: части вместе дают ровно целое. У музыки
    неназванное модель «other» тут же делится по тембру на «Инструмент 1, 2…».
    → (ключи, имена, файлы) найденных по ходу; меньше двух частей — ([], {}, {})."""
    spec = SPLITS[parent]
    src = track(folder, parent)
    tmp = folder / f".split-{parent}"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        stems = run_model(spec["model"], src, tmp, progress)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    whole = read_wav(src).astype(np.int32)
    rms = lambda a: float(np.sqrt(np.mean(a.astype(np.float32) ** 2))) or 1e-9
    base = rms(whole)
    parts = {}
    for name, path in stems.items():
        key = spec["stems"].get(name)
        if key is None:
            continue
        a = read_wav(path).astype(np.int32)[:len(whole)]
        parts[key] = parts[key] + a if key in parts else a
    quiet = lambda k: 20 * np.log10(rms(parts[k]) / base) < QUIET_DB
    fold = spec["fold"]
    for k in list(parts):
        if k != fold and quiet(k):
            parts[fold] = parts.get(fold, 0) + parts.pop(k)
    if fold in parts and quiet(fold) and len(parts) > 1:
        rest = parts.pop(fold)
        loud = max(parts, key=lambda k: rms(parts[k]))
        parts[loud] = parts[loud] + rest
    # Остаток, который модель не разнесла, — в rest: части вместе дают ровно целое.
    rest = spec.get("rest")
    if rest in parts:
        parts[rest] = parts[rest] + (whole - sum(parts.values()))
    keys = [k for k in spec["order"] if k in parts]
    names, files = {}, {}
    if len(keys) < 2:
        shutil.rmtree(tmp, ignore_errors=True)
        return [], names, files
    for k in keys:
        parts[k] = np.clip(parts[k], -32768, 32767).astype(np.int16)
    # Всё, что модель не назвала, — сразу по тембру: «Инструмент 1, 2…»
    # вместо одного «Остального».
    if parent == "music" and "other" in parts:
        if progress:
            progress("timbre", None)
        groups = timbre_groups(parts["other"])
        if len(groups) >= 2:
            at = keys.index("other")
            keys[at:at + 1] = [f"inst{i}" for i in range(1, len(groups) + 1)]
            for i, g in enumerate(groups, 1):
                parts[f"inst{i}"] = g
                names[f"inst{i}"] = f"Инструмент {i}"
                files[f"inst{i}"] = f"{i18n.t('Инструмент')} {i}"
            del parts["other"]
    for k in keys:
        files[k] = files.get(k) or default_file(k)
        write_wav(folder / f"{files[k]}.wav", parts[k])
    shutil.rmtree(tmp, ignore_errors=True)
    return keys, names, files


def stem_file(info: dict, key: str, folder: Path = None) -> str:
    """Имя файла дорожки: у постоянных — из FILES, у найденных по ходу
    (исполнители, инструменты) — записано в описании песни."""
    name = info.get("files", {}).get(key)
    if name and (folder is None or (folder / f"{name}.wav").exists()):
        return name
    if folder is not None:
        for other in (FILES.get(key), FILES_EN.get(key), LEGACY.get(key)):
            if other and (folder / f"{other}.wav").exists():
                return other
    return name or default_file(key)


def timbre_groups(data: np.ndarray, most=5, count=0) -> list:
    """Дорожку — на звуки разного тембра: спектрограмма раскладывается на 24
    составляющие (NMF), составляющие группируются по огибающей спектра (тембр
    без высоты нот), число групп — по силуэту. Каждая группа — мягкая маска,
    вместе они дают ровно исходную дорожку. На «Остальном» тестовой песни
    группы совпали с тем, что SAM Audio выделяет по словам «электрогитара» и
    «синтезатор» (похожесть спектров 0,93 и 0,90), за 15 с на песню.
    count — заданное число групп вместо подбора по силуэту.
    → дорожки int16 от громкой к тихой; один тембр — [data]."""
    import librosa
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.decomposition import NMF
    from sklearn.metrics import silhouette_score
    x = data.astype(np.float32) / 32768.0
    X = [librosa.stft(np.ascontiguousarray(x[:, c]), n_fft=4096, hop_length=1024) for c in range(2)]
    V = np.abs(X[0]) + np.abs(X[1])
    nmf = NMF(n_components=24, beta_loss="kullback-leibler", solver="mu", max_iter=150,
              init="nndsvda", random_state=0)
    W = nmf.fit_transform(V)
    H = nmf.components_
    env = np.log(librosa.filters.mel(sr=SR, n_fft=4096, n_mels=64) @ W + 1e-6)
    feat = librosa.feature.mfcc(S=env, n_mfcc=14)[1:].T
    feat = (feat - feat.mean(0)) / (feat.std(0) + 1e-9)
    if count >= 2:
        lab = AgglomerativeClustering(n_clusters=min(count, len(feat)), linkage="ward").fit_predict(feat)
    else:
        best = (0.12, None)          # ниже — тембр один, делить нечего
        for k in range(2, most + 1):
            lab = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(feat)
            score = silhouette_score(feat, lab)
            if score > best[0]:
                best = (score, lab)
        lab = best[1]
    if lab is None:
        return [data]
    total = W @ H + 1e-9
    out = []
    for g in set(lab.tolist()):
        mask = (W[:, lab == g] @ H[lab == g]) / total
        y = np.stack([librosa.istft(X[c] * mask, hop_length=1024, length=len(x)) for c in range(2)], 1)
        out.append(np.clip(y * 32768.0, -32768, 32767).astype(np.int16))
    return sorted(out, key=lambda a: -float(np.mean(a.astype(np.float32) ** 2)))


def split_timbre(folder: Path, parent: str, info: dict, progress=None, count=0) -> tuple:
    """Дорожку — на «Инструмент 1, 2…» по тембру; count — заданное число.
    Один тембр — ([], {}, {})."""
    stem = stem_file(info, parent, folder)
    groups = timbre_groups(read_wav(folder / f"{stem}.wav"), count=count)
    if len(groups) < 2:
        return [], {}, {}
    drop_parts(folder, stem, "timbre")
    keys, names, files = [], {}, {}
    word = part_word("timbre")
    for i, g in enumerate(groups, 1):
        key = f"{parent}_i{i}"
        write_wav(folder / f"{stem} — {word} {i}.wav", g)
        keys.append(key)
        names[key] = f"Инструмент {i}"
        files[key] = f"{stem} — {word} {i}"
    return keys, names, files


def artists_in_title(title: str) -> int:
    """Сколько исполнителей перечислено в названии: «Слава КПСС, Skurt, mzlff - …» — 3,
    «… (feat. X)» — плюс один. Группа под одним именем — 1: тут название не поможет."""
    head, _, tail = (title or "").partition(" - ")
    feat = re.findall(r"\b(?:feat|ft|при уч)\.?\s+([^()\[\]]+)", tail, re.I)
    sep = r"\s*(?:,|&|\+|\bfeat\.?|\bft\.?|\bvs\.?)\s*|\s+[x×]\s+"
    names = re.split(sep, head, flags=re.I)
    for f in feat:
        names += re.split(sep, f, flags=re.I)
    return len([n for n in names if n.strip()])


def split_singers(folder: Path, parent: str, info: dict, progress=None, count=0) -> tuple:
    """Голос — по исполнителям: кто когда поёт, решает singers.py в окружении
    смены голоса (там CAM++ и TitaNet); дорожка делится по времени мягкими
    масками, вместе они дают ровно исходную. Число исполнителей: заданное, иначе
    из названия трека, иначе — само. Один исполнитель — ([], {}, {}).
    Разметка «кто когда» сохраняется отрезками: по ней дорожки правятся вручную."""
    py, script = voice_python(), voice_script("singers.py")
    if not py or not script:
        raise RuntimeError(i18n.t("нет окружения смены голоса"))
    stem = stem_file(info, parent, folder)
    src = folder / f"{stem}.wav"
    out = folder / ".singers.json"
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONDONTWRITEBYTECODE")}
    cache = Path.home() / "Library" / "Caches" / "Severance"
    env.update(PYTHONPYCACHEPREFIX=str(cache / "bytecode"), NUMBA_CACHE_DIR=str(cache / "numba"),
               PYTORCH_ENABLE_MPS_FALLBACK="1")
    count = count or (n if (n := artists_in_title(info.get("title", ""))) >= 2 else 0)
    cmd = [str(py), str(script), str(src), str(out)] + (["--k", str(count)] if count else [])
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(voice_home()))
    if r.returncode != 0 or not out.exists():
        lines = [x for x in r.stderr.splitlines() if x.strip()]
        raise RuntimeError(lines[-1] if lines else i18n.t("не вышло"))
    found = json.loads(out.read_text())
    out.unlink(missing_ok=True)
    if found["k"] < 2:
        return [], {}, {}
    centers = np.asarray(found["centers"], dtype=float)
    labels = np.asarray(found["labels"])
    # Одиночное окно между двумя одинаковыми — ошибка, а не смена исполнителя.
    for i in range(1, len(labels) - 1):
        if labels[i - 1] == labels[i + 1] != labels[i]:
            labels[i] = labels[i - 1]
    order = sorted(set(labels.tolist()), key=lambda l: -(labels == l).sum())
    rank = {l: i for i, l in enumerate(order)}
    data = read_wav(src).astype(np.float32).mean(axis=1)
    step = SR // 100
    level = np.sqrt((data[:len(data) // step * step].reshape(-1, step) ** 2).mean(axis=1))
    # Метка на каждую сотую секунды, тишина тоже чья-то: маски покрывают всё время
    # и в сумме дают единицу. Смена исполнителя — в самом тихом месте между
    # соседними окнами разных групп (вдох, пауза), а не ровно посередине.
    frame = np.zeros(len(level), dtype=int)
    start = 0
    for i in range(1, len(labels) + 1):
        if i < len(labels) and labels[i] == labels[i - 1]:
            continue
        if i < len(labels):
            lo, hi = int(centers[i - 1] * 100), int(centers[i] * 100)
            cut = lo + int(np.argmin(level[lo:hi])) if hi > lo else hi
        else:
            cut = len(level)
        frame[start:cut] = rank[labels[i - 1]]
        start = cut
    runs = frames_to_runs(frame)
    keys = [f"{parent}_s{i}" for i in range(1, len(order) + 1)]
    names = {k: f"Исполнитель {i}" for i, k in enumerate(keys, 1)}
    word = part_word("singer")
    files = {k: f"{stem} — {word} {i}" for i, k in enumerate(keys, 1)}
    drop_parts(folder, stem, "singer")
    render_singers(folder, src, runs, [files[k] for k in keys])
    info.setdefault("singer_runs", {})[parent] = runs
    return keys, names, files


def sf_frames(path) -> int:
    import soundfile as sf
    return sf.info(str(path)).frames


def frames_to_runs(frame) -> list:
    """Метки по сотым секунды → отрезки [начало, конец, исполнитель] в секундах."""
    runs, s = [], 0
    for i in range(1, len(frame) + 1):
        if i == len(frame) or frame[i] != frame[s]:
            runs.append([round(s * 0.01, 2), round(i * 0.01, 2), int(frame[s])])
            s = i
    return runs


def render_singers(folder: Path, src: Path, runs: list, files: list):
    """Дорожки исполнителей из общей по отрезкам: мягкие края по 40 мс, в сумме — исходная."""
    data = read_wav(src).astype(np.float32)
    n = len(data)
    grid = np.arange(0, n / SR, 0.01)
    frame = np.zeros(len(grid), dtype=int)
    for a, b, who in runs:
        frame[int(round(a * 100)):int(round(b * 100))] = who
    fade = np.hanning(9)
    fade /= fade.sum()
    masks = [np.convolve((frame == i).astype(np.float32), fade, mode="same") for i in range(len(files))]
    total = np.maximum(sum(masks), 1e-6)
    t = np.arange(n) / SR
    for m, name in zip(masks, files):
        gain = np.interp(t, grid, m / total).astype(np.float32)
        write_wav(folder / f"{name}.wav", np.clip(data * gain[:, None], -32768, 32767).astype(np.int16))


def runs_from_files(folder: Path, files: list) -> list:
    """Разметка для старых раскладок без неё: на каждую сотую — кто громче."""
    level = []
    for name in files:
        d = read_wav(folder / f"{name}.wav").astype(np.float32).mean(axis=1)
        step = SR // 100
        d = d[:len(d) // step * step].reshape(-1, step)
        level.append((d ** 2).mean(axis=1))
    size = min(len(x) for x in level)
    return frames_to_runs(np.argmax(np.stack([x[:size] for x in level]), axis=0))


def move_audio(folder: Path, sources: list, target: str, a: float, b: float) -> dict:
    """Кусок [a, b) из частей sources — в часть target; края по 10 мс: сумма частей
    не меняется. → прежние куски {имя файла: (первый кадр, int16)} для отмены."""
    parts = {n: read_wav(folder / f"{n}.wav") for n in dict.fromkeys(list(sources) + [target])}
    ia = max(int(a * SR), 0)
    ib = min(int(b * SR), min(len(x) for x in parts.values()))
    if ib - ia < 2:
        return {}
    w = np.ones(ib - ia, np.float32)
    edge = min(int(0.01 * SR), (ib - ia) // 2)
    if edge:
        w[:edge] = np.linspace(0, 1, edge)
        w[-edge:] = np.linspace(1, 0, edge)
    saved = {n: (ia, x[ia:ib].copy()) for n, x in parts.items()}
    into = parts[target][ia:ib].astype(np.float32)
    for n in sources:
        if n == target:
            continue
        seg = parts[n][ia:ib].astype(np.float32) * w[:, None]
        into += seg
        parts[n][ia:ib] = np.clip(np.round(parts[n][ia:ib] - seg), -32768, 32767).astype(np.int16)
    parts[target][ia:ib] = np.clip(np.round(into), -32768, 32767).astype(np.int16)
    for n, x in parts.items():
        write_wav(folder / f"{n}.wav", x)
    return saved


def restore_audio(folder: Path, saved: dict):
    for n, (ia, seg) in saved.items():
        path = folder / f"{n}.wav"
        if path.exists():
            x = read_wav(path)
            x[ia:ia + len(seg)] = seg
            write_wav(path, x)


def move_singer(runs: list, a: float, b: float, who: int) -> list:
    """Отрезок [a, b) — исполнителю who; соседние отрезки обрезаются."""
    out = []
    for s, e, w in runs:
        if e <= a or s >= b:
            out.append([s, e, w])
            continue
        if s < a:
            out.append([s, round(a, 2), w])
        if e > b:
            out.append([round(b, 2), e, w])
    out.append([round(a, 2), round(b, 2), int(who)])
    out.sort()
    merged = []
    for s, e, w in out:
        if merged and merged[-1][2] == w and abs(merged[-1][1] - s) < 1e-6:
            merged[-1][1] = e
        elif e > s:
            merged.append([s, e, w])
    return merged


def chords(wav: Path) -> list:
    """Аккорды по времени: [{"start", "end", "chord"}], метки вида «F#:min7», «N» — нет аккорда."""
    from lv_chordia.session import LVChordiaSession
    session = LVChordiaSession(chord_dict_name="submission").load()
    try:
        found = session.infer(str(wav))
    finally:
        session.close()
    return [{"start": round(float(r["start_time"]), 3), "end": round(float(r["end_time"]), 3),
             "chord": r["chord"]} for r in found]


def separate_fast(wav: Path, out: Path) -> dict:
    """Четыре дорожки demucs-mlx — для образца голоса."""
    from demucs_mlx.api import Separator
    _mlx_ready()
    with GPU, Separator(model=FAST_MODEL) as sep:
        paths = sep.separate(str(wav), output_dir=str(out), filename_format="{stem}.wav")
    return {k: Path(v) for k, v in paths.items()}


def tempo(wav: Path) -> dict:
    """BPM по наклону прямой через все удары: медиана интервалов дрожит и даёт
    115,4 там, где 116; наклон — 116,04. Плюс доли такта и сами удары."""
    import torch
    from beat_this.inference import Audio2Beats
    raw = subprocess.run([tool("ffmpeg"), "-v", "error", "-i", str(wav), "-ac", "1", "-ar", "22050",
                          "-f", "f32le", "-"], capture_output=True).stdout
    sig = np.frombuffer(raw, np.float32)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    beats, downbeats = Audio2Beats(checkpoint_path="final0", device=device, dbn=False)(sig, 22050)
    beats = np.asarray(beats, dtype=float)
    downbeats = np.asarray(downbeats, dtype=float)
    info = {"bpm": 0.0, "meter": 0, "beats": beats.tolist(), "downbeats": downbeats.tolist()}
    if len(beats) >= 8:
        slope = np.polyfit(np.arange(len(beats)), beats, 1)[0]
        info["bpm"] = round(60.0 / slope, 1)
        if len(downbeats) >= 3:
            info["meter"] = int(round(np.median(np.diff(downbeats)) / np.median(np.diff(beats))))
    return info


def download(url: str, folder: Path, progress=None, stop=None) -> tuple:
    """Звук по ссылке: лучшая дорожка без видео. Возвращает (файл, название).
    Музыка ВКонтакте — своим путём (links), остальное — yt-dlp с cookies
    браузера, если они читаются: закрытые сайты отдают запись только вошедшим."""
    import links
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadCancelled, DownloadError

    if links.is_vk_audio(url):
        return links.vk_download(url, folder, progress, stop)

    def hook(d):
        if stop and stop():
            raise DownloadCancelled()
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        if total and progress:
            progress(d.get("downloaded_bytes", 0) / total)

    folder.mkdir(parents=True, exist_ok=True)
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "format": "ba/b",
            "outtmpl": str(folder / "%(id)s.%(ext)s"), "progress_hooks": [hook], "noplaylist": True}
    readable = links.cookie_browsers()
    if readable:
        opts["cookiesfrombrowser"] = (readable[0],)
    try:
        with YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
            path = (info.get("requested_downloads") or [{}])[0].get("filepath") or y.prepare_filename(info)
    except DownloadError as e:
        text = links.human_error(str(e))
        if text and "после входа" in text and not readable and links.installed_browsers():
            raise links.NeedsAccess(i18n.t("Нужен полный доступ к диску.")) from e
        raise links.SourceError(text or i18n.t("Не скачалось: ") + str(e).replace("ERROR: ", "")[:200]) from e
    return Path(path), info.get("title") or Path(path).stem


def free_memory():
    """Модели отпускаются после разделения: MLX и MPS держат память до конца процесса."""
    gc.collect()
    try:
        import mlx.core as mx
        with GPU:
            mx.clear_cache()
    except Exception:
        pass
    try:
        import torch
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


_info_lock = threading.Lock()


def save_info(folder: Path, data: dict):
    # Через временный файл: окно читает описание, пока работа его дописывает.
    tmp = folder / (INFO + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(folder / INFO)


def update_info(folder: Path, change) -> dict:
    """Прочитать, поменять и записать описание под замком: громкость из окна
    и итог раскладки из рабочего потока пишутся в один файл."""
    with _info_lock:
        info = load_info(folder)
        change(info)
        save_info(folder, info)
        return info


def load_info(folder: Path) -> dict:
    try:
        return json.loads((folder / INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def voice_python():
    """Python окружения смены голоса: в бандле — свой, в разработке — voice/.venv."""
    for p in (HERE.parent / "voice" / "python" / "bin" / "python3",
              HERE / "voice" / ".venv" / "bin" / "python",
              HERE / "voice" / ".venv" / "Scripts" / "python.exe"):
        if p.exists():
            return p
    return None


def voice_script(name="convert.py"):
    for p in (HERE.parent / "voice" / name, HERE / "voice" / name):
        if p.exists():
            return p
    return None


def reference_voice(src, work: Path, seconds: int = 10) -> Path:
    """Образец голоса из чего угодно: песни, записи, видео. Музыку убирает demucs,
    из голоса берутся самые громкие seconds секунд. Seed-VC держит в окне 30 с
    вместе с образцом: образец 10 с оставляет песне 20 с за раз, 25 с — только 5.
    Сходство с голосом по CAM++ на 30 с песни: образец 25 с и 10 шагов — 0,50
    за 28 с; образец 10 с и 30 шагов — 0,54 за 21 с."""
    work.mkdir(parents=True, exist_ok=True)
    wav = decode(src, work / "reference_mix.wav")
    stems = separate_fast(wav, work)
    voice = read_wav(stems["vocals"]).astype(np.float32).mean(axis=1)
    win = seconds * SR
    if len(voice) > win:
        energy = np.convolve(voice ** 2, np.ones(SR, dtype=np.float32), mode="valid")[::SR]
        sums = np.convolve(energy, np.ones(seconds, dtype=np.float32), mode="valid")
        start = int(np.argmax(sums)) * SR
        voice = voice[start:start + win]
    out = work / "reference.wav"
    import soundfile as sf
    sf.write(str(out), voice / 32768.0, SR)
    return out


def change_voice(vocals: Path, reference: Path, out: Path, steps: int, shift: int, progress=None, stop=None):
    """Seed-VC отдельным процессом. Ход — по кускам, которые он печатает.

    Seed-VC при каждом запуске сверяет веса с Hugging Face, а без ответа оттуда
    ждёт бесконечно. Когда всё уже скачано, сеть ему закрыта; если веса
    пропали — второй заход с сетью докачает их."""
    py, script = voice_python(), voice_script()
    if not py or not script:
        raise RuntimeError(i18n.t("смена голоса не установлена"))
    home = voice_home()
    home.mkdir(parents=True, exist_ok=True)
    ready = home / "ready"
    # stderr — в файл: Seed-VC сыплет туда предупреждениями и полосками загрузки,
    # и непрочитанная труба на 64 КБ остановила бы процесс навсегда.
    log = out.with_suffix(".log")
    for offline in ([True, False] if ready.exists() else [False]):
        # Пути основного Python второму не нужны: у него свои библиотеки.
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONDONTWRITEBYTECODE")}
        env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        # Байт-код и кэш Numba (librosa) — в кэш пользователя: подписанный бандл
        # менять нельзя, иначе macOS проверяет его заново при каждом запуске.
        cache = Path.home() / "Library" / "Caches" / "Severance"
        env["PYTHONPYCACHEPREFIX"] = str(cache / "bytecode")
        env["NUMBA_CACHE_DIR"] = str(cache / "numba")
        if offline:
            env["HF_HUB_OFFLINE"] = "1"
        with open(log, "w") as err:
            proc = subprocess.Popen([str(py), str(script), str(vocals), str(reference), str(out),
                                     "--steps", str(steps), "--shift", str(shift)],
                                    stdout=subprocess.PIPE, stderr=err, text=True, env=env,
                                    cwd=str(home))
            for line in proc.stdout:
                if stop and stop():
                    proc.kill()
                    raise RuntimeError(i18n.t("отменено"))
                line = line.strip()
                if progress and line == "models":
                    progress("models", None)
                elif progress and line.startswith("chunk "):
                    n, total = map(int, line.split()[1].split("/"))
                    progress("chunk", n / total)
            proc.wait()
        if proc.returncode == 0 and out.exists():
            ready.touch()
            log.unlink(missing_ok=True)
            return
    lines = [x for x in log.read_text(errors="replace").splitlines() if x.strip()]
    raise RuntimeError(lines[-1] if lines else i18n.t("ошибка"))


def make_cover(voice: Path, original_vocals: Path, instrumental: Path, out: Path) -> Path:
    """Новый голос поверх музыки. Громкость голоса — как у исходного вокала."""
    import soundfile as sf
    new, sr = sf.read(str(voice), dtype="float32", always_2d=True)
    old = read_wav(original_vocals).astype(np.float32) / 32768.0
    inst = read_wav(instrumental).astype(np.float32) / 32768.0
    new = np.repeat(new[:, :1], 2, axis=1) if new.shape[1] == 1 else new[:, :2]
    rms = lambda a: float(np.sqrt(np.mean(a ** 2))) or 1e-9
    new *= rms(old) / rms(new)
    n = min(len(new), len(inst))
    mix = inst[:n] + new[:n]
    peak = float(np.abs(mix).max()) or 1.0
    if peak > 0.99:
        mix *= 0.99 / peak
        new *= 0.99 / peak
    write_wav(voice, (np.clip(new, -1, 1) * 32767).astype(np.int16))
    write_wav(out, (np.clip(mix, -1, 1) * 32767).astype(np.int16))
    return out


# Запись под оригинал

ALIGN_SR = 16000
ALIGN_HOP = 640          # 40 мс: на песню в три минуты матрица сравнения ~4500², ~0,3 ГБ
WORLD_MS = 5.0


def _world():
    """Вокодер WORLD. Его __init__ лезет в pkg_resources только за номером
    версии, а в свежем setuptools того больше нет — подставляем заглушку."""
    import types
    if "pkg_resources" not in sys.modules:
        stub = types.ModuleType("pkg_resources")
        stub.get_distribution = lambda name: types.SimpleNamespace(version="0")
        sys.modules["pkg_resources"] = stub
    import pyworld
    return pyworld


def _mono(path) -> np.ndarray:
    return read_wav(path).astype(np.float64).mean(axis=1) / 32768.0


def _align_features(y: np.ndarray) -> np.ndarray:
    """Тембр по кадрам (MFCC без громкости) и отметка тишины: тишина должна
    ложиться на тишину, а не на случайный шум, который MFCC в ней видит."""
    import librosa
    y = y.astype(np.float32)
    mfcc = librosa.feature.mfcc(y=y, sr=ALIGN_SR, n_mfcc=21, n_fft=2048, hop_length=ALIGN_HOP)[1:]
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=ALIGN_HOP)[0]
    quiet = rms < max(float(np.percentile(rms, 95)) * 0.05, 1e-4)
    mfcc = (mfcc - mfcc.mean(axis=1, keepdims=True)) / (mfcc.std(axis=1, keepdims=True) + 1e-6)
    mfcc[:, quiet] = 0.0
    return np.vstack([mfcc, quiet[None, :] * 4.0])


def time_map(guide: np.ndarray, take: np.ndarray) -> tuple:
    """Где в записи звучит то, что в оригинале звучит в момент t: (t оригинала, t записи)."""
    import librosa
    from scipy.ndimage import median_filter
    from scipy.signal import resample_poly
    g = _align_features(resample_poly(guide, 160, 441))
    k = _align_features(resample_poly(take, 160, 441))
    _, path = librosa.sequence.dtw(X=g, Y=k, metric="euclidean", global_constraints=True, band_rad=0.25)
    path = path[::-1]
    hop = ALIGN_HOP / ALIGN_SR
    src = np.zeros(g.shape[1])
    for i in range(g.shape[1]):
        src[i] = path[path[:, 0] == i, 1].mean()
    # Путь DTW идёт ступеньками; сглаживаем и не даём времени идти назад.
    src = np.maximum.accumulate(median_filter(src, size=5, mode="nearest"))
    return np.arange(g.shape[1]) * hop, src * hop


def fit_voice(take_src, guide: Path, out: Path, work: Path, progress=None, stop=None) -> Path:
    """Чужая запись под исполнение оригинала: время и мелодия — от guide,
    тембр, слова и дыхание — от записи. Октава мелодии — та, что ближе к
    голосу записи: мужской голос не тянется в женский регистр."""
    from scipy.interpolate import interp1d

    def step(kind, share=None):
        if stop and stop():
            raise Stopped
        if progress:
            progress(kind, share)

    work.mkdir(parents=True, exist_ok=True)
    step("voice")
    wav = decode(take_src, work / "take_mix.wav")
    take = _mono(separate_fast(wav, work)["vocals"])
    free_memory()
    lead = _mono(guide)
    step("align")
    g_times, k_times = time_map(lead, take)
    pw = _world()
    step("analyse", 0.0)
    f0_g, t_g = pw.dio(lead, SR, frame_period=WORLD_MS)
    f0_g = pw.stonemask(lead, f0_g, t_g, SR)
    step("analyse", 0.3)
    f0_k, t_k = pw.dio(take, SR, frame_period=WORLD_MS)
    f0_k = pw.stonemask(take, f0_k, t_k, SR)
    sp = pw.cheaptrick(take, f0_k, t_k, SR)
    step("analyse", 0.6)
    ap = pw.d4c(take, f0_k, t_k, SR)
    step("render")
    where = interp1d(g_times, k_times, bounds_error=False, fill_value=(k_times[0], k_times[-1]))(t_g)
    idx = np.clip(where * 1000 / WORLD_MS, 0, len(f0_k) - 1)
    lo = np.floor(idx).astype(int)
    hi = np.minimum(lo + 1, len(f0_k) - 1)
    w = (idx - lo)[:, None]
    sp_out = np.exp(np.log(sp[lo] + 1e-12) * (1 - w) + np.log(sp[hi] + 1e-12) * w)
    ap_out = ap[lo] * (1 - w) + ap[hi] * w
    take_f0 = f0_k[np.rint(idx).astype(int)]
    sung, own = f0_g > 0, take_f0 > 0
    octave = 0
    if sung.any() and (f0_k > 0).any():
        octave = int(np.round(np.log2(np.median(f0_k[f0_k > 0]) / np.median(f0_g[sung]))))
    # Звучит у обоих — мелодия оригинала; оригинал молчит, а в записи голос —
    # свой тон записи: иначе тянутые ноты превращались в шёпот.
    f0_out = np.where(sung & own, f0_g * 2.0 ** octave, np.where(own, take_f0, 0.0))
    y = pw.synthesize(np.ascontiguousarray(f0_out), np.ascontiguousarray(sp_out),
                      np.ascontiguousarray(ap_out), SR, frame_period=WORLD_MS)
    y = np.pad(y, (0, max(0, len(lead) - len(y))))[:len(lead)]
    peak = float(np.abs(y).max()) or 1.0
    y = y / peak * 0.9
    write_wav(out, (np.repeat(y[:, None], 2, axis=1) * 32767).astype(np.int16))
    return out


# Левый и правый каналы

CHANNEL_WORDS = {"ru": ("левый", "правый"), "en": ("left", "right")}


def split_channels(folder: Path, parent: str, info: dict) -> tuple:
    """Дорожку — на левый и правый каналы: каждый звучит со своей стороны,
    вместе дают целую. Одинаковые каналы (моно) — ([], {}, {})."""
    stem = stem_file(info, parent, folder)
    data = read_wav(folder / f"{stem}.wav")
    left, right = data[:, 0].astype(np.float32), data[:, 1].astype(np.float32)
    if np.sqrt(np.mean((left - right) ** 2)) < 0.01 * (np.sqrt(np.mean((left + right) ** 2)) + 1e-9):
        return [], {}, {}
    words = CHANNEL_WORDS[i18n.current()]
    keys, names, files = [], {}, {}
    for i, (side, name) in enumerate(zip(words, ("Левый канал", "Правый канал")), 1):
        part = np.zeros_like(data)
        part[:, i - 1] = data[:, i - 1]
        key = f"{parent}_ch{i}"
        files[key] = f"{stem} — {side}"
        names[key] = name
        write_wav(folder / f"{files[key]}.wav", part)
        keys.append(key)
    return keys, names, files


# Текст песни

WHISPER = "mlx-community/whisper-large-v3-mlx"
LRCLIB = "https://lrclib.net/api/search"


def _norm(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower().replace("ё", "е"))


def _clean_title(title: str) -> str:
    title = re.sub(r"\((?:[^)]*\.(?:net|com|ru|org)|full|official[^)]*|lyrics?)\)", "", title, flags=re.I)
    return re.sub(r"[_\s]+", " ", title).strip(" -")


def lrclib(title: str, duration: float) -> list:
    """Строки с временем из LRCLIB: [(начало, текст)]. Не нашлось — []."""
    import urllib.error
    import urllib.parse
    import urllib.request
    req = urllib.request.Request(f"{LRCLIB}?{urllib.parse.urlencode({'q': _clean_title(title)})}",
                                 headers={"User-Agent": "Severance (https://github.com/Drtonix/Severance)"})
    found = None
    # LRCLIB часто отвечает 429 на первый запрос и пускает со второго-третьего.
    for wait in (1.5, 3, 6, None):
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                found = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or wait is None:
                return []
            time.sleep(wait)
        except (OSError, ValueError):
            return []
    if not found:
        return []
    found = [x for x in found if x.get("syncedLyrics") and abs((x.get("duration") or 0) - duration) < 4]
    if not found:
        return []
    best = min(found, key=lambda x: abs(x["duration"] - duration))
    lines = []
    for raw in best["syncedLyrics"].splitlines():
        m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)", raw)
        if m and m.group(3).strip():
            lines.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3).strip()))
    return lines


def _whisper_words(wav: Path, progress=None) -> list:
    """Слова с временем по голосу: [(начало, конец, слово)]."""
    import mlx_whisper
    import models_home
    from scipy.signal import resample_poly
    path = models_home.resolve(WHISPER)
    if path is None:
        from huggingface_hub import snapshot_download
        if progress:
            progress("download", None)
        path = snapshot_download(WHISPER)
    data = read_wav(wav).astype(np.float32).mean(axis=1) / 32768
    audio = resample_poly(data, 160, 441).astype(np.float32)
    if progress:
        progress("words", None)

    class Steps:
        # Вместо полосы tqdm: доля пройденного и место, где работу можно прервать.
        def __init__(self, total=0, **_):
            self.total, self.done = max(total, 1), 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def update(self, n):
            self.done += n
            if progress:
                progress("words", min(self.done / self.total, 1.0))

    module = sys.modules["mlx_whisper.transcribe"]
    saved = module.tqdm
    module.tqdm = type("tqdm", (), {"tqdm": Steps})
    try:
        with GPU:
            _mlx_ready()
            r = mlx_whisper.transcribe(audio, path_or_hf_repo=str(path), word_timestamps=True,
                                       condition_on_previous_text=False, hallucination_silence_threshold=2.0)
    finally:
        module.tqdm = saved
        # mlx-whisper держит модель до конца процесса — это 3 ГБ памяти видеокарты,
        # занятые и тогда, когда текст давно найден.
        module.ModelHolder.model = module.ModelHolder.model_path = None
    words = []
    for seg in r.get("segments", []):
        # Музыка без слов даёт «спасибо за просмотр» и повторы: такие куски пропускаем.
        if seg.get("no_speech_prob", 0) > 0.6 or seg.get("compression_ratio", 0) > 2.4:
            continue
        for w in seg.get("words", []):
            text = w["word"].strip()
            if text:
                words.append((float(w["start"]), float(w["end"]), text))
    return words


def _lines_from_words(words: list) -> list:
    """Строки из слов Whisper: по паузам, не длиннее десяти слов."""
    lines, cur = [], []
    for w in words:
        if cur and (w[0] - cur[-1][1] > 0.6 or len(cur) >= 10 or cur[-1][2][-1:] in ".!?"):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return [{"start": ln[0][0], "end": ln[-1][1], "words": [list(w) for w in ln]} for ln in lines]


def _match(a: list, b: list) -> list:
    """Пары (i, j) похожих слов по порядку: распознанное слово часто отличается
    от текста буквой или знаком, точное сравнение теряет две трети пар."""
    import difflib
    n, m = len(a), len(b)
    sim = np.zeros((n, m), np.float32)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            if x and y and abs(len(x) - len(y)) <= max(len(x), len(y)) // 2 + 1:
                r = difflib.SequenceMatcher(None, x, y).ratio()
                if r >= 0.6:
                    sim[i, j] = r
    best = np.zeros((n + 1, m + 1), np.float32)
    for i in range(1, n + 1):
        row, prev = best[i], best[i - 1]
        for j in range(1, m + 1):
            take = prev[j - 1] + sim[i - 1, j - 1] if sim[i - 1, j - 1] else 0
            row[j] = max(prev[j], row[j - 1], take)
    pairs, i, j = [], n, m
    while i and j:
        if sim[i - 1, j - 1] and best[i, j] == best[i - 1, j - 1] + sim[i - 1, j - 1]:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif best[i - 1, j] >= best[i, j - 1]:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def _align(lines: list, words: list, duration: float, starts=None) -> list:
    """Текст LRCLIB с временем слов Whisper: совпавшие слова берут его время,
    остальные делят промежуток между соседями поровну."""
    tokens = [(i, tok) for i, (_, text) in enumerate(lines) for tok in text.split()]
    times = [None] * len(tokens)
    for i, j in _match([_norm(tok) for _, tok in tokens], [_norm(w[2]) for w in words]):
        times[i] = words[j][:2]
    out = []
    for i, (start, _) in enumerate(lines):
        end = lines[i + 1][0] if i + 1 < len(lines) else min(start + 8, duration)
        idx = [j for j, (li, _) in enumerate(tokens) if li == i]
        hits = {j: times[j] for j in idx if times[j] and start - 1 <= times[j][0] <= end + 1}
        ws = [None] * len(idx)
        n = 0
        while n < len(idx):
            if idx[n] in hits:
                ws[n] = [*hits[idx[n]], tokens[idx[n]][1]]
                n += 1
                continue
            m = n
            while m < len(idx) and idx[m] not in hits:
                m += 1
            lo = ws[n - 1][1] if n else start
            if m < len(idx):
                hi = max(hits[idx[m]][0], lo)
                step = (hi - lo) / (m - n)
                for k in range(n, m):
                    ws[k] = [lo + (k - n) * step, lo + (k - n + 1) * step, tokens[idx[k]][1]]
            else:
                # Хвост строки без опоры: слова своей длины, а не растянутые
                # до следующей строки через паузу.
                for k in range(n, m):
                    size = min(max(len(tokens[idx[k]][1]) * 0.075, 0.18), 0.6)
                    ws[k] = [lo, min(lo + size, end), tokens[idx[k]][1]]
                    lo = ws[k][1]
            n = m
        out.append({"start": start, "end": end, "words": ws})
    return _settle(out, starts)


def onsets(wav: Path) -> np.ndarray:
    """Начала звуков в отделённом голосе — по ним выверяется начало слов."""
    import librosa
    data = read_wav(wav).astype(np.float32).mean(axis=1) / 32768
    return librosa.onset.onset_detect(y=data, sr=SR, units="time", backtrack=True)


def _settle(lines: list, starts=None) -> list:
    """Начало слова — к ближайшему началу звука не дальше 0,2 с; конец — не
    позже следующего слова. Строка становится текущей чуть раньше первого
    слова: метка строки в LRCLIB бывает позже, чем начинают петь."""
    for ln in lines:
        prev = None
        for w in ln["words"]:
            if starts is not None and len(starts):
                j = int(np.argmin(np.abs(starts - w[0])))
                if abs(starts[j] - w[0]) <= 0.2:
                    w[0] = float(starts[j])
            if prev is not None:
                w[0] = max(w[0], prev[0] + 0.05)
                prev[1] = min(prev[1], w[0]) if prev[1] > w[0] else prev[1]
            w[1] = max(w[1], w[0] + 0.08)
            prev = w
        if ln["words"]:
            ln["start"] = min(ln["start"], ln["words"][0][0] - 0.25)
            ln["end"] = min(ln["end"], ln["words"][-1][1] + 1.5)
    return lines


def lyrics(folder: Path, info: dict, progress=None) -> dict:
    """Текст песни со временем каждого слова. Текст — из LRCLIB, если там есть
    эта песня, слова по времени — Whisper по отделённому голосу."""
    vocals = track(folder, "vocals", info)
    src = vocals if vocals.exists() else track(folder, "original", info)
    duration = float(info.get("duration") or 0)
    found = [tuple(x) for x in info.get("lyrics", {}).get("lrc", [])]
    if not found and duration:
        found = lrclib(info.get("title") or folder.name, duration)
    words = _whisper_words(src, progress)
    if found:
        return {"source": "lrclib", "lrc": found, "lines": _align(found, words, duration, onsets(src))}
    return {"source": "whisper", "lines": _settle(_lines_from_words(words), onsets(src))}


# Спектрограмма

SPEC_ROWS = 640
SPEC_FMIN, SPEC_FMAX = 30.0, 16000.0
SPEC_HOP = 512
SPEC_FFT = 4096
SPEC_RANGE = 80.0


def _band_weights(rows: int) -> np.ndarray:
    """Матрица полос на логарифмической шкале: внизу полоса уже шага БПФ —
    там линейная интерполяция, вверху шире — там среднее по своим частотам."""
    freqs = np.fft.rfftfreq(SPEC_FFT, 1 / SR)
    edges = np.geomspace(SPEC_FMIN, SPEC_FMAX, rows + 1)
    w = np.zeros((rows, len(freqs)), np.float32)
    step = freqs[1]
    for r in range(rows):
        lo, hi = edges[r], edges[r + 1]
        inside = np.nonzero((freqs >= lo) & (freqs < hi))[0]
        if len(inside):
            w[r, inside] = 1.0 / len(inside)
        else:
            c = (lo * hi) ** 0.5 / step
            i = int(c)
            frac = c - i
            w[r, i], w[r, i + 1] = 1 - frac, frac
    return w


def spectrogram(data: np.ndarray, stop=None) -> np.ndarray:
    """Спектрограмма: uint8 [строки, кадры], 0 — тишина, 255 — громче всего
    в дорожке; верхняя строка — высокие частоты."""
    x = data.astype(np.float32).mean(axis=1) / 32768
    if len(x) < SPEC_FFT:
        return np.zeros((SPEC_ROWS, 1), np.uint8)
    window = np.hanning(SPEC_FFT).astype(np.float32)
    weights = _band_weights(SPEC_ROWS)
    frames = 1 + (len(x) - SPEC_FFT) // SPEC_HOP
    out = np.empty((SPEC_ROWS, frames), np.float32)
    view = np.lib.stride_tricks.sliding_window_view(x, SPEC_FFT)[::SPEC_HOP]
    for a in range(0, frames, 1024):
        if stop and stop():
            return None
        block = view[a:a + 1024] * window
        power = np.abs(np.fft.rfft(block, axis=1)) ** 2
        out[:, a:a + len(block)] = weights @ power.T
    db = 10 * np.log10(out + 1e-12)
    top = float(np.percentile(db, 99.9))
    img = np.clip((db - (top - SPEC_RANGE)) / SPEC_RANGE, 0, 1)
    return np.ascontiguousarray((img[::-1] * 255).astype(np.uint8))
