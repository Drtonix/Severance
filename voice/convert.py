"""Смена голоса: Seed-VC, модель для пения (44 кГц, с сохранением мелодии).

Живёт в своём окружении — Seed-VC требует numpy<2, а разделители Severance — numpy 2;
лицензия у него GPL-3.0, отдельный процесс её не распространяет на Severance.
Ход работы — строками в stdout: «models», «chunk 3/9», «done».
"""
import argparse
import math
import sys
import types

import numpy as np
import soundfile as sf


class Mps(str):
    """Обёртка Seed-VC сравнивает устройство со строкой «mps» и тут же берёт .type:
    ни torch.device, ни строка по отдельности её не устраивают."""
    type = "mps"


def drain(gen):
    """Без потокового режима обёртка возвращает звук через StopIteration."""
    last = None
    try:
        while True:
            last = next(gen)
    except StopIteration as stop:
        return stop.value if stop.value is not None else last


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source")
    p.add_argument("reference")
    p.add_argument("out")
    p.add_argument("--steps", type=int, default=30)
    p.add_argument("--shift", type=int, default=0)
    a = p.parse_args()

    import torch
    from seed_vc.seed_vc_wrapper import SeedVCWrapper

    if torch.backends.mps.is_available():
        device = Mps("mps")
    elif torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"
    print("models", flush=True)
    w = SeedVCWrapper(device=device)

    # В окне 30 с контекста часть занимает образец, на песню остаётся остальное:
    # с образцом 10 с кусок — 20 с, с образцом 25 с — всего 5 с.
    room = max(30 - min(sf.info(a.reference).duration, 25) - 0.5, 1)
    total = max(1, math.ceil(sf.info(a.source).duration / room))
    done = {"n": 0}
    original = w._stream_wave_chunks

    def counted(*args, **kwargs):
        done["n"] += 1
        print(f"chunk {min(done['n'], total)}/{total}", flush=True)
        return original(*args, **kwargs)

    w._stream_wave_chunks = counted
    out = w.convert_voice(a.source, a.reference, diffusion_steps=a.steps, f0_condition=True,
                          auto_f0_adjust=False, pitch_shift=a.shift, stream_output=False)
    if isinstance(out, types.GeneratorType):
        out = drain(out)
    if isinstance(out, tuple):
        out = out[-1]
    sf.write(a.out, np.asarray(out, dtype=np.float32).squeeze(), 44100)
    print("done", flush=True)


if __name__ == "__main__":
    sys.exit(main())
