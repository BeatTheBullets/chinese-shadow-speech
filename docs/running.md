# Running

## Dev (WSL2, GPU)
    cd backend && uv sync --extra dev --extra models      # pulls torch from the PyTorch cu126 index
    export ANTHROPIC_API_KEY=...                          # optional; without it rectification/translation are skipped
    cd .. && make dev

The GPU driver must support CUDA 12.6 (Windows NVIDIA driver >= 560).
First ingest downloads Paraformer-zh (~1 GB, ModelScope) and the MMS_FA aligner (~1.2 GB, torchaudio).
Before the first real ingest, smoke-test Paraformer and the aligners: `cd backend && uv run pytest -m models`.
Verify the GPU is seen: `curl -s localhost:8000/health` -> `"device": "cuda"`.

## CPU only
Set `[models] device = "cpu"` in config.toml; the aligner is MMS_FA on every device (`aligner = "qwen3_fa"` selects Qwen3 explicitly).

## Docker
    cd frontend && npm run build        # produces frontend/dist, which the image copies
    ANTHROPIC_API_KEY=... docker compose up --build

Serves the SPA and API on http://127.0.0.1:8000. The image is built without the `models` extra
(no torch), so it is for CPU / no-model use only; run the real models from the dev setup above.
Data lives in `./data`, config in `./config.toml` (mounted read-only).

## Tests
    make test                       # fakes only, no models
    cd backend && uv run pytest -m models   # real-model smoke tests
