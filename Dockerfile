FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl sqlite3 cron ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

COPY . .

RUN mkdir -p /data/media /data/backups

# Install backup cron job: daily at 03:00 UTC
RUN echo '0 3 * * * /app/scripts/backup.sh >> /var/log/backup.log 2>&1' | crontab -

EXPOSE 8000

# Startup: run cron daemon, migrations, seed, then uvicorn
CMD ["sh", "-c", "cron && uv run alembic upgrade head && uv run python -m app.seed && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
