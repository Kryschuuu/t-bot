#!/bin/sh
set -eu

python manage.py wait_for_database
exec celery -A trading_bot_project worker \
  -Q backtest \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency=1 \
  --prefetch-multiplier=1 \
  --max-tasks-per-child=1 \
  --max-memory-per-child="${CELERY_WORKER_MAX_MEMORY_PER_CHILD:-384000}"
