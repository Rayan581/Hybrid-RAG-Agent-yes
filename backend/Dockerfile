# =============================================================================
# backend/Dockerfile
# CPU-optimised FastAPI + llama-cpp-python backend for Daraz Voice Assistant.
# Multi-stage build: keeps the final image lean by separating build deps.
# =============================================================================

# -----------------------------------------------------------------------------
# STAGE 1 — Builder
# Compiles llama-cpp-python from source (required for CPU-only GGUF inference).
# Build tools are NOT copied to the final image.
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Build dependencies for llama-cpp-python C++ compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only requirements first — Docker layer cache skips re-install
# if requirements haven't changed between builds.
COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install --prefix=/install \
    --default-timeout=1000 --retries=10 \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
    --trusted-host abetlen.github.io \
    -r requirements.txt \
    --no-binary llama-cpp-python

# -----------------------------------------------------------------------------
# STAGE 2 — Runtime
# Minimal image: only Python, installed packages, and app code.
# No compilers, no build tools — smaller attack surface.
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Runtime system deps only (libstdc++ needed by llama-cpp shared libs)
# espeak-ng is required by piper-tts for phoneme conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 \
    libgomp1 \
    curl \
    espeak-ng \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder stage
COPY --from=builder /install /usr/local

# Create non-root user — never run app as root in production
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy application source
COPY src/ ./src/

# /data is the SQLite volume mount point (see docker-compose.yml)
# /models is where the GGUF model file lives (mounted as read-only volume)
RUN mkdir -p /data /models && chown -R appuser:appuser /app /data /models

USER appuser

# Expose FastAPI port
EXPOSE 8000

# Health check — docker-compose and orchestrators use this to know when
# the container is ready to accept traffic.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# -----------------------------------------------------------------------------
# Start uvicorn with:
#   --workers 1     → single worker (one LLM instance; ThreadPool handles concurrency)
#   --loop uvloop   → faster async event loop
#   --timeout-keep-alive 75 → keeps WebSocket connections alive
# For 4 concurrent users on CPU, 1 worker + ThreadPool is the right model.
# Multiple workers would each load the GGUF into RAM — not viable on a laptop.
# -----------------------------------------------------------------------------
CMD ["uvicorn", "src.main:app", \
    "--host", "0.0.0.0", \
    "--port", "8000", \
    "--workers", "1", \
    "--loop", "uvloop", \
    "--timeout-keep-alive", "75"]