#!/bin/sh
set -eu

# Migrationen verwenden immer die direkte PostgreSQL-Verbindung. Die App nutzt
# DATABASE_POOL_URL nur, wenn auf einem bezahlten Datastore PgBouncer aktiviert ist.
USE_DIRECT_DATABASE_URL=True python manage.py wait_for_database
USE_DIRECT_DATABASE_URL=True python manage.py migrate --noinput
exec daphne -b 0.0.0.0 -p "${PORT:-8000}" trading_bot_project.asgi:application
