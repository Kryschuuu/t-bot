# Lokale Entwicklungsumgebung

## 1. Voraussetzungen

- Docker Engine mit Compose v2
- mindestens 2 GB freier RAM
- freie TCP-Ports 8000 (Web) und interne Docker-Netze

## 2. Konfiguration

```bash
cp .env.docker.example .env
```

Mindestens `SECRET_KEY`, `PASSPHRASE` und `POSTGRES_PASSWORD` in `.env` ändern. Die Datei `.env` ist durch `.gitignore` ausgeschlossen.

## 3. Start

```bash
docker compose up --build -d
```

Services:

| Service | Aufgabe | Grenze |
|---|---|---|
| `web` | Django, Daphne, WebSockets, TradingBot | 512 MB, standardmäßig 0,5 CPU |
| `backtest-worker` | ausschließlich Queue `backtest` | 512-MB-Container, 384-MB-Celery-Child, Concurrency 1 |
| `redis` | Broker/Result Backend | 64 MB, keine Persistenz für lokale Entwicklung |
| `postgres` | lokale persistente DB | 256 MB |
| `scheduler` | optional Celery Beat | nur Profil `scheduler` |

Status prüfen:

```bash
docker compose ps
docker compose logs -f web backtest-worker
curl http://localhost:8000/health/
docker compose exec backtest-worker celery -A trading_bot_project inspect ping --timeout 3
```

Admin anlegen:

```bash
docker compose exec web python manage.py createsuperuser
```

Anwendung: <http://localhost:8000/>

## 4. Render-Free-CPU lokal simulieren

In `.env`:

```env
WEB_CPUS=0.10
WORKER_CPUS=0.50
```

Danach:

```bash
docker compose up -d --force-recreate web backtest-worker
```

Der Worker besitzt weiterhin eigene Ressourcen; der Web-/Bot-Prozess wird künstlich auf 0,1 CPU begrenzt.

## 5. Graceful Degradation testen

### Worker-Ausfall bei erreichbarem Redis

```bash
docker compose stop backtest-worker
```

`/backtesting/` muss `worker-unavailable` anzeigen und neue POSTs ablehnen. Solange Redis erreichbar ist, wird nicht lokal gestartet: Sonst könnte ein bereits eingereihtes Redis-Task später zusätzlich ausgeführt werden.

Worker wieder starten:

```bash
docker compose start backtest-worker
```

Der Status wechselt zu `celery-worker`.

### Redis-Ausfall

```bash
docker compose stop redis
```

Worker ebenfalls stoppen (`docker compose stop backtest-worker`), damit Redis keinen bereits angenommenen Task enthält. Ein neuer Backtest fällt dann lokal zurück. In Produktion (`BACKTEST_LOCAL_FALLBACK_ENABLED=False`) wird derselbe POST verständlich abgelehnt und erzeugt keinen Thread im Bot-Prozess.

### Worker-Crash

```bash
docker compose kill -s KILL backtest-worker
docker compose up -d backtest-worker
```

Daphne und TradingBot müssen durchgehend laufen. `acks_late` und `reject_on_worker_lost` sorgen bei Redis-Betrieb dafür, dass ein nicht bestätigter Task erneut zugestellt werden kann.

## 6. Ressourcen-Validation

```bash
python scripts/backtest_resource_probe.py
```

Akzeptanz:

- Exit-Code 0
- Peak-RSS < 384 MB
- 100 Kandidaten × 5.000 Preispunkte
- Eltern-Heartbeat ungefähr 20 ms und ohne große Ausreißer

Vollständige Studie: [`BACKTESTING_STUDY.md`](BACKTESTING_STUDY.md).

## 7. Optionaler Scheduler

```bash
docker compose --profile scheduler up -d scheduler
```

Celery Beat prüft jede Minute geplante Backtests. Für normale sofortige Backtests ist der Scheduler nicht nötig.

## 8. Debugging

```bash
# Strukturierte Backtest-Events
docker compose logs backtest-worker | grep 'event=backtest'

# Worker-Ressourcen
docker stats t-bot-local-backtest-worker-1 t-bot-local-web-1

# DB-Verbindungen
docker compose exec postgres psql -U tbot -d tbot -c \
  "select application_name, state, count(*) from pg_stat_activity group by 1,2 order by 3 desc;"
```

Der authentifizierte Endpoint `/api/backtesting/status/` liefert Worker-/Redis-Modus sowie Web-Peak-RSS, Threadzahl, Heartbeat-Alter und maximalen Scheduler-Lag.

## 9. Beenden und Zurücksetzen

```bash
docker compose down                 # Datenbank-Volume behalten
docker compose down -v              # lokale Daten vollständig löschen
```

## 10. Produktion auf Render

Render Free besitzt keinen isolierten Background-Worker. Deshalb bleibt `BACKTEST_LOCAL_FALLBACK_ENABLED=False` in Produktion. Für produktives Backtesting:

1. Redis/Render Key Value bereitstellen.
2. Web und Worker dieselbe `REDIS_URL` geben.
3. Bezahlten Worker anhand `render.worker.example.yaml` erstellen.
4. Worker-Queue `backtest`, Concurrency 1 und Memory-Child-Limit prüfen.
5. Optional Beat als separaten Service erstellen.
6. Erst kleinen Test ausführen und `/api/backtesting/status/` beobachten.
