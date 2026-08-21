#!/bin/sh
set -eu

python manage.py wait_for_database
exec celery -A trading_bot_project beat --loglevel="${CELERY_LOG_LEVEL:-INFO}"
