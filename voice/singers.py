"""Кто когда поёт: отпечатки голоса CAM++ по окнам чистого вокала и кластеризация.

Окна по 2 с с шагом 1 с там, где поют; отпечаток — CAM++ из Seed-VC (192 числа).
Деление — спектральная кластеризация с числом групп по наибольшему силуэту,
затем слияние групп, похожих на одного человека: средняя похожесть между
группами, делённая на похожесть внутри них, не ниже SAME. На склейках с
известным ответом (один, два, три и четыре исполнителя) число верно в 5 из 6,
окна на своём месте — 91–100%. Итог — JSON: центры окон и номер исполнителя.

Число исполнителей известно (--k: из названия трека или выбрано вручную) —
отпечатки CAM++ и TitaNet (NeMo) склеиваются: на тех же склейках окна на месте
на 88–98%, а на настоящей песне с тремя рэперами куплеты выходят цельными
(17 смен исполнителя против 22 у одного CAM++). Без --k склейка хуже: одного
певца делит надвое — там остаётся CAM++.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

WINDOW, STEP = 2.0, 1.0
SAME = 0.65
# Штраф за смену исполнителя при сглаживании (похожесть окна с голосом группы — от −1 до 1).
# Склейки с известным ответом: 88→91% и 92→97%; смен на настоящей песне — 16→6.
SWITCH = 0.25


def main():
    p = argparse.ArgumentParser()
    p.add_argument("vocals")
    p.add_argument("out")
    p.add_argument("--max", type=int, default=6)
    p.add_argument("--dump", default="")
    p.add_argument("--k", type=int, default=0)
    a = p.parse_args()

    import librosa
    import soundfile as sf
    import torch
    import torchaudio.compliance.kaldi as kaldi
    from seed_vc.modules.campplus.DTDNN import CAMPPlus
    import seed_vc
    from sklearn.cluster import SpectralClustering
    from sklearn.metrics import silhouette_score

    wav, sr = sf.read(a.vocals, dtype="float32", always_2d=True)
    y = librosa.resample(wav.mean(axis=1), orig_sr=sr, target_sr=16000)
    # Где поют: громкость кусками по 0,1 с не тише −35 дБ от самого громкого.
    frames = y[:len(y) // 1600 * 1600].reshape(-1, 1600)
    level = np.sqrt((frames ** 2).mean(axis=1))
    voiced = level > level.max() * 10 ** (-35 / 20)
    centers = []
    t = 0.0
    while t + WINDOW <= len(y) / 16000:
        i0, i1 = int(t * 10), int((t + WINDOW) * 10)
        if voiced[i0:i1].mean() >= 0.5:
            centers.append(t + WINDOW / 2)
        t += STEP
    print(f"windows {len(centers)}", flush=True)
    if len(centers) < 4:
        json.dump({"k": 1, "centers": centers, "labels": [0] * len(centers)}, open(a.out, "w"))
        print("done", flush=True)
        return

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = CAMPPlus(feat_dim=80, embedding_size=192)
    weights = Path(seed_vc.__file__).parent / "campplus_cn_common.bin"
    model.load_state_dict(torch.load(weights, map_location="cpu"))
    model.eval().to(device)
    emb = []
    with torch.no_grad():
        for c in centers:
            seg = torch.from_numpy(y[int((c - WINDOW / 2) * 16000):int((c + WINDOW / 2) * 16000)]).unsqueeze(0)
            feat = kaldi.fbank(seg, num_mel_bins=80, dither=0, sample_frequency=16000)
            feat = feat - feat.mean(dim=0, keepdim=True)
            e = model(feat.unsqueeze(0).to(device)).cpu().numpy()[0]
            emb.append(e / (np.linalg.norm(e) + 1e-9))
    emb = np.array(emb)
    if a.k >= 2:
        titanet = _titanet(y, centers)
        if titanet is not None:
            emb = np.c_[emb, titanet] / np.sqrt(2)
    if a.dump:
        np.save(a.dump, np.c_[np.array(centers)[:, None], emb])
    sim = emb @ emb.T
    affinity = np.clip((sim + 1) / 2, 0, 1)

    if a.k >= 2:
        k = min(a.k, len(emb) - 1)
        labels = SpectralClustering(n_clusters=k, affinity="precomputed", random_state=0,
                                    assign_labels="discretize").fit_predict(affinity)
        labels = smooth(emb, labels, np.array(centers))
        print(f"k {k} задано", flush=True)
        json.dump({"k": int(len(set(labels))), "centers": centers, "labels": [int(x) for x in labels]},
                  open(a.out, "w"))
        print("done", flush=True)
        return

    best_s, labels = -1.0, np.zeros(len(emb), dtype=int)
    for k in range(2, min(a.max, len(emb) - 1) + 1):
        lab = SpectralClustering(n_clusters=k, affinity="precomputed", random_state=0,
                                 assign_labels="discretize").fit_predict(affinity)
        if len(set(lab)) < 2:
            continue
        s = silhouette_score(emb, lab, metric="cosine")
        if s > best_s:
            best_s, labels = s, lab

    # Силуэт делит и одного человека — по куплетам и припевам. Группы, между
    # которыми похожесть почти как внутри, — один исполнитель.
    groups = [list(np.where(labels == g)[0]) for g in sorted(set(labels))]

    def within(g):
        m = sim[np.ix_(g, g)]
        return max((m.sum() - np.trace(m)) / max(len(g) * (len(g) - 1), 1), 1e-3)

    while len(groups) > 1:
        best, pair = -1.0, None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                r = sim[np.ix_(groups[i], groups[j])].mean() / np.sqrt(within(groups[i]) * within(groups[j]))
                if r > best:
                    best, pair = r, (i, j)
        if best < SAME:
            break
        i, j = pair
        groups[i] += groups.pop(j)
    labels = np.zeros(len(emb), dtype=int)
    for i, g in enumerate(groups):
        labels[g] = i
    if len(groups) > 1:
        labels = smooth(emb, labels, np.array(centers))
    best_k = len(set(labels.tolist()))
    print(f"silhouette {best_s:.3f} k {best_k}", flush=True)
    json.dump({"k": int(best_k), "centers": centers, "labels": [int(x) for x in labels],
               "silhouette": float(best_s)}, open(a.out, "w"))
    print("done", flush=True)


def smooth(emb, labels, centers, rounds=3):
    """Окна по отдельности дёргаются между исполнителями. Голос группы — среднее
    её окон; разметка — путь Витерби: сумма похожести окон на голос своей группы
    минус штраф за каждую смену (после паузы длиннее 1,5 с — меньше). Голоса
    групп пересчитываются по новой разметке, и так несколько раз."""
    emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    k = int(labels.max()) + 1
    gap = np.r_[0, np.diff(centers)]
    for _ in range(rounds):
        voice = np.stack([emb[labels == c].mean(0) if (labels == c).any() else np.zeros(emb.shape[1])
                          for c in range(k)])
        voice /= np.linalg.norm(voice, axis=1, keepdims=True) + 1e-9
        score = emb @ voice.T
        best, back = score[0].copy(), np.zeros(score.shape, dtype=int)
        for i in range(1, len(score)):
            pen = SWITCH * (0.4 if gap[i] > 1.5 else 1.0)
            move = best.max() - pen
            back[i] = np.where(best >= move, np.arange(k), best.argmax())
            best = np.maximum(best, move) + score[i]
        path = np.zeros(len(score), dtype=int)
        path[-1] = best.argmax()
        for i in range(len(score) - 1, 0, -1):
            path[i - 1] = back[i, path[i]]
        labels = path
    used = sorted(set(labels.tolist()))
    return np.array([used.index(x) for x in labels])


def _titanet(y, centers):
    """Отпечатки TitaNet по тем же окнам; нет модели или sherpa-onnx — None."""
    model = Path(__file__).resolve().parent / "models" / "nemo_en_titanet_large.onnx"
    try:
        import sherpa_onnx
    except ImportError:
        return None
    if not model.exists():
        return None
    ext = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model), num_threads=4))
    out = []
    for c in centers:
        s = ext.create_stream()
        s.accept_waveform(16000, y[int((c - WINDOW / 2) * 16000):int((c + WINDOW / 2) * 16000)])
        s.input_finished()
        e = np.array(ext.compute(s))
        out.append(e / (np.linalg.norm(e) + 1e-9))
    return np.array(out)


if __name__ == "__main__":
    sys.exit(main())
