# t-bot

Django-/Channels-Anwendung für **Paper Trading**, Marktvisualisierung und parametrisierte Backtests. Der Bot simuliert Orders; er sendet keine echten Kauf- oder Verkaufsaufträge an eine Börse.

## Lokal starten

Voraussetzungen: Python 3.12 und die nativen WeasyPrint-Bibliotheken (unter Debian insbesondere Pango/Harfbuzz).

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Werte in .env setzen, dann in die Shell exportieren:
set -a; . ./.env; set +a
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py runserver
```

Django lädt `.env` nicht automatisch. Die Variablen müssen von der Shell, einem Prozessmanager oder einer IDE exportiert werden.

## Qualitätssicherung

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
python manage.py collectstatic --noinput
pip-audit -r requirements.txt   # wenn pip-audit installiert ist
```

## Render-Deployment

`render.yaml` definiert einen Docker-Web-Service und PostgreSQL in Frankfurt. Der Container installiert die für PDF-Reports benötigten Systembibliotheken, führt beim Start Migrationen aus und startet Daphne auf `$PORT`.

1. Branch `arena/01a01bc6-t-bot` zu GitHub pushen.
2. In Render **New → Blueprint** wählen und dieses Repository verbinden.
3. Blueprint anwenden. `SECRET_KEY`, `PASSPHRASE` und `DATABASE_URL` werden automatisch erzeugt/verknüpft.
4. Die erzeugte `PASSPHRASE` unter **t-bot-web → Environment** anzeigen und sicher aufbewahren.
5. Optional über die Render Shell einen Admin anlegen:
   ```bash
   python manage.py createsuperuser
   ```
6. `/health/`, Passphrase-Gate, Registrierung/Login, Dashboard und WebSocket-Fortschritt prüfen.

### Einschränkungen des kostenlosen Render-Plans

- Der Web-Service schläft bei Inaktivität ein. Ein In-Process-Trading-Bot läuft daher **nicht garantiert 24/7**.
- Die kostenlose PostgreSQL-Datenbank läuft nach 30 Tagen ab und muss rechtzeitig ersetzt oder hochgestuft werden.
- Ohne `REDIS_URL` laufen Backtests in einem lokalen Hintergrund-Thread. Das funktioniert mit einer Instanz, überlebt aber keinen Prozessneustart.
- Geplante Backtests benötigen ohne Celery Beat einen externen Aufruf von:
  ```bash
  python manage.py run_scheduled_backtests
  ```
- Für dauerhaften Betrieb sind ein bezahlter Web-Service sowie Redis, Celery Worker und Celery Beat empfohlen.

## Sicherheit

- In Produktion sind `SECRET_KEY` und `PASSPHRASE` Pflichtvariablen.
- Zustandsändernde Endpunkte akzeptieren nur POST und sind CSRF-geschützt.
- Konfigurationen, Logs, Backtests, PDFs und WebSockets sind benutzerbezogen autorisiert.
- API-Schlüssel werden aktuell im Django-Datenbankfeld gespeichert. Für sensible echte Schlüssel sollte vor Nutzung zusätzlich Verschlüsselung auf Feldebene eingerichtet werden.
