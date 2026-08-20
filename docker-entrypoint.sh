#!/bin/sh
set -eu

python manage.py wait_for_database
python manage.py migrate --noinput
exec daphne -b 0.0.0.0 -p "${PORT:-8000}" trading_bot_project.asgi:application
