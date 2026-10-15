"""Общее хранилище моделей для всех приложений: где лежат, куда качать, загрузки.

Одна настройка на все приложения (Konspekt, Lectures, Dubl, блокнот, Prognews,
Severance, tonix-gpt): папка по умолчанию, куда ставятся модели, — любая, на
любом диске; без неё — общий кэш Hugging Face (~/.cache/huggingface). При
установке папку можно указать для одной модели. Модель ищется там, куда её
поставили, в папке по умолчанию и в общем кэше.

Загрузки идут одной очередью в отдельном процессе-загрузчике: он не зависит
от окон и докачивает, даже когда приложения закрыты. Ход пишется в файл —
его показывает окно моделей любого приложения.

Свой загрузчик, а не huggingface_hub: тот (1.x) после перезапуска процесса
начинает файл заново. Здесь у недокачанного постоянное имя «.part», продолжение
запросом с середины, в конце — сверка SHA-256. В общий кэш файлы ложатся так
же, как кладёт huggingface_hub (blobs, snapshots, refs), — модели видят и
программы, которые ищут их по-старому.

Файл один и тот же во всех проектах — как _style.py: правится в одном, копируется
в остальные.
"""
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Служебное: настройка, очередь, ход загрузок. MODELS_HOME_DATA — для проверок.
HOME = Path(os.environ.get("MODELS_HOME_DATA")
            or Path.home() / "Library" / "Application Support" / "Модели")
SETTINGS = HOME / "настройка.json"
QUEUE = HOME / "очередь.json"
STATUS = HOME / "ход.json"
LOCK = HOME / "загрузчик.lock"
CHUNK = 1 << 20


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, data):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def folder():
    """Папка по умолчанию или None — общий кэш Hugging Face."""
    f = _read(SETTINGS, {}).get("folder")
    return Path(f) if f else None


def set_folder(path):
    s = _read(SETTINGS, {})
    s["folder"] = str(path) if path else None
    _write(SETTINGS, s)


def _placed(repo):
    p = _read(SETTINGS, {}).get("placed", {}).get(repo)
    return Path(p) if p else None


def _remember(repo, base):
    s = _read(SETTINGS, {})
    placed = s.setdefault("placed", {})
    if base is None:
        placed.pop(repo, None)
    else:
        placed[repo] = str(base)
    _write(SETTINGS, s)


def volume_of(path):
    """Подключаемый диск, на котором лежит путь: /Volumes/Имя или None."""
    parts = Path(path).parts
    return Path(*parts[:3]) if len(parts) >= 3 and parts[1] == "Volumes" else None


def mounted(base):
    v = volume_of(base)
    return v is None or v.exists()


def label(base):
    """Короткая подпись папки: «Диск/Модели» или «~/Модели»; None — общий кэш."""
    path = Path(base) if base is not None else cache_root().parent
    v = volume_of(path)
    if v is not None:
        return str(Path(v.name, path.relative_to(v)))
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def cache_root():
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    return Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"


def cache_dir(repo):
    return cache_root() / ("models--" + repo.replace("/", "--"))


def repo_dir(repo, base):
    return Path(base) / repo.replace("/", "--")


def _complete(path):
    """Все ли веса на месте: от осмотра репозитория остаётся папка с одним
    config.json, у недокачанной — часть файлов."""
    if path is None or not Path(path).exists():
        return False
    path = Path(path)
    index = next(iter(path.glob("*.safetensors.index.json")), None)
    if index is not None:
        files = set(json.loads(index.read_text()).get("weight_map", {}).values())
        return all((path / f).exists() for f in files)
    weights = [p for p in path.rglob("*") if p.suffix in (".safetensors", ".npz", ".bin", ".gguf", ".onnx", ".pt", ".ckpt")
               and not p.name.endswith(".part")]
    return bool(weights) and not any(path.rglob("*.part"))


