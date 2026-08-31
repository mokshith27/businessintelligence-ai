# syntax=docker/dockerfile:1

FROM python:3.12-slim

WORKDIR /app

# Non-interactive and unbuffered runtime.
ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build/runtime system deps for transformers + sentencepiece.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching).
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

# Copy the application source + tracked data (raw CSVs, config, docs).
COPY . .

# Make Windows/macOS line endings safe for the shell entrypoint.
RUN sed -i 's/\r$//' docker/entrypoint.sh && \
    chmod +x docker/entrypoint.sh

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]