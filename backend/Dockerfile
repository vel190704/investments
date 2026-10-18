# Backend image (FastAPI + Uvicorn). Configuration comes from environment variables only (docs/DEPLOY.md).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
COPY deploy ./deploy

# Writable scratch for download caches and log files (ephemeral; the database is Postgres).
RUN mkdir -p /app/data /app/logs && chown -R app:app /app/data /app/logs
ENV DATA_DIR=/app/data LOG_DIR=/app/logs PORT=8000

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8000'), timeout=4)"

# Release step (run once per deploy, before the new version starts): alembic upgrade head
# Start: real client IPs come from the host's proxy headers (rate limits use them).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
