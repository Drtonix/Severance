# Third-party components

The MIT license in `LICENSE` covers the code in this repository except
`voice/`, which is GPL-3.0 (see `voice/LICENSE`). The distributed `.app` bundle
also contains the components below. Their full license texts are inside the
bundle, in `Contents/Resources/Лицензии`.

## Bundled in the application

| Component | Version | License | Source |
|---|---|---|---|
| Qt (via PySide6) | 6.12.0 | LGPL-3.0 | https://download.qt.io/official_releases/QtForPython/ |
| FFmpeg | 7.1 | LGPL-2.1-or-later | https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz |
| CPython | 3.12.14, 3.11.16 | PSF-2.0 | https://github.com/astral-sh/python-build-standalone |
| MLX | 0.32.3 | MIT | https://github.com/ml-explore/mlx |
| mlx-audio-separator | 0.1.20 | MIT | https://pypi.org/project/mlx-audio-separator/ |
| demucs-mlx | 1.6.1 | MIT | https://pypi.org/project/demucs-mlx/ |
| beat-this | 1.1.0 | MIT | https://github.com/CPJKU/beat_this |
| lv-chordia | 1.1.0 | MIT | https://github.com/openmirlab/lv-chordia |
| yt-dlp | 2026.8.19 | Unlicense | https://github.com/yt-dlp/yt-dlp |
| lameenc (LAME) | 1.8.4 | LGPL-3.0-or-later | https://github.com/chrisstaite/lameenc |
| PyTorch | 2.14.1 | BSD-3-Clause | https://github.com/pytorch/pytorch |
| librosa, scikit-learn, NumPy, SoundFile | 1.0.0 / 1.9.1 / 2.5.3 / 0.14.0 | ISC / BSD-3-Clause / BSD-3-Clause / BSD-3-Clause | https://pypi.org |
| mlx-whisper | 0.4.3 | MIT | https://github.com/ml-explore/mlx-examples |
| pyworld (WORLD vocoder) | 0.3.5 | MIT / modified BSD | https://github.com/JeremyCCHsu/Python-Wrapper-for-World-Vocoder |
| Seed-VC | 0.4.3 | GPL-3.0 | https://github.com/Plachtaa/seed-vc |
| sherpa-onnx | 1.13.8 | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |
| Transformers | 4.57.6 | Apache-2.0 | https://github.com/huggingface/transformers |

FFmpeg is built from unmodified upstream sources with `--disable-autodetect`
and no GPL components enabled, so it is distributed under LGPL-2.1. The exact
configure flags are in `build_app.sh`.

Qt, FFmpeg and LAME are dynamically loaded. To relink the application against
your own builds, replace the libraries in
`Severance.app/Contents/Resources/python/lib/python3.12/site-packages/PySide6`,
the `lameenc` extension next to it, or the binaries in
`Severance.app/Contents/Resources/app/bin`.

Seed-VC runs as a separate program in `Severance.app/Contents/Resources/voice`.
The source of `voice/` is in this repository, Seed-VC's is at the URL above.

## Neural network weights

Downloaded on first use and not redistributed, except TitaNet, which
`build_app.sh` places in the bundle:

| Model | Used for | License | Source |
|---|---|---|---|
| BS-RoFormer (ep 317, SDR 12.97, viperx) | vocals and music | see source | https://github.com/TRvlvr/model_repo |
| Mel-Band RoFormer karaoke (becruily) | lead and backing vocals | see source | https://huggingface.co/becruily/mel-band-roformer-karaoke |
| BS-RoFormer SW | instruments | see source | https://huggingface.co/jarredou/BS-ROFO-SW-Fixed |
| MDX23C DrumSep (aufr33, jarredou) | drum parts | see source | https://github.com/jarredou/models |
| HTDemucs FT | voice sample cleanup | MIT | https://github.com/facebookresearch/demucs |
| Whisper large-v3 (MLX) | lyrics | MIT | https://huggingface.co/mlx-community/whisper-large-v3-mlx |
| Seed-VC, BigVGAN, CAM++ | voice change, voice prints | GPL-3.0 / MIT / Apache-2.0 | https://github.com/Plachtaa/seed-vc |
| NeMo TitaNet-L (ONNX) | voice prints | CC-BY-4.0 | https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models |
