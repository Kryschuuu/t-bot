# trading_bot_project/settings.py
import logging
import os
from pathlib import Path

import dj_database_url

# ---------------------------------------------------------------------------
# Basisverzeichnis
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)


def env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def env_int(name, default, minimum=1):
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        logger.warning("Ungültiger Integerwert für %s; verwende %s", name, default)
        return default


# ---------------------------------------------------------------------------
# Sicherheit / Grundkonfiguration
# ---------------------------------------------------------------------------
# WICHTIG: In Produktion (Render) MUSS SECRET_KEY über die Environment-Variable
# gesetzt werden. Vorher wurde bei jedem Prozessstart ein neuer, zufälliger Key
# erzeugt (secrets.token_urlsafe(50)) - das invalidiert bei mehreren Workern
# (oder jedem Neustart/Deploy) sofort alle Sessions und CSRF-Tokens.
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if env_bool("RENDER", False):
        raise RuntimeError(
            "SECRET_KEY environment variable is required on Render. "
            "Set it in the service's Environment settings."
        )
    # Nur für lokale Entwicklung: stabiler Dummy-Key (kein Zufalls-Reset mehr)
    SECRET_KEY = "django-insecure-local-dev-key-not-for-production"

DEBUG = env_bool("DEBUG", default=not env_bool("RENDER", False))

# Render stellt den öffentlichen Hostnamen automatisch als Env-Var bereit
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
extra_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS += [h.strip() for h in extra_hosts.split(",") if h.strip()]
if DEBUG:
    ALLOWED_HOSTS.append("*")

CSRF_TRUSTED_ORIGINS = []
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")
extra_origins = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS += [o.strip() for o in extra_origins.split(",") if o.strip()]

# ---------------------------------------------------------------------------
# Celery-Konfiguration
# ---------------------------------------------------------------------------
# Render Free Tier bietet keinen kostenlosen Redis/Broker und keine
# Background-Worker-Instanzen. Ist kein REDIS_URL gesetzt, laeuft Celery im
# "eager" Modus: app.task.delay(...) fuehrt die Aufgabe SOFORT UND SYNCHRON
# im aufrufenden Prozess aus - es wird weder ein Broker noch ein separater
# Worker-Prozess benoetigt. Sobald REDIS_URL gesetzt ist (z.B. Render Key
# Value oder ein externer Redis-Dienst auf einem bezahlten Plan), wird ganz
# normal ueber den Broker verteilt und ein "celery worker" Prozess kann die
# Tasks abarbeiten.
REDIS_URL = os.environ.get("REDIS_URL")

CELERY_TIMEZONE = "UTC"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 60
CELERY_TASK_TIME_LIMIT = 60 * 60 + 300

if REDIS_URL:
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
    CELERY_TASK_ALWAYS_EAGER = False
else:
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

# ---------------------------------------------------------------------------
# Security Header (nur wenn nicht DEBUG)
# ---------------------------------------------------------------------------
if not DEBUG:
    # Render terminiert TLS bereits am Edge/Loadbalancer und leitet Requests
    # per HTTP an den Container weiter, setzt aber den Header X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_REFERRER_POLICY = "same-origin"
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

LOGIN_URL = "/login/"

# ---------------------------------------------------------------------------
# Apps / Middleware
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "trading.apps.TradingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "trading.middleware.PassphraseGateMiddleware",
]

ROOT_URLCONF = "trading_bot_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Channels (WebSocket) Konfiguration
# ---------------------------------------------------------------------------
# Render Free Tier laeuft immer nur mit EINER Instanz (kein Autoscaling im
# Free Plan), daher reicht der In-Memory Channel-Layer vollkommen aus und
# es wird kein Redis benoetigt. Wird REDIS_URL gesetzt (z.B. bei einem
# Upgrade auf einen bezahlten Plan mit mehreren Instanzen), wird automatisch
# auf den Redis-Channel-Layer umgeschaltet.
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }

