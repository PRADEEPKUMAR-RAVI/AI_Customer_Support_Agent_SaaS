# API + workers image. All runtime deps ship manylinux wheels for cp312, so python:3.12-slim
# needs no compiler. (Add the `.[onnx]` extra to bundle the self-hosted BGE embed/rerank.)
FROM python:3.12-slim

# EMBED_CACHE_DIR pins fastembed's model cache to /app/models. docker-compose mounts a named
# volume there, so the real BGE embed/rerank ONNX weights download ONCE at runtime (first embed)
# and persist across rebuilds/restarts — keeping image builds fast (no multi-GB model baked into
# every build, and no fragile network download inside the build step).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    EMBED_CACHE_DIR=/app/models

WORKDIR /app

# onnxruntime (pulled in by the .[onnx] extra) dynamically links libgomp.so.1 (OpenMP) and does
# NOT bundle it; python:3.12-slim (Debian bookworm-slim) omits it, so `import onnxruntime` — and
# thus the real BGE embed/rerank path — fails with "libgomp.so.1: cannot open shared object file"
# unless libgomp1 is installed. Install it before the pip step.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy metadata + source needed for the editable install and at runtime.
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY contracts ./contracts

# Install with the self-hosted embed/rerank extra (fastembed/ONNX). The model WEIGHTS are NOT
# baked here — they download at runtime into EMBED_CACHE_DIR (the mounted volume) on first use.
RUN pip install --upgrade pip && pip install -e ".[onnx]"

EXPOSE 8000

# Overridden by docker-compose (api runs migrations first; workers run celery).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
