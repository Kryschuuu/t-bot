FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        fonts-dejavu-core \
        libharfbuzz-subset0 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

RUN groupadd --system app && useradd --system --gid app --home /app app
COPY --chown=app:app . .
# WORKDIR legt /app als root an. Der unprivilegierte Runtime-Benutzer muss
# STATIC_ROOT (und ggf. lokale Cache-Verzeichnisse) darin anlegen dürfen.
RUN chmod +x /app/docker-entrypoint.sh && chown app:app /app
USER app

RUN SECRET_KEY=build-only-secret-key \
    PASSPHRASE=build-only-passphrase \
    DEBUG=False \
    python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["/app/docker-entrypoint.sh"]
