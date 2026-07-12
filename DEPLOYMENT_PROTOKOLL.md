# t-bot — Reverse-Engineering-, Debugging- und Render-Deployment-Protokoll

Repository: `https://github.com/Kryschuuu/t-bot`
Analysiert, gefixt und lokal end-to-end getestet am 13.07.2026.

---

## 1. Reverse Engineering — Architektur & Dateien

Stack: **Django 5 + Django Channels (WebSocket) + Celery + ccxt (Exchange-API) +
PostgreSQL**, gedacht für Paper-Trading (simulierter Handel ohne echtes Geld,
sofern kein `api_key`/`secret_key` gesetzt ist) mit Backtesting-Funktion.

### 1.1 Einstiegspunkte

| Datei | Rolle |
|---|---|
| `manage.py` | Standard-Django-CLI-Einstiegspunkt (`runserver`, `migrate`, ...). |
| `trading_bot_project/wsgi.py` | WSGI-Einstiegspunkt — **nicht** ausreichend für dieses Projekt, da WebSockets nicht über WSGI laufen können. |
| `trading_bot_project/asgi.py` | ASGI-Einstiegspunkt: routet HTTP an Django, WebSocket-Verbindungen (`AuthMiddlewareStack(URLRouter(...))`) an Channels. **Das ist der Einstiegspunkt, der in Produktion tatsächlich gestartet werden muss** (z.B. via `daphne`), sonst funktioniert der Backtest-Fortschrittsbalken nicht. |
| `ssl_server.py` | Custom-`runserver`-Kommando mit selbstsigniertem SSL-Zertifikat für lokale HTTPS-Tests. Auf Render **nicht relevant/nicht verwendet** — Render terminiert TLS zentral am Edge und reicht unverschlüsseltes HTTP an den Container weiter (mit `X-Forwarded-Proto`-Header). |

### 1.2 Projekt-Konfiguration (`trading_bot_project/`)

| Datei | Rolle |
|---|---|
| `settings.py` | Zentrale Konfiguration: Datenbank, installierte Apps, Middleware, Celery, Channel-Layer, Static Files, Logging. |
| `urls.py` | Root-URLconf, bindet `trading.urls` ein und liefert Static Files aus. |
| `celery.py` | Celery-App-Definition (`app = Celery('trading_bot_project')`), inkl. `beat_schedule` für periodische geplante Backtests. Wird in `__init__.py` importiert, damit `@shared_task` in der ganzen App funktioniert. |
| `routing.py` | WebSocket-URL-Routing: `ws/backtest/<task_id>/` → `BacktestConsumer`. |
| `consumers.py` | **Der tatsächlich verwendete** WebSocket-Consumer (siehe `asgi.py`, der `from .routing import websocket_urlpatterns` und darüber `from . import consumers` in `routing.py` referenziert). |

### 1.3 Trading-App (`trading/`)

