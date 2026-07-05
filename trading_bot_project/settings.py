# trading_bot_project/settings.py
import os
from pathlib import Path
import secrets
import logging
import socket

# Logging konfigurieren
logger = logging.getLogger(__name__)

# Basisverzeichnis des Projekts
# BASE_DIR = Path(__file__).resolve().parent
BASE_DIR = Path(__file__).resolve().parent.parent

print(BASE_DIR)
SECRET_KEY = secrets.token_urlsafe(50)
DEBUG = True


# Dynamische Ermittlung der lokalen IP-Adresse
def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Erfordert keine echte Verbindung
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

# Erlaubt localhost, die IP der Maschine und ggf. einen Domainnamen
ALLOWED_HOSTS = ['localhost', '127.0.0.1', get_ip_address()]

# Falls du über Nginx/Proxy zugreifst
CSRF_TRUSTED_ORIGINS = [f"http://{get_ip_address()}:8000", f"https://{get_ip_address()}:8000"]

#ALLOWED_HOSTS = ['127.0.0.1', '0.0.0.0', '192.168.0.4', '192.168.0.217', 'localhost', 'tradingbot.local', 'tbot.local', 'tbot.localhost']

# Celery-Konfiguration
CELERY_TIMEZONE = 'UTC'
USE_TZ = True
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 60  # 1 Stunde
CELERY_TASK_TIME_LIMIT = 60 * 60 + 300  # 1h 5m
# Sicherheitseinstellungen
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_REFERRER_POLICY = 'same-origin'
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

LOGIN_URL = "/login/"

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_extensions',
    'channels',
    'trading.apps.TradingConfig',  # Nur DIESE Zeile behalten
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'trading_bot_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],  # Globale Templates
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# Channels-Konfiguration: Verwende Redis als Channel-Layer-Backend
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("redis://localhost:6379/0")],
        },
    },
}

# Wichtig: ASGI_APPLICATION muss auf die asgi.py in Deinem Projekt verweisen
ASGI_APPLICATION = "trading_bot_project.asgi.application"
WSGI_APPLICATION = "trading_bot_project.wsgi.application"

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'tbot_db',
        'USER': 'tbot',
        'PASSWORD': 'tbot',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
]

LANGUAGE_CODE = 'de-de'
TIME_ZONE = 'Europe/Berlin'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
#STATICFILES_DIRS = [os.path.join(BASE_DIR.parent, 'static')]
#STATIC_ROOT = os.path.join(BASE_DIR.parent, 'staticfiles')

STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"


print(STATIC_URL)
print(STATICFILES_DIRS)
print(STATIC_ROOT)
# Logging-Konfiguration (optional, hier als Beispiel)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'trading_bot.log'),
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'trading': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}
