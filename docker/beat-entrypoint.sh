#!/bin/sh
set -eu

# shellcheck source=docker/load-tuning.sh
. /app/docker/load-tuning.sh

python manage.py wait_for_database
exec celery -A trading_bot_project beat --loglevel="${CELERY_LOG_LEVEL:-INFO}"