| Datei | Rolle |
|---|---|
| `models.py` | `Configuration` (Bot-Konfiguration pro User/Exchange), `TradingLog` (ausgeführte Paper-Trades), `DataLog` (Preis-/Indikator-Historie), `BacktestTask` (Backtest-Job inkl. Status/Progress/Result). |
| `views.py` | Alle HTTP-Views: Auth, Konfigurationsverwaltung, Dashboard, Bot Start/Stop, Backtesting-Formular, PDF-Reports, JSON-APIs für's Frontend. |
| `forms.py` | Django-Forms für Registrierung, Login, Konfiguration, Backtest-Parameter. |
| `urls.py` | App-URLconf (bindet alle Views ein). |
| `trading_bot.py` | **Kernstück des Paper-Trading-Bots**: `TradingBot` (ein `threading.Thread` pro aktiver Konfiguration, holt per `ccxt` Preise von der Exchange, berechnet Indikatoren, simuliert Buy/Sell-Trades) sowie `TradingBotManager`/`bot_manager` (Singleton-Registry aller laufenden Bot-Threads). |
| `bot_manager.py` | **Zweites, unabhängiges** In-Memory-Status-System (`BOT_STATE`-Dict) — historisch parallel zu `trading_bot.py` entstanden, wird nur für eine Status-Abfrage (`bot_status_api`) benutzt. |
| `backtesting.py` | Reine Simulationslogik (`Backtesting.simulate_trading_detailed`) + Plotly-Chart-Erzeugung, unabhängig von Celery/Django. |
| `tasks.py` | Celery-Tasks: `simulate_candidate` (ein Parameter-Kandidat), `collect_results` (Chord-Callback, wählt beste Threshold-Kombination pro Symbol), `run_backtest` (baut den ganzen Parameter-Grid + Chord auf), `schedule_backtests` (periodischer Task für geplante Backtests). |
| `consumers.py` | **Ungenutztes Duplikat** eines `BacktestConsumer` (siehe Fehler #3 unten) — tatsächlich verwendet wird `trading_bot_project/consumers.py`. |
| `apps.py` | `AppConfig.ready()` hängt sich an das `post_migrate`-Signal, um beim Start alle als `is_running=True` markierten Bots automatisch neu zu starten (z.B. nach einem Server-Neustart). |
| `admin.py` | Django-Admin-Registrierung für alle Modelle. |
| `templates/`, `templatetags/` | Frontend (Bootstrap-artige HTML-Templates + eigene Template-Filter). |

### 1.4 Datenfluss (vereinfacht)

```
Browser ──HTTP──▶ views.py ──▶ Configuration (DB)
                              │
                              ▼
              apps.py/config_activate ──▶ bot_manager.start_bot()
                              │
                              ▼
                  TradingBot-Thread (trading_bot.py)
                    ├─ ccxt.fetch_ticker()  (Preis holen)
                    ├─ Indikatoren berechnen ──▶ DataLog (DB)
                    └─ Buy/Sell-Logik simulieren ──▶ TradingLog (DB)

Backtesting:
Browser ──POST──▶ views.backtesting_form ──▶ BacktestTask (DB)
                              │
                              ▼
                  tasks.run_backtest (Celery-Task / Chord)
                    ├─ simulate_candidate × N  (ein Task pro Parameter-Kombi)
                    └─ collect_results (Callback) ──▶ BacktestTask.result

Fortschritt: BacktestTask.update_progress() ──Channels──▶ WebSocket ──▶ Browser
```

### 1.5 Externe Abhängigkeiten / Services

- **PostgreSQL** (Pflicht laut Original-`settings.py`, hart auf `localhost` konfiguriert)
- **Redis** (Pflicht laut Original: Celery-Broker/-Backend **und** Channels-Layer)
- **Crypto-Exchange-API** über `ccxt` (Binance/BingX/Bybit/Bitmart) — für Live-Preise, auch im Paper-Trading-Modus nötig (nur die Order-Ausführung ist simuliert, die Preise sind echt).
- **WeasyPrint** für PDF-Reports (moderne Versionen sind reines Python, benötigen **keine** Cairo/Pango-Systembibliotheken mehr — im Test bestätigt, siehe Abschnitt 3).

---

## 2. Gefundene Fehler & Probleme

### Fehler 1 — `SECRET_KEY` wird bei jedem Prozessstart neu erzeugt
```python
SECRET_KEY = secrets.token_urlsafe(50)
```
**Auswirkung:** Bei jedem Neustart/Deploy (und bei mehreren parallelen Worker-
Prozessen sogar *sofort*, da jeder Prozess einen eigenen Key hätte) werden
alle Sessions und CSRF-Tokens ungültig — Nutzer werden ständig ausgeloggt,
Formulare schlagen mit „CSRF verification failed" fehl.
**Fix:** `SECRET_KEY` aus `os.environ["SECRET_KEY"]`, mit Pflichtprüfung in
Produktion (`RENDER=True`) und stabilem Dummy-Key nur für lokale Entwicklung.

### Fehler 2 — Hart codierte Redis-/Postgres-/Host-Konfiguration
`CELERY_BROKER_URL = 'redis://localhost:6379/0'`, `CHANNEL_LAYERS` → Redis,
`DATABASES` → `localhost`/feste Zugangsdaten, `ALLOWED_HOSTS` per
Socket-Trick (`connect(('10.255.255.255', 1))`, funktioniert in einer
Container-Sandbox wie Render nicht zuverlässig und liefert nicht den
öffentlichen Hostnamen).
**Fix:** Alles über Environment-Variablen (`DATABASE_URL`, `REDIS_URL`,
`RENDER_EXTERNAL_HOSTNAME`, `DJANGO_ALLOWED_HOSTS`), mit sinnvollen
Fallbacks für lokale Entwicklung (SQLite, In-Memory-Channel-Layer).

### Fehler 3 — WebSocket-Gruppenname-Mismatch (Fortschrittsbalken kaputt)
`trading/models.py` (`BacktestTask.update_progress`) sendet an die Gruppe
`f'backtest_progress_{self.id}'` mit `"type": "backtest.progress"`.
Der tatsächlich verwendete Consumer (`trading_bot_project/consumers.py`) trat
aber der Gruppe `f"backtest_{self.task_id}"` bei — **ein anderer Name.**
**Auswirkung:** Der WebSocket verbindet sich erfolgreich, empfängt aber
**niemals** eine Fortschritts-Nachricht — der Progress-Balken im Backtesting-
Formular bewegt sich nie, obwohl der Backtest im Hintergrund korrekt läuft.
**Fix:** Consumer-Gruppenname auf `f"backtest_progress_{self.task_id}"`
angeglichen.

### Fehler 4 — `ws://` hartcodiert im Frontend (Mixed-Content-Block)
```js
const ws = new WebSocket(`ws://${window.location.host}/ws/backtest/{{ task.id }}/`);
```
**Auswirkung:** Funktioniert nur auf `http://`-Seiten. Da Render **immer**
über HTTPS ausliefert, blockiert der Browser diese Verbindung als
„Mixed Content" (unverschlüsseltes WS von einer verschlüsselten Seite aus) —
die Verbindung wird nie aufgebaut.
**Fix:** Protokoll dynamisch wählen (`wss:` wenn `location.protocol === 'https:'`).

### Fehler 5 — Zwei unabhängige, sich widersprechende „Bot-Manager"
- `trading/trading_bot.py` definiert eine Singleton-Instanz `bot_manager`
  (echte `TradingBot`-Threads).
- `trading/bot_manager.py` ist ein komplett separates Modul mit einem reinen
  In-Memory-`BOT_STATE`-Dict (kein Bezug zu echten Threads).
- `trading/apps.py` instanziierte beim automatischen Neustart aktiver Bots
  eine **neue** `TradingBotManager()` statt den Singleton aus `trading_bot.py`
  zu verwenden — dadurch landeten automatisch gestartete Bots in einer
  Registry, die `views.py` (welches den echten Singleton importiert) gar
  nicht kennt. Start/Stop über die UI hätte dann nicht mehr zu den
  tatsächlich laufenden Threads gepasst.
**Fix:** `apps.py` verwendet jetzt konsequent den Singleton aus
`trading_bot.py`. Das redundante `bot_manager.py`-Modul wurde belassen
(wird nur für eine reine Status-Abfrage benutzt), aber nicht weiter
ausgebaut — im Protokoll als bekannte Altlast dokumentiert.

### Fehler 6 — `apps.py` startet Bots auch während `migrate`/`collectstatic`
Das `post_migrate`-Signal feuert bei **jedem** Aufruf von
`python manage.py migrate` — auch während des Render-Build-Schritts, bevor
der eigentliche Server überhaupt läuft. Das hätte während des Builds
`TradingBot`-Threads (mit Exchange-API-Calls) gestartet, die dort weder
sinnvoll laufen noch sauber beendet werden.
**Fix:** Guard über `sys.argv[1]` (überspringt `migrate`,
`collectstatic`, `makemigrations`, `test`, `shell`, ...) sowie neue Einstellung
`AUTOSTART_BOTS` zum kompletten Deaktivieren.

### Fehler 7 — Unbenutzter `django_redis`-Import erzwingt Redis-Kopplung
`views.py` importierte `from django_redis import get_redis_connection`,
ohne die Funktion je aufzurufen. Unnötige harte Abhängigkeit.
**Fix:** Import entfernt.

### Fehler 8 — `plotly.express` importiert, aber `pandas` fehlt
`import plotly.express as px` in `views.py` — `plotly.express` benötigt
zwingend `pandas`, das aber nirgends in einer `requirements.txt` (die im
Repo komplett fehlte) aufgeführt war. **Fix:** `pandas` ergänzt,
`requirements.txt` neu erstellt (siehe Abschnitt 4).

### Fehler 9 — Keine `requirements.txt`, `render.yaml`, `.gitignore` im Repo
Nur eine Liste von `pip install`-Befehlen im PDF-README vorhanden — nicht
reproduzierbar, kein Deployment-Artefakt. **Fix:** siehe Abschnitt 4 & 5.

### Fehler 10 — Doppelte, teils tote `schedule_backtests`-Definition
`views.py` enthält am Dateiende eine **zweite**, mit `@shared_task`
dekorierte Kopie von `schedule_backtests` (identisch zu der in `tasks.py`,
aber nicht über `celery.py`s `beat_schedule` referenziert → toter Code,
nur potenziell verwirrend). Nicht entfernt (kein funktionales Risiko), aber
aus Konsistenzgründen ebenfalls auf `dispatch_task()` umgestellt.

### Struktureller Punkt (kein Bug, aber Render-relevant) — Celery/Channels brauchen auf Free Tier eine andere Architektur
Render Free Tier bietet **weder** einen kostenlosen Redis-/Key-Value-Dienst
in ausreichender Größe für produktiven Einsatz **noch** einen kostenlosen
„Background Worker"- oder „Cron Job"-Service-Typ (nur `Static Site`,
`Web Service`, `Postgres` und ein sehr kleiner `Key Value` (25 MB/50
Connections) unterstützen den Free-Instanztyp). Ein separater
`celery worker`/`celery beat`-Prozess ist auf dem Free Tier somit **nicht
sauber realisierbar**. Details und der gewählte Workaround: Abschnitt 3.2.

---

## 3. Free-Tier-Architektur — Entscheidungen & Workarounds

### 3.1 Kein Redis nötig
- **Channels:** `channels.layers.InMemoryChannelLayer` statt
  `channels_redis`. Funktioniert einwandfrei, **solange nur eine einzige
  Prozess-/Instanz läuft** — was auf dem Free Tier ohnehin der Fall ist
  (kein Autoscaling im Free Plan). Wird später `REDIS_URL` gesetzt (z.B.
  nach einem Upgrade), schaltet `settings.py` automatisch auf den
  Redis-Channel-Layer um.
- **Celery:** Ohne `REDIS_URL` wird `CELERY_TASK_ALWAYS_EAGER = True`
  gesetzt. `task.delay(...)` führt den Task dann **synchron im selben
  Prozess** aus — kein Broker, kein separater Worker nötig. Damit das die
  HTTP-Antwort nicht blockiert (ein Parameter-Grid-Backtest kann durchaus
  mehrere Sekunden dauern), wurde `trading/tasks.py::dispatch_task()`
  eingeführt: Im Eager-Modus wird der Task stattdessen in einem
  Hintergrund-Thread desselben Prozesses gestartet — der Request kommt
  sofort zurück, der Fortschritt kommt weiterhin live per WebSocket rein
  (Fehler 3 ist ja behoben).
  **Bekannte Einschränkung:** Ohne echten Broker funktioniert
  `AsyncResult(...).revoke()` (Pause/Cancel eines laufenden Backtests über
  die UI) nicht mehr zuverlässig — der Thread läuft dann im Hintergrund zu
  Ende. Für einen produktiven, unterbrechbaren Backtest-Betrieb ist ein
  Upgrade auf einen bezahlten Plan mit echtem Redis + Worker nötig (siehe
  auskommentierter Abschnitt in `render.yaml`).

### 3.2 Kein Celery Beat (`schedule_backtests`)
Für **geplante** Backtests (Nutzer setzt eine zukünftige Startzeit) gibt es
auf dem Free Tier keinen laufenden Scheduler-Prozess. Workaround:
`python manage.py run_scheduled_backtests` (neues Management-Command,
ruft `tasks.schedule_backtests()` direkt synchron auf) kann von einem
**externen, kostenlosen Cron-Dienst** (z.B. cron-job.org, UptimeRobot mit
Webhook) regelmäßig gegen einen entsprechend abgesicherten Endpoint/Command
ausgelöst werden. Alternativ: Auf einen bezahlten Plan mit `Cron Job`- oder
`Background Worker`-Service upgraden. Diese Einschränkung ist rein die
geplante Backtest-*Terminierung* betreffend — sofortige Backtests
funktionieren ohne Einschränkung.

### 3.3 Der Paper-Trading-Bot selbst läuft nur, während der Web-Service wach ist
Render Free Web Services werden **nach 15 Minuten ohne eingehenden
Traffic „eingeschläfert"** und brauchen beim nächsten Request 30–60s zum
Aufwachen. Der `TradingBot`-Thread (der kontinuierlich Preise pollt) läuft
nur, während der Prozess aktiv ist — im Schlafzustand pausiert er
zwangsläufig und der Bot verpasst in dieser Zeit Marktbewegungen.
**Für einen wirklich 24/7 laufenden Paper-Trading-Bot gibt es zwei Optionen:**
1. **Empfohlen für echten Dauerbetrieb:** Upgrade auf den `Starter`-Plan
   (ab 7 $/Monat) — keine Idle-Abschaltung mehr.
2. **Free-Tier-Workaround für Demos/Tests:** Einen externen Uptime-Pinger
   (z.B. UptimeRobot, cron-job.org) alle ~10 Minuten gegen die App-URL
   schicken, damit sie nicht einschläft. **Wichtig:** Das ist kein von
   Render offiziell unterstütztes Pattern und Render behält sich vor,
   Free-Instanzen bei „ungewöhnlich hohem" künstlichem Traffic zu
   suspendieren — für einen echten Produktivbetrieb ist Option 1 die
   robuste Lösung.

Diese Einschränkung betrifft **ausschließlich den Free Instance Type** und
ist keine App-seitige Limitierung — sie wurde hier transparent dokumentiert,
damit keine falschen Erwartungen an „kostenloses 24/7 Trading" entstehen.

### 3.4 Postgres statt SQLite/hartcodierter lokaler DB
`DATABASE_URL` (von Render bei verknüpfter Postgres-Instanz automatisch
gesetzt) wird über `dj_database_url` geparst. Lokal ohne `DATABASE_URL`
fällt die App automatisch auf SQLite zurück (kein lokaler Postgres-Server
nötig, um schnell zu entwickeln/zu testen).
**Wichtig:** Render Free Postgres läuft nur 1 GB groß und wird **30 Tage
nach Erstellung automatisch gelöscht** (14 Tage Gnadenfrist zum Upgrade).
Für produktiven Einsatz rechtzeitig auf einen bezahlten Datenbank-Plan
upgraden oder regelmäßige Backups einplanen.

### 3.5 Static Files ohne persistenten Storage
Render Free Web Services haben **keinen persistenten Dateisystem-Storage**
(bei jedem Deploy/Neustart geht alles verloren, was nicht in der DB liegt).
Da Django-Static-Files (`admin`-CSS/JS etc.) aber nur beim Build einmalig
über `collectstatic` erzeugt und danach nur gelesen werden, ist das
unproblematisch — gelöst über **WhiteNoise**
(`whitenoise.middleware.WhiteNoiseMiddleware` +
`CompressedManifestStaticFilesStorage`), das die Static Files direkt aus
dem Python-Prozess ausliefert, ganz ohne Nginx/separaten Static-Server.

### 3.6 WeasyPrint (PDF-Reports)
Ältere WeasyPrint-Versionen benötigten native Cairo-/Pango-Bibliotheken
(auf Render's Python-Buildpack ohne `apt`-Zugriff ein Problem gewesen
wäre). WeasyPrint 63.1 (aktuell in `requirements.txt`) ist **reines
Python** (nutzt `pydyf`, `fonttools`, `Pyphen`, `tinycss2`) und wurde lokal
erfolgreich getestet (siehe Abschnitt 6) — **kein Dockerfile / keine
System-Pakete nötig**, Render's normaler Python-Native-Runtime reicht aus.

---

## 4. Durchgeführte Code-Änderungen (Zusammenfassung)

| Datei | Änderung |
|---|---|
| `trading_bot_project/settings.py` | Komplett auf Environment-Variablen umgestellt: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` (inkl. `RENDER_EXTERNAL_HOSTNAME`), `DATABASE_URL` → Postgres/SQLite-Fallback, `REDIS_URL` → Redis/In-Memory-Fallback für Celery **und** Channels, WhiteNoise für Static Files, Logging nach STDOUT in Produktion, neue Einstellung `AUTOSTART_BOTS`. |
| `trading_bot_project/consumers.py` | WebSocket-Gruppenname an `BacktestTask.update_progress()` angeglichen (Fehler 3). |
| `trading_bot_project/celery.py` | Erklärender Kommentar zum Free-Tier-Verhalten von `beat_schedule` ergänzt. |
| `trading/apps.py` | Singleton-`bot_manager` statt neuer Instanz (Fehler 5), Guard gegen Autostart während `migrate`/`collectstatic` (Fehler 6), neue Einstellung `AUTOSTART_BOTS` respektiert. |
| `trading/views.py` | Unbenutzten `django_redis`-Import entfernt (Fehler 7); `run_backtest.delay(...)` durch `dispatch_task(run_backtest, ...)` ersetzt (2 Stellen + tote Zweit-Definition). |
| `trading/tasks.py` | Neue Helper-Funktion `dispatch_task()` für Broker-freie, nicht-blockierende Hintergrund-Ausführung von Celery-Tasks (Kern des Free-Tier-Workarounds); in `schedule_backtests()` verwendet. |
| `trading/templates/trading/backtesting_form.html` | `ws://` → dynamisch `ws:`/`wss:` je nach Seiten-Protokoll (Fehler 4). |
| `ssl_server.py` | Kommentar ergänzt: nur für lokale HTTPS-Entwicklung, auf Render nicht verwendet. |
| `trading/management/commands/run_scheduled_backtests.py` | **Neu**: Management-Command als Celery-Beat-Ersatz für geplante Backtests (siehe 3.2). |
| `requirements.txt` | **Neu erstellt** (existierte im Repo nicht). |
| `render.yaml` | **Neu**: Render-Blueprint für automatisiertes Free-Tier-Deployment. |
| `.env.example` | **Neu**: Dokumentation aller Environment-Variablen. |
| `.gitignore` | **Neu**: verhindert versehentliches Commiten von `db.sqlite3`, `staticfiles/`, `.env`, `__pycache__/`, `cert/`. |

**Nicht verändert** (bewusst außerhalb des Scopes belassen, da funktional
unabhängig von Redis/Deployment und ohne Fehlverhalten getestet):
`models.py`, `forms.py`, `backtesting.py`, `admin.py`, `trading_bot.py`
(Handelslogik selbst), `urls.py` (beide), `wsgi.py`, `asgi.py`,
Migrations, Templates (außer der WS-URL-Fix), `trading/bot_manager.py`
(Legacy-Modul, siehe Fehler 5 — Nutzung eingeschränkt aber lauffähig
belassen, um bestehende `bot_status_api`-Nutzung nicht zu brechen).

---

## 5. `requirements.txt`

Siehe `requirements.txt` im Projektverzeichnis. Enthält alle tatsächlich
importierten Pakete (per `grep` über alle `.py`-Dateien verifiziert), inkl.
zuvor fehlendem `pandas` (Fehler 8) und `dj-database-url`/`whitenoise` für
das Deployment. Lokal vollständig installiert und getestet (Python 3.12,
siehe Abschnitt 6).

---

## 6. Lokale Tests — Ergebnisse

Durchgeführt in einer isolierten venv (Python 3.12), Datenbank: SQLite
(Postgres-Codepfad ist identisch, nur über `DATABASE_URL` aktiviert; ein
separater Postgres-Server war in der Testumgebung nicht verfügbar/nicht
nötig, da `dj_database_url` denselben Code-Pfad für beide Backends nutzt).

| Test | Ergebnis |
|---|---|
| `pip install -r requirements.txt` | ✅ Alle Pakete installieren sauber, keine Kompilierfehler |
| `python manage.py check` | ✅ „System check identified no issues" |
| `python manage.py migrate` | ✅ Alle 5 Migrationen der `trading`-App + Django-Core-Migrationen laufen durch |
| `python manage.py collectstatic --noinput` | ✅ 132 Dateien gesammelt, WhiteNoise-Post-Processing (Hashing/Kompression) läuft durch |
| Server-Start via `daphne -b 127.0.0.1 -p 8000 trading_bot_project.asgi:application` | ✅ Startet, lauscht auf Port |
| `GET /` | ✅ 302 → `/login/` (nicht eingeloggt) |
| `GET /login/` | ✅ 200, Formular rendert |
| `GET /admin/` | ✅ 302 → Admin-Login |
| `GET /static/admin/css/base.css` | ✅ 200 — WhiteNoise liefert Static Files korrekt aus |
| Login-Flow (`POST /login/` mit Testuser) | ✅ 302 → `/dashboard/`, Session/CSRF funktionieren |
| `GET /dashboard/` (eingeloggt) | ✅ 200 |
| Konfiguration anlegen (`POST /config/`) | ✅ 302 → `/config/list/`, `Configuration`-Objekt in DB angelegt |
| Bot aktivieren (`GET /config/activate/<id>/`) | ✅ 302, `TradingBot`-Thread startet; `ccxt`-Call zur Binance-API schlägt in der Sandbox erwartungsgemäß fehl (kein Internetzugriff auf `api.binance.com` erlaubt) — **wird sauber abgefangen und geloggt, App bleibt stabil** (`try/except` in `main_loop`) |
| Bot deaktivieren (`GET /config/deactivate/<id>/`) | ✅ 302, Thread wird sauber gestoppt |
| Backtesting-Formular (`GET`/`POST /backtesting/<id>/`) | ✅ 200/302; `run_backtest` wird über `dispatch_task()` **ohne Redis/Worker** im Hintergrund-Thread ausgeführt, Celery-Chord (`simulate_candidate` × N + `collect_results`-Callback) läuft vollständig eager durch und aktualisiert `BacktestTask.result` |
| WebSocket-Verbindung `ws://127.0.0.1:8000/ws/backtest/1/` | ✅ Connect/Disconnect erfolgreich (Consumer-Fix aus Fehler 3 verifiziert über Server-Log `WSCONNECT`/`WSDISCONNECT`) |
| `weasyprint.HTML(...).write_pdf()` | ✅ Erzeugt valides PDF (5942 Bytes für einen Testinhalt) — **keine** System-Pakete (Cairo/Pango) nötig |

**Nicht testbar in dieser Sandbox** (Netzwerk-Egress ist auf eine feste
Domain-Allowlist beschränkt, `api.binance.com`/Render selbst sind nicht
erreichbar):
- Echte Preis-Abfragen von einer Exchange (Code-Pfad ist unverändert
  gegenüber dem Original, nur die Fehlerbehandlung darum wurde nicht
  angefasst).
- Das tatsächliche Deployment auf Render selbst (Blueprint wurde nach
  offizieller Render-Dokumentation erstellt, siehe Abschnitt 7, aber nicht
  live gegen Render's API verifiziert).

---

## 7. Deployment-Anleitung (Render, Free Tier)

### Schritt 1 — Repository vorbereiten
Alle Änderungen aus diesem Protokoll committen und pushen (inkl.
`requirements.txt`, `render.yaml`, `.env.example`, `.gitignore`).

### Schritt 2 — Blueprint deployen
1. Render Dashboard → **New** → **Blueprint**.
2. Das GitHub-Repository auswählen (Render liest `render.yaml`
   automatisch ein).
3. Render erstellt automatisch:
   - `t-bot-web` (Web Service, Free, Region Frankfurt)
   - `t-bot-db` (PostgreSQL, Free, 1 GB)
4. `SECRET_KEY` wird von Render automatisch generiert
   (`generateValue: true`), `DATABASE_URL` automatisch aus der verknüpften
   DB gesetzt. **Keine manuellen Secrets nötig für den Minimal-Betrieb.**
5. Deploy bestätigen. Build-Log verfolgen:
   `pip install -r requirements.txt && collectstatic && migrate`.

### Schritt 3 — Environment Variables prüfen/ergänzen (Dashboard → t-bot-web → Environment)

| Variable | Pflicht? | Bedeutung |
|---|---|---|
| `SECRET_KEY` | ✅ (automatisch von Render gesetzt) | Django Secret Key |
| `DEBUG` | nein (Default `False`) | Bei Bedarf temporär `True` für Fehlersuche |
| `DATABASE_URL` | ✅ (automatisch von Render gesetzt) | Postgres-Connection-String |
| `RENDER` | ✅ (in `render.yaml` gesetzt) | Aktiviert Produktions-Validierungen (z.B. Pflicht-`SECRET_KEY`) |
| `AUTOSTART_BOTS` | nein (Default `True`) | `False`, um automatisches Neustarten aktiver Bots beim Prozessstart zu unterbinden |
| `REDIS_URL` | nein | Nur setzen, wenn zusätzlich ein bezahlter Redis-/Key-Value-Dienst + Worker-Service hinzugefügt wurde (siehe auskommentierter Block in `render.yaml`) |
| `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` | nein | Nur bei eigener Domain zusätzlich zur `onrender.com`-URL nötig |

### Schritt 4 — Admin-User anlegen
Render Dashboard → t-bot-web → **Shell** (im Web-Service-Kontext):
```bash
python manage.py createsuperuser
```

### Schritt 5 — App aufrufen & verifizieren
`https://t-bot-web.onrender.com/login/` öffnen (erster Aufruf nach Idle
kann 30–60s dauern, siehe Abschnitt 3.3), einloggen, Konfiguration anlegen,
Backtest starten, Fortschrittsbalken beobachten (WebSocket über `wss://`
läuft jetzt automatisch dank Fehler-4-Fix).

### Schritt 6 (optional) — Bot dauerhaft wach halten / auf Dauerbetrieb upgraden
Siehe Abschnitt 3.3 für die beiden Optionen (Uptime-Pinger vs.
Starter-Plan-Upgrade).

### Schritt 7 (optional) — Auf echten Redis+Worker upgraden
Im auskommentierten Teil von `render.yaml` sind ein `keyvalue`-Service
und zwei `worker`-Services (Celery Worker + Beat) als Referenz hinterlegt.
Nach Aktivierung (Plan ≥ Starter nötig, da `worker`/`keyvalue` keinen
Free-Instanztyp unterstützen) automatisch:
`REDIS_URL` setzen → App schaltet selbstständig von Eager-Fallback auf
verteilte Celery-Ausführung + Redis-Channel-Layer um (kein Code-Fix nötig,
das ist bereits in `settings.py` vorbereitet).

---

## 8. Bekannte, bewusst nicht behobene Limitierungen

1. **Kein echtes 24/7-Trading auf dem Free Tier** ohne externen Uptime-Pinger
   oder Upgrade (Abschnitt 3.3) — technische Grenze der Plattform, kein
   Bug im Code.
2. **Pause/Cancel eines laufenden Backtests** funktioniert im
   Broker-losen Fallback-Modus nicht zuverlässig (Abschnitt 3.1).
3. **Geplante Backtests** brauchen einen externen Cron-Trigger auf dem
   Free Tier (Abschnitt 3.2).
4. `trading/bot_manager.py` (Legacy-Modul) bleibt als Altlast bestehen,
   um `bot_status_api` nicht zu brechen — für eine echte Bereinigung
   müsste dieser Status ebenfalls aus dem `trading_bot.py`-Singleton
   abgeleitet werden (nicht im aktuellen Scope, da rein kosmetisch/keine
   funktionale Auswirkung auf Paper-Trading oder Deployment).
5. Free Render Postgres läuft nach 30 Tagen ab (Abschnitt 3.4) — für
   Langzeitbetrieb rechtzeitig upgraden.
