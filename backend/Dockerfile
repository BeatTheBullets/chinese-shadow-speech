FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/backend
# Dependency layer (no models extra: CPU / no-model image)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY config.toml /app/config.toml
COPY frontend/dist /app/frontend/dist
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "shadow.main:app", "--host", "0.0.0.0", "--port", "8000"]
