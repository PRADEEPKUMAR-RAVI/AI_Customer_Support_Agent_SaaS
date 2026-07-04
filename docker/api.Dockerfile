# API + workers image. All runtime deps ship manylinux wheels for cp312, so python:3.12-slim
# needs no compiler. (Add the `.[onnx]` extra to bundle the self-hosted BGE embed/rerank.)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy metadata + source needed for the editable install and at runtime.
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY contracts ./contracts

RUN pip install --upgrade pip && pip install -e .
# For real self-hosted embeddings/rerank instead of fakes, build with:  pip install -e ".[onnx]"

EXPOSE 8000

# Overridden by docker-compose (api runs migrations first; workers run celery).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
