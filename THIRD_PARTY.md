# Third-party software and models

Chinese Shadow Speech is licensed under the GNU Affero General Public License v3.0 or later (see `LICENSE`).
It builds on the work below, each under its own licence. Nothing here is modified unless stated.

## Speech models (downloaded on first launch, not shipped in the installer)

| Model | Used for | Licence | Source |
|---|---|---|---|
| Paraformer-large with VAD (`iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch`), FunASR / Alibaba DAMO Academy | Speech recognition | Apache-2.0 (ModelScope model page) | https://www.modelscope.cn/models/iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch |
| CT-Transformer punctuation, sherpa-onnx int8 conversion (`sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8`) of `iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch` | Punctuation | Apache-2.0 (upstream ModelScope model page) | https://k2-fsa.github.io/sherpa/onnx/punctuation/pretrained_models.html |
| MMS forced-alignment model (torchaudio `MMS_FA`), Meta AI | Aligning characters to audio | **CC-BY-NC 4.0, non-commercial use only** | https://github.com/facebookresearch/fairseq/tree/main/examples/mms |
| `TencentGameMate/chinese-wav2vec2-base` | Tone features | MIT (Hugging Face model card) | https://huggingface.co/TencentGameMate/chinese-wav2vec2-base |
| `wbbbbb/wav2vec2-large-chinese-zh-cn`, fine-tuned from `facebook/wav2vec2-large-xlsr-53` | Wrong-sound detection | Apache-2.0 (Hugging Face model card) | https://huggingface.co/wbbbbb/wav2vec2-large-chinese-zh-cn |

Because the MMS alignment model is non-commercial, the app as distributed is for non-commercial use. Selling it,
or using it in a paid service, would need a different aligner first.

Citations requested by the model authors:

- MMS: Pratap et al., "Scaling Speech Technology to 1,000+ Languages", arXiv:2305.13516 (2023).
- FunASR: Gao et al., "FunASR: A Fundamental End-to-End Speech Recognition Toolkit", Interspeech 2023.
- chinese-wav2vec2: TencentGameMate, Chinese speech pretraining, https://github.com/TencentGameMate/chinese_speech_pretrain (2022).

## Programs shipped in the Windows installer

| Program | Licence | Source |
|---|---|---|
| CPython 3.12 (python-build-standalone) | Python Software Foundation License | https://github.com/astral-sh/python-build-standalone |
| uv | Apache-2.0 or MIT | https://github.com/astral-sh/uv |
| FFmpeg and ffprobe (LGPL build) | LGPL-3.0-or-later | https://github.com/BtbN/FFmpeg-Builds, https://ffmpeg.org/ |
| Deno | MIT | https://github.com/denoland/deno |

The exact versions are in `packaging/windows/versions.json`. The installed `tools\THIRD-PARTY.txt` lists them as well.

## Main libraries

Installed from PyPI and npm at their published versions (pinned in `backend/uv.lock` and `frontend/package-lock.json`).

| Library | Licence |
|---|---|
| praat-parselmouth (Praat) | GPL-3.0-or-later |
| pystray (Windows tray icon) | LGPL-3.0 |
| PyTorch, torchaudio | BSD-3-Clause, BSD-2-Clause |
| transformers, modelscope, sherpa-onnx, qwen-asr, opencc-python-reimplemented, python-multipart | Apache-2.0 |
| FunASR, FastAPI, SQLModel, Pydantic, pypinyin, jieba, rapidfuzz, Pillow (MIT-CMU) | MIT |
| uvicorn, sse-starlette, httpx, NumPy, SciPy, scikit-learn, umap-learn, soundfile, psutil, joblib | BSD |
| librosa | ISC |
| yt-dlp, yt-dlp-ejs | Unlicense (yt-dlp-ejs also MIT and ISC) |
| React and the other frontend packages | MIT (see `frontend/package-lock.json`) |