ASGI_APPLICATION = "trading_bot_project.asgi.application"
WSGI_APPLICATION = "trading_bot_project.wsgi.application"

# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------
# Render stellt bei verknuepfter Postgres-Instanz automatisch DATABASE_URL
# bereit. Lokal faellt die App auf SQLite zurueck, falls nichts gesetzt ist.
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            # BUGFIX ("connection already closed" / psycopg2.InterfaceError,
            # siehe trading/trading_bot.py db_safe()): Render Postgres Free
            # Tier kappt idle gewordene Connections serverseitig deutlich
            # frueher als die alten 600s. Django hat das bis dato nicht
            # bemerkt (kein CONN_HEALTH_CHECKS) und eine bereits tote
            # Connection einfach weiterverwendet -> InterfaceError bei der
            # naechsten Query. conn_max_age auf 60s gesenkt (kuerzeres
            # "Verfallsdatum" pro Connection) UND conn_health_checks=True
            # aktiviert: Django pingt eine wiederverwendete Connection kurz
            # (SELECT 1), bevor sie fuer eine Query genutzt wird, und
            # verwirft+erneuert sie automatisch, falls der Ping fehlschlaegt.
            # Das greift ueberall dort, wo Django selbst den Request-Zyklus
            # steuert (Views, Admin, Channels-Consumer). Fuer den dauerhaft
            # laufenden TradingBot-Thread (kein Request-Zyklus, daher feuert
            # der Health-Check-Trigger dort nie) sorgt zusaetzlich der
            # eigene db_safe()-Reconnect-Decorator in trading_bot.py.
            conn_max_age=60,
            conn_health_checks=True,
            ssl_require=env_bool("DATABASE_SSL_REQUIRE", True),
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "de-de"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static Files (WhiteNoise - kein persistenter Storage auf Render noetig)
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Render Free Tier hat KEINEN persistenten Storage - Logdateien wuerden bei
# jedem Deploy/Neustart verloren gehen. Daher wird in Produktion nach STDOUT
# geloggt (von Render automatisch eingesammelt); lokal weiterhin zusaetzlich
# in eine Datei.
handlers = {
    "console": {
        "level": "INFO",
        "class": "logging.StreamHandler",
    },
}
trading_handlers = ["console"]

if DEBUG:
    handlers["file"] = {
        "level": "DEBUG",
        "class": "logging.FileHandler",
        "filename": os.path.join(BASE_DIR, "trading_bot.log"),
        "formatter": "verbose",
    }
    trading_handlers.append("file")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
    },
    "handlers": handlers,
    "loggers": {
        "trading": {
            "handlers": trading_handlers,
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# App-spezifische Einstellungen
# ---------------------------------------------------------------------------
# Steuert, ob TradingBots fuer aktive Konfigurationen beim Prozessstart
# automatisch gestartet werden sollen (siehe trading/apps.py).
AUTOSTART_BOTS = env_bool("AUTOSTART_BOTS", True)
MAX_DATA_LOGS_PER_SYMBOL = env_int("MAX_DATA_LOGS_PER_SYMBOL", 20_000, minimum=1_000)
DATA_LOG_CLEANUP_EVERY = env_int("DATA_LOG_CLEANUP_EVERY", 500, minimum=10)

# ---------------------------------------------------------------------------
# Passphrase-Gate (Landingpage vor Registrierung/Login)
# ---------------------------------------------------------------------------
PASSPHRASE = os.environ.get("PASSPHRASE")
if not PASSPHRASE:
    if env_bool("RENDER", False):
        raise RuntimeError(
            "PASSPHRASE environment variable is required on Render. "
            "Generate it in the service environment settings."
        )
    PASSPHRASE = "local-development-only"
PASSPHRASE_GATE_ENABLED = env_bool("PASSPHRASE_GATE_ENABLED", True)
