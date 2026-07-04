# API + workers image. All runtime deps ship manylinux wheels for cp312, so python:3.12-slim
# needs no compiler. (Add the `.[onnx]` extra to bundle the self-hosted BGE embed/rerank.)
FROM python:3.12-slim

# EMBED_CACHE_DIR pins fastembed's model cache to a persistent path so the ONNX weights are baked
# into an image layer (below) — every teammate runs the identical model with no runtime download.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    EMBED_CACHE_DIR=/app/models

WORKDIR /app

# Copy metadata + source needed for the editable install and at runtime.
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY contracts ./contracts

# Install with the self-hosted embed/rerank extra (fastembed/ONNX).
RUN pip install --upgrade pip && pip install -e ".[onnx]"

# Bake the real embed + rerank models into the image (downloads into /app/models). Uses the pinned
# config model ids; runs even though USE_FAKE_EMBEDDINGS defaults true (we instantiate directly).
RUN python -c "import asyncio; from app.core.config import get_settings as g; from app.infra.embeddings.bge_onnx_client import BgeOnnxClient as B; s=g(); asyncio.run(B(embed_model=s.embed_model, rerank_model=s.rerank_model, dim=s.embed_dim, cache_dir='/app/models').warmup())"

EXPOSE 8000

# Overridden by docker-compose (api runs migrations first; workers run celery).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
