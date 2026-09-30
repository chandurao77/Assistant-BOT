FROM python:3.11-slim AS base

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# ── Dependency layer (cached unless requirements change) ──────────────────────
FROM base AS deps
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-lock.txt

# ── Runtime ───────────────────────────────────────────────────────────────────
FROM deps AS runtime
COPY app/ ./app/
COPY pyproject.toml .

# Non-root user — create /app/data before the volume is mounted so appuser owns it.
# The 'fix-perms' trick: the runtime copies the image's /app/data ownership to the volume
# on first mount when an image VOLUME declaration preexists.
RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

VOLUME /app/data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-1}"]