def _cache_snapshot(repo):
    root = cache_dir(repo)
    ref = root / "refs" / "main"
    if ref.exists():
        snap = root / "snapshots" / ref.read_text().strip()
        if snap.exists():
            return snap
    snaps = sorted((root / "snapshots").glob("*"), key=lambda p: p.stat().st_mtime) if (root / "snapshots").exists() else []
    return snaps[-1] if snaps else None


def resolve(repo):
    """Папка скачанной модели, если она целиком на месте и диск подключён; иначе None."""
    for base in dict.fromkeys(b for b in (_placed(repo), folder()) if b):
        d = repo_dir(repo, base)
        if mounted(base) and _complete(d):
            return d
    snap = _cache_snapshot(repo)
    return snap if _complete(snap) else None


def local_first(repo):
    """Для загрузчиков моделей: путь, если скачана, иначе само имя."""
    p = resolve(repo)
    return str(p) if p else repo


def where(repo):
    """Подпись папки, где модель лежит, а если её нет — куда она установится."""
    p = resolve(repo)
    if p is not None:
        return label(None if shared(repo) else p.parent)
    placed = _placed(repo)
    if placed and not mounted(placed):
        return label(placed)
    return label(target(repo))


def shared(repo):
    """Лежит в общем кэше — им могут пользоваться и другие приложения."""
    p = resolve(repo)
    return p is not None and str(p).startswith(str(cache_dir(repo)))


def _size(path):
    path = Path(path)
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def target(repo):
    """Куда качать: туда, где загрузка уже начата, иначе в выбранную папку;
    None — общий кэш."""
    base = folder()
    if base and mounted(base) and _size(repo_dir(repo, base)) > 50e6:
        return base
    if _size(cache_dir(repo) / "blobs") > 50e6:
        return None
    return base


def on_disk(repo):
    """Сколько байт уже лежит там, куда идёт загрузка, включая недокачанное."""
    base = target(repo)
    if base is None:
        return _size(cache_dir(repo) / "blobs")
    return _size(repo_dir(repo, base)) if mounted(base) else 0


def state(repo):
    """ready, offline (на отключённом диске), downloading, queued, partial, absent."""
    if resolve(repo) is not None:
        return "ready"
    placed = _placed(repo)
    if placed and not mounted(placed):
        return "offline"
    st = status()
    if (st.get("current") or {}).get("repo") == repo and worker_alive():
        return "downloading"
    if any(j["repo"] == repo for j in queue()):
        return "queued"
    return "partial" if on_disk(repo) > 50e6 else "absent"


def remove(repo):
    """Убирает модель отовсюду, где она есть на подключённых дисках."""
    import shutil
    for base in dict.fromkeys(b for b in (_placed(repo), folder()) if b):
        if mounted(base):
            shutil.rmtree(repo_dir(repo, base), ignore_errors=True)
    shutil.rmtree(cache_dir(repo), ignore_errors=True)
    _remember(repo, None)


def queue():
    return _read(QUEUE, [])


def status():
    return _read(STATUS, {})


def progress(repo):
    """Ход загрузки этой модели: (доля, байт в секунду, секунд осталось) или None."""
    cur = status().get("current") or {}
    if cur.get("repo") != repo or not worker_alive():
        return None
    total, done = cur.get("total") or 0, cur.get("done") or 0
    speed = cur.get("speed") or 0
    left = (total - done) / speed if speed > 0 and total else None
    return (done / total if total else 0.0), speed, left


_tr = str


def set_translator(fn):
    """Подписи хода — на языке приложения: fn берёт русскую заготовку."""
    global _tr
    _tr = fn


def describe(repo):
    """Строка хода для окна: «34% · 2,1 МБ/с · ещё 1 ч 20 мин» или «в очереди»."""
    p = progress(repo)
    if p is not None:
        share, speed, left = p
        parts = [f"{share * 100:.0f}%"]
        if speed:
            mb = f"{speed / 1e6:.1f}"
            parts.append(_tr("{mb} МБ/с").format(mb=mb if _tr("МБ/с") != "МБ/с" else mb.replace(".", ",")))
        if left:
            h, m = divmod(int(left // 60), 60)
            parts.append(_tr("ещё {h} ч {m} мин").format(h=h, m=m) if h
                         else _tr("ещё {m} мин").format(m=max(m, 1)))
        return " · ".join(parts)
    q = [j["repo"] for j in queue()]
    if repo in q:
        n = q.index(repo)
        return _tr("в очереди") + (_tr(", перед ней {n}").format(n=n) if n else _tr(", следующая"))
    err = status().get("errors", {}).get(repo)
    return _tr("не вышло: {e}").format(e=err) if err else ""


def enqueue(repo, where=None):
    """В очередь; where — папка для этой модели, «cache» (общий кэш) или None —
    туда, куда покажет target()."""
    q = queue()
    if not any(j["repo"] == repo for j in q):
        base = target(repo) if where is None else None if where == "cache" else Path(where)
        if base is not None and not mounted(base):
            raise RuntimeError(_tr("Папка недоступна: {where}").format(where=label(base)))
        q.append({"repo": repo, "dest": str(base) if base else None})
        _write(QUEUE, q)
        st = status()
        st.get("errors", {}).pop(repo, None)
        _write(STATUS, st)
    start_worker()


def cancel(repo):
    """Убрать из очереди; если качается сейчас — остановить (докачается с места)."""
    _write(QUEUE, [j for j in queue() if j["repo"] != repo])
    st = status()
    if (st.get("current") or {}).get("repo") == repo:
        st["stop"] = repo
        _write(STATUS, st)


def worker_alive():
    """Жив ли загрузчик: он держит замок на файле, пока работает."""
    HOME.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
        return False


def start_worker():
    """Запускает загрузчик, если его нет. Он живёт отдельно от приложения."""
    if worker_alive() or not queue():
        return
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    log = open(HOME / "загрузчик.log", "a")
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "worker"],
                     stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     start_new_session=True, env=env, cwd=str(HOME))


def _proxy_env():
    found = urllib.request.getproxies()
    for scheme in ("http", "https"):
        if found.get(scheme):
            os.environ.setdefault(f"{scheme}_proxy", found[scheme])


def _open(url, start=0):
    req = urllib.request.Request(url, headers={"User-Agent": "models-home/1.0",
                                               **({"Range": f"bytes={start}-"} if start else {})})
    return urllib.request.urlopen(req, timeout=60)


def _files(repo):
    with _open(f"https://huggingface.co/api/models/{repo}?blobs=true") as r:
        info = json.loads(r.read())
    out = []
    for s in info.get("siblings", []):
        lfs = s.get("lfs") or {}
        sha = lfs.get("sha256")
        out.append((s["rfilename"], s.get("size") or lfs.get("size") or 0, sha, sha or s.get("blobId")))
    return info["sha"], out


def _adopt(final, part):
    """Брошенные куски huggingface_hub («<blob>.<случайное>.incomplete») — начало
    того же файла: самый длинный становится нашим «.part», остальные — прочь."""
    if part.exists():
        return
    olds = sorted(final.parent.glob(final.name + ".*.incomplete"), key=lambda p: p.stat().st_size)
    if olds:
        olds[-1].rename(part)
        for p in olds[:-1]:
            p.unlink(missing_ok=True)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * CHUNK), b""):
            h.update(block)
    return h.hexdigest()


class Stopped(Exception):
    pass


def _get(url, part, size, sha, tick, stop):
    for attempt in range(80):
        if stop():
            raise Stopped
        have = part.stat().st_size if part.exists() else 0
        if size and have >= size:
            break
        try:
            with _open(url, have) as r:
                if r.status == 200:
                    have = 0
                with open(part, "ab" if have else "wb") as f:
                    while True:
                        if stop():
                            raise Stopped
                        block = r.read(CHUNK)
                        if not block:
                            break
                        f.write(block)
                        tick(len(block))
        except Stopped:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 416:
                break
            time.sleep(min(3 + attempt * 2, 30))
        except Exception:
            time.sleep(min(3 + attempt * 2, 30))
    if size and part.stat().st_size != size:
        raise IOError(f"{part.name}: скачалось {part.stat().st_size} из {size}")
    if sha and _sha256(part) != sha:
        part.unlink(missing_ok=True)
        raise IOError("не сошлась контрольная сумма, файл скачается заново")


def fetch(repo, dest=None, on_progress=None, stop=lambda: False):
    """Скачивает модель целиком. dest — папка-хранилище (внутри — папка модели);
    None — общий кэш. on_progress(всего, готово). Повтор продолжает с места."""
    commit, files = _files(repo)
    total = sum(f[1] for f in files)
    if dest is None:
        root = cache_dir(repo)
        snap = root / "snapshots" / commit
        for d in (root / "blobs", snap, root / "refs"):
            d.mkdir(parents=True, exist_ok=True)
        place = lambda name, blob: root / "blobs" / blob
    else:
        out = repo_dir(repo, dest)
        out.mkdir(parents=True, exist_ok=True)
        _remember(repo, Path(dest))
        place = lambda name, blob: out / name
    done = [sum(f[1] for f in files if place(f[0], f[3]).exists())]

    def tick(n):
        done[0] += n
        if on_progress:
            on_progress(total, done[0])

    for name, size, sha, blob in files:
        final = place(name, blob)
        if not final.exists():
            final.parent.mkdir(parents=True, exist_ok=True)
            part = final.with_name(final.name + ".part")
            _adopt(final, part)
            done[0] += part.stat().st_size if part.exists() else 0
            _get(f"https://huggingface.co/{repo}/resolve/{commit}/{name}", part, size, sha, tick, stop)
            part.rename(final)
        if dest is None:
            link = snap / name
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.exists():
                link.symlink_to(os.path.relpath(final, link.parent))
    if dest is None:
        (root / "refs" / "main").write_text(commit)
    if on_progress:
        on_progress(total, total)
    return resolve(repo)


def _worker():
    """Загрузчик: берёт из очереди по одной, пишет ход раз в секунду."""
    _proxy_env()
    HOME.mkdir(parents=True, exist_ok=True)
    lock = open(LOCK, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return          # уже работает другой
    while True:
        q = queue()
        if not q:
            st = status()
            st["current"] = None
            _write(STATUS, st)
            return
        job = q[0]
        repo = job["repo"]
        mark = {"t": time.time(), "done": 0, "window": []}

        def report(total, done, job=job):
            now = time.time()
            if now - mark["t"] < 1.0 and done < total:
                return
            w = mark["window"]
            w.append((now, done))
            del w[:-15]
            speed = (w[-1][1] - w[0][1]) / (w[-1][0] - w[0][0]) if len(w) > 1 and w[-1][0] > w[0][0] else 0
            st = status()
            st["current"] = {"repo": job["repo"], "dest": job["dest"], "total": total, "done": done,
                             "speed": speed, "updated": now}
            st["updated"] = now
            _write(STATUS, st)
            mark["t"] = now

        def stop():
            return status().get("stop") == repo

        try:
            fetch(repo, Path(job["dest"]) if job["dest"] else None, report, stop)
            st = status()
            st.setdefault("done", {})[repo] = time.time()
        except Stopped:
            st = status()
        except Exception as e:
            st = status()
            st.setdefault("errors", {})[repo] = str(e)[:200]
        st.pop("stop", None)
        st["current"] = None
        _write(STATUS, st)
        _write(QUEUE, [j for j in queue() if j["repo"] != repo])


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "worker":
    _worker()
