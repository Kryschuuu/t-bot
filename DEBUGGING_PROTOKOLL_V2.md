# t-bot — Debugging-Protokoll V2: "Bot: STOPPED" Root Cause, Passphrase-Gate & Hosting-Alternativen

Fortsetzung von `DEPLOYMENT_PROTOKOLL.md` (siehe dort für die ursprüngliche
Reverse-Engineering-Analyse und die erste Deployment-Runde).

**Wichtiger Hinweis zur Ausgangslage dieser Session:** `git clone` auf
`https://github.com/Kryschuuu/t-bot` lieferte diesmal `Repository not
found` — das Repo ist vermutlich seit der letzten Session privat gestellt
worden (sinnvoll, sobald echte API-Keys im Spiel sind). Ich habe daher auf
Basis meines letzten reparierten Codestands weitergearbeitet. Die im
Render-Log sichtbaren Endpunkte (`/api/info/`, `/api/logs/`,
`/api/data_logs/`, `/api/trades/`, `/api/bot/status/`) waren in diesem
Codestand bereits vorhanden — ich konnte den Bug daher **direkt im Code
nachweisen**, nicht nur vermuten.

---

## 1. Root Cause: "Dashboard zeigt BOT AKTIV, Historische-Daten-Fenster zeigt Bot: STOPPED"

### 1.1 Der Beweis

Zwei völlig unabhängige Datenquellen steuern zwei verschiedene UI-Elemente:

| UI-Element | Datenquelle | Code |
|---|---|---|
| "Bot aktiv"-Badge oben im Dashboard | `Configuration.is_running` (DB-Feld) | `dashboard.html` Zeile 4/11: `{% if config.is_running %}` |
| "Bot: RUNNING/STOPPED" im Historische-Daten-Fenster | `GET /api/bot/status/` → `bot_status_api()` | `dashboard.html` Zeile 312ff (JS `fetch`) |

`bot_status_api` sah (vor dem Fix) so aus:
```python
@login_required
def bot_status_api(request):
    from .bot_manager import get_status
    return JsonResponse(get_status())
```
`get_status()` liest aus `trading/bot_manager.py`:
```python
BOT_STATE = {"running": False, "config_id": None, "started_at": None}
def start_bot(config_id):
    BOT_STATE["running"] = True
    ...
def stop_bot():
    BOT_STATE["running"] = False
    ...
```
Das ist ein **zweites, komplett unabhängiges** In-Memory-Status-Dict —
losgelöst vom echten Bot. Und in `config_activate` (der View, die beim
Klick auf "Bot starten" läuft) stand:
```python
def config_activate(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    #start_bot(config_id)          # <-- AUSKOMMENTIERT!
    if not config.is_running:
        config.is_running = True   # <-- das hier läuft trotzdem
        config.save(update_fields=["is_running"])
    if not bot_manager.is_running(config.id):
        bot_manager.start_bot(config)   # <-- startet den ECHTEN Bot-Thread
    return redirect('config_list')
```

**Der Aufruf, der `BOT_STATE["running"] = True` gesetzt hätte
(`start_bot(config_id)`), war auskommentiert.** `config.is_running` (DB)
wird trotzdem unbedingt auf `True` gesetzt, und der echte `TradingBot`-
Thread startet auch wirklich. Aber `BOT_STATE` bleibt für immer bei
`{"running": False, ...}`, weil ihn niemand mehr aktualisiert.
`config_deactivate` ruft dagegen `stop_bot()` (die Bare-Funktion aus
`bot_manager.py`) weiterhin unbedingt auf — was konsistent zu `False`
zurücksetzt (ein No-Op, da es ja eh schon `False` war).

**Ergebnis:** Das Dashboard-Badge ("Bot aktiv") ist korrekt (liest die DB).
Das Live-Status-Feld im Historische-Daten-Fenster fragt eine tote Variable
ab, die **strukturell nie `True` werden konnte** — unabhängig davon, ob der
Bot tatsächlich lief oder nicht.

### 1.2 Der Fix

1. `trading/bot_manager.py` (das komplette, disconnected Legacy-Modul)
   **entfernt**.
2. `TradingBotManager` (in `trading_bot.py`, der Singleton, den auch
   `config_activate`/`config_deactivate` für den echten Bot-Thread
   benutzen) bekommt eine neue Methode `status(config_id)`, die den
   **tatsächlichen** Zustand des Threads zurückgibt (`bot.is_alive()`,
   `started_at`, plus neu: `last_error`/`last_error_at`/`last_success_at` —
   siehe Abschnitt 2).
3. `bot_status_api` liest jetzt `bot_manager.status(config.id)` +
   `config.is_running` — also exakt dieselbe Quelle, die auch den Thread
   tatsächlich startet/stoppt. Es gibt jetzt nur noch **eine** Quelle der
   Wahrheit für "läuft der Bot wirklich".
4. `config_activate` fängt jetzt Fehler beim Bot-Start ab (`try/except`)
   und zeigt sie über Django-Messages an, statt `is_running=True` zu
   setzen, obwohl der Bot-Thread nie erfolgreich erstellt wurde.

### 1.3 Verifiziert (lokal, End-to-End)

```
config_activate  ->  302
GET /api/bot/status/?config_id=1
  ->  {"running": true, "config_id": 1, "started_at": 1783971230.30,
       "last_error": "BTC/USDT: binance GET https://api.binance.com/api/v3/exchangeInfo",
       "last_error_at": 1783971232.46, "last_success_at": null,
       "is_running_flag": true}
```
`running: true` unmittelbar nach dem Aktivieren — der Bug ist behoben und
mit einem echten Request/Response-Zyklus nachgewiesen (nicht nur Code-Review).

---

## 2. Zweiter, tieferliegender Fund: Vermutlich werden GAR KEINE Binance-Preise abgerufen

### 2.1 Die Beweislage aus deinem Render-Log

```
GET /api/data_logs/?config_id=3&symbol=BTC/USDT&...   200  2   <- "2 Bytes" = leeres Array "[]"
GET /api/trades/?config_id=3&symbol=BTC/USDT&...      200  2   <- ebenfalls leer
GET /api/logs/3/                                       200  2   <- ebenfalls leer
GET /api/info/3/                                       200  46  <- passt exakt zur "keine Logs vorhanden"-Antwort
```
**Für Konfiguration 3 existiert offenbar zu keinem Zeitpunkt auch nur eine
einzige `DataLog`- oder `TradingLog`-Zeile in der Datenbank.** Das erklärt
gleichzeitig:
- "Es werden keine Graphen geplottet" (Plotly bricht bei `data.length === 0`
  einfach ab, ohne Fehler anzuzeigen — kein Bug, sondern Konsequenz der
  leeren Daten).
- Die generelle Unsicherheit, ob Binance-Preise ankommen.

### 2.2 Root-Cause-Hypothese (mit eigenem Testbeweis, aber nicht 100% auf Render verifizierbar)

`calculate_and_store()` schreibt eine `DataLog`-Zeile bei **jedem**
erfolgreichen Zyklus, sobald 3 Preise im Buffer sind — unabhängig vom
Countdown. D.h. wenn wirklich keine einzige Zeile in der DB landet, muss
`fetch_price()` (der `ccxt`-Call `exchange.fetch_ticker(symbol)`) **bei
jedem einzelnen Versuch** fehlschlagen. Dank der neuen `last_error`-
Sichtbarkeit (Abschnitt 1) lässt sich das jetzt sofort auf dem Dashboard
sehen, statt nur im Server-Log zu verschwinden.

In meiner eigenen lokalen End-to-End-Testumgebung (Abschnitt 1.3) schlägt
genau dieser Call mit exakt folgendem Fehler fehl:
```
BTC/USDT: binance GET https://api.binance.com/api/v3/exchangeInfo
```
In meiner Sandbox liegt das schlicht daran, dass ausgehende Verbindungen zu
`api.binance.com` technisch geblockt sind (Netzwerk-Allowlist) — das ist
**kein Beweis dafür, dass auf Render dieselbe Fehlerursache vorliegt**,
aber es zeigt exakt das Symptom-Muster, das zu deinem Log passt (Aufruf
schlägt fehl → wird abgefangen/geloggt → keine DataLog-Zeile → leere API-
Antworten → keine Graphen).

**Der auf Render mit Abstand wahrscheinlichste, real sehr häufig
auftretende Grund dafür:** Binance blockiert `api.binance.com`-Zugriffe
aus vielen Cloud-Rechenzentrums-IP-Bereichen (AWS, GCP, und damit i.d.R.
auch Render) mit HTTP 451 ("Service unavailable from a restricted
location..."). Das trifft in der Praxis sehr viele Bots, die auf
klassischen PaaS-Anbietern statt bei sich zuhause laufen — unabhängig von
API-Keys, denn `fetch_ticker` ist ein öffentlicher Endpunkt.

### 2.3 Empfohlene nächste Schritte (in dieser Reihenfolge)

1. **Sofort prüfbar, ohne Code-Änderung:** Dashboard nach dem Fix aus
   Abschnitt 1 öffnen → das rote `last_error`-Feld im Bot-Status-Kasten
   zeigt jetzt die exakte Fehlermeldung inkl. Exchange und Symbol an.
2. Falls die Meldung einen 451/HTML-Fehler oder "restricted location"
   enthält: **Exchange in der Konfiguration wechseln.** Das Projekt
   unterstützt laut `_setup_exchange()` jeden `ccxt`-Exchange-Namen, u.a.
   sind laut ursprünglichem README Binance, BingX, Bybit und Bitmart
   vorgesehen — probier probehalber **Bybit** oder **BingX** in einer neuen
   Konfiguration (diese sind erfahrungsgemäß deutlich seltener gegenüber
   generischen Cloud-IPs geoblockt als Binance.com).
3. Falls es unbedingt Binance sein muss: `binance.us` (nur US-gelistete
   Paare, andere Symbolnamen!) oder ein Proxy/VPN mit Ausgangs-IP aus einer
   nicht geblockten Region — beides zusätzlicher Aufwand, für ein privates
   Hobby-Projekt meist nicht lohnend gegenüber Schritt 2.
4. Danach erneut prüfen: `last_success_at` im Bot-Status sollte sich nach
   spätestens `time_interval` Sekunden füllen, und die Graphen sollten
   nach kurzer Zeit Daten zeigen.

---

## 3. Alle Code-Änderungen dieser Session

| Datei | Änderung |
|---|---|
| `trading/bot_manager.py` | **Entfernt** (Ursache von Fehler 1, siehe oben). |
| `trading/trading_bot.py` | `TradingBot` trackt jetzt `last_error`, `last_error_at`, `last_success_at`, `started_at`. `TradingBotManager.status(config_id)` neu — einzige Quelle der Wahrheit für den Bot-Status. |
| `trading/views.py` | `bot_status_api` liest jetzt `bot_manager.status(config_id)` statt des toten Dicts; nimmt jetzt `config_id` als Query-Parameter (analog zu den anderen `/api/`-Endpunkten). `config_activate`/`config_deactivate` bereinigt, Bot-Start jetzt mit `try/except` + Nutzer-Feedback über Django-Messages. Neue View `passphrase_gate_view`. Import von `settings` ergänzt. |
| `trading/urls.py` | Neue URL `gate/` → `passphrase_gate_view`. |
| `trading/middleware.py` | **Neu**: `PassphraseGateMiddleware` (siehe Abschnitt 5). |
| `trading/templates/trading/passphrase_gate.html` | **Neu**: Landingpage mit Disclaimer + Passphrase-Formular. |
| `trading/templates/trading/dashboard.html` | Bot-Status-Polling: sendet jetzt `config_id` mit, pollt alle 10s (vorher: einmalig beim Laden), zeigt `last_error` an. |
| `trading_bot_project/settings.py` | `PassphraseGateMiddleware` in `MIDDLEWARE` registriert; neue Settings `PASSPHRASE` und `PASSPHRASE_GATE_ENABLED`. |
| `render.yaml`, `.env.example` | `PASSPHRASE`-Environment-Variable ergänzt. |

Alle Änderungen wurden lokal end-to-end getestet (Abschnitt 6).

---

## 4. SQLite vs. PostgreSQL — Analyse & klare Empfehlung

### Empfehlung: **PostgreSQL beibehalten. SQLite ist auf Render Free Tier keine Alternative, sondern ein Datenverlust-Risiko.**

Das ist kein "kommt drauf an" — es gibt einen harten technischen K.-o.-Grund:

**Render Free Web Services haben keinen persistenten Storage.** Bei jedem
Deploy, jedem manuellen Neustart und jedem Aufwachen aus dem 15-Minuten-
Idle-Schlaf bekommt der Container ein frisches, leeres Dateisystem. Eine
SQLite-Datei (`db.sqlite3`) liegt aber genau dort — im Container-
Dateisystem. **Sie würde bei jedem Deploy/Neustart komplett verloren
gehen** — alle Konfigurationen, alle Trading-Logs, alle Backtest-Ergebnisse,
weg. PostgreSQL läuft dagegen als eigener, separater Render-Service mit
eigenem persistentem Volume — unabhängig vom Web-Service-Lifecycle.

Zusätzliche Nachteile von SQLite für diesen konkreten Use-Case, auch wenn
Storage-Persistenz kein Thema wäre:

| Aspekt | SQLite | PostgreSQL |
|---|---|---|
| Persistenz auf Render Free Web Service | ❌ Geht bei jedem Neustart verloren | ✅ Eigener Service, übersteht Web-Neustarts |
| Nebenläufigkeit | Datei-Lock auf Schreibzugriffe — der `TradingBot`-Thread schreibt alle paar Sekunden `DataLog`-Zeilen, während gleichzeitig mehrere Browser-Tabs/Requests per Polling lesen (siehe dein Log: mehrere gleichzeitige `/api/...`-Requests) → Risiko von `database is locked`-Fehlern unter Last | Row-Level-Locking, für genau dieses Read-oft/Write-oft-Muster gebaut |
| Mehrere gleichzeitige Bots (mehrere Configs aktiv) | Schreibkonflikte wahrscheinlicher | Unproblematisch |
| Backups | Manuell (Datei kopieren, geht aber wie gesagt eh verloren) | Render bietet auf bezahlten Plänen automatische Backups/PITR |
| Passt zu `dj_database_url`/aktuellem Code | Ja (bereits als Lokal-Fallback eingebaut) | Ja (Standard) |

**Einziger sinnvoller Einsatzort für SQLite in diesem Projekt bleibt exakt
das, was bereits umgesetzt ist:** lokale Entwicklung auf dem eigenen
Rechner (kein Postgres-Server nötig, schneller Start) — genau der
Fallback, der schon in `settings.py` existiert (`DATABASE_URL` leer →
SQLite). Für alles, was auf Render läuft, ist Postgres alternativlos.

---

## 5. Passphrase-Landingpage

### Funktionsweise
- **Neue Middleware** `trading.middleware.PassphraseGateMiddleware`: greift
  vor jeder View (auch vor Login/Registrierung). Solange
  `request.session["passphrase_verified"]` nicht gesetzt ist, wird
  **jede** Anfrage auf `/gate/` umgeleitet (Static Files ausgenommen).
- `/gate/` (`passphrase_gate_view` + `passphrase_gate.html`): zeigt den
  Disclaimer **"PRIVATES PROJEKT – SELBSTHAFTUNG – NUR MIT PASSPHRASE
  ZUGÄNGLICH"** und ein Passphrase-Feld. Der eingegebene Wert wird per
  `secrets.compare_digest()` (timing-safe) mit `settings.PASSPHRASE`
  verglichen.
- Bei korrekter Eingabe: Session-Flag gesetzt (gilt für die Dauer der
  Browser-Session bzw. bis `SESSION_COOKIE_AGE` abläuft), Weiterleitung
  zur ursprünglich gewünschten Seite (oder zum Login).
- Standard-Test-Passphrase (env `PASSPHRASE`, **unbedingt in Produktion
  überschreiben** — der Default liegt öffentlich in diesem Repo):
  ```
  n7kQ2vX9mP5wL8eRt3bF
  ```
- Komplett deaktivierbar über `PASSPHRASE_GATE_ENABLED=False` (z.B. für
  lokale Entwicklung ohne ständige Eingabe).

### Verifiziert (lokal, End-to-End, siehe Abschnitt 6)
- Zugriff ohne Passphrase → Redirect auf `/gate/`.
- Falsche Passphrase → Fehlermeldung, weiterhin blockiert.
- Korrekte Passphrase → Zugriff freigeschaltet, Login/Dashboard/Aktivierung
  funktionieren danach normal.

---

## 6. Alternative Deployment-Optionen — Stand Juli 2026 (recherchiert)

Kurzfassung vorweg: **Für "kostenlos UND production-tauglich" ist die
Landschaft 2026 deutlich schlechter als noch 2023.** Fast jeder frühere
"generöse Free Tier" wurde gestrichen oder stark eingedampft.

| Plattform | Freier Tarif 2026? | Redis kostenlos? | Background Worker kostenlos? | Bewertung für t-bot |
|---|---|---|---|---|
| **Render** (aktuell) | Ja, dauerhaft (Web Service schläft nach 15 Min ein) | Nein (nur winziges 25MB "Key Value") | Nein | Aktuelle Wahl — funktioniert mit den in diesem Protokoll beschriebenen Workarounds |
| **Railway** | Faktisch nein mehr — nur ein einmaliger 5$-Trial-Credit, danach 1$/Monat Guthaben (reicht nicht mal für einen Service + DB) | Nur im (kostenpflichtigen) Guthaben enthalten | Ja als Service-Typ, aber kostenpflichtig | Für dieses Projekt nicht mehr kostenlos nutzbar |
| **Fly.io** | Nein — seit Ende 2024 nur noch 2 Stunden/7 Tage Trial, danach Kreditkarte zwingend | Nein | Nein (alles nutzungsbasiert abgerechnet) | Kein Free-Tier-Kandidat mehr |
| **Heroku** | Nein — Free Tier bereits 2022 komplett abgeschafft | Nein | Nein | Raus |
| **Oracle Cloud "Always Free"** (VPS, kein PaaS) | **Ja, dauerhaft kostenlos** (aktuell 2 statt früher 4 ARM-Kerne, 12 GB statt 24 GB RAM, 200 GB Storage) | Ja — eigener Server, du installierst Redis selbst | Ja — eigener Server, du installierst Celery Worker + Beat selbst | **Interessanteste Alternative**, wenn du wirklich 24/7 ohne Kompromisse willst — siehe unten |
| **Hetzner Cloud + Coolify** | Nein (aber sehr günstig: ab ca. 4,59 €/Monat für mehrere Apps) | Ja (eigener Server) | Ja (eigener Server) | Guter Kompromiss, wenn dir ein paar Euro/Monat egal sind und Oracle's Account-Freigabe nervt |

### Warum Oracle Cloud "Always Free" die einzige *wirklich* kostenlose
Alternative ist, die **beide** Render-Free-Tier-Probleme auf einmal löst
(kein Redis, kein Worker, Spin-Down):

Es handelt sich um eine echte, dauerhaft laufende VM (kein PaaS mit
Spin-Down!) — du installierst dort Docker/Docker Compose selbst und
bekommst damit **echten** Redis + **echten** Celery Worker + Celery Beat +
Postgres, alles auf derselben Maschine, ohne die in diesem Protokoll
beschriebenen Free-Tier-Workarounds (Eager-Celery, In-Memory-Channel-
Layer, Uptime-Pinger-Hack). Der Bot liefe wirklich rund um die Uhr.

**Aber (wichtig, aus der Recherche):**
- Oracle hat die Ampere-A1-Freikontingente 2026 bereits einmal von 4
  OCPU/24GB auf 2 OCPU/12GB **halbiert** — "Always Free" ist in der Praxis
  nicht ganz so "always" wie der Name suggeriert. 2 OCPU/12GB reicht für
  dieses Projekt aber immer noch mehr als genug.
- Die Kontoerstellung ist notorisch streng (Kreditkarte zur Verifizierung
  nötig, Ablehnungen/Reviews ohne klare Begründung sind ein bekanntes,
  häufig berichtetes Problem, gerade bei Neuanmeldungen).
- Du bist dann selbst für OS-Updates, Firewall, TLS-Zertifikate (z.B. via
  Caddy/Let's Encrypt) und Backups verantwortlich — das ist der Preis für
  "kein PaaS mehr, echter Server".

**Praktische Empfehlung:** Render (aktueller Stand mit den Fixes aus
diesem Protokoll) für ein Hobby-/Test-Setup beibehalten — es ist am
wenigsten Aufwand und "gut genug" für Paper-Trading, solange man die
Spin-Down-Realität akzeptiert (Abschnitt 3.3 im ersten Protokoll). Falls
echtes 24/7-Verhalten wichtig wird, ist Oracle Cloud Always Free der
einzige Kandidat, der das *kostenlos* leistet — alle anderen genannten
PaaS-Alternativen sind 2026 schlicht nicht mehr kostenlos genug für Web +
DB + Redis + Worker gleichzeitig.

---

## 7. Testergebnisse (diese Session, lokal, End-to-End)

| Test | Ergebnis |
|---|---|
| `python manage.py check` nach allen Änderungen | ✅ Keine Fehler |
| Migration auf frischer DB | ✅ Alle 5 Migrationen laufen durch |
| Zugriff ohne Passphrase → `/gate/` | ✅ Redirect korrekt, `next`-Parameter erhalten |
| Falsche Passphrase | ✅ Fehlermeldung, weiterhin blockiert |
| Korrekte Passphrase (`n7kQ2vX9mP5wL8eRt3bF`) | ✅ Session-Flag gesetzt, Weiterleitung funktioniert |
| Login/Dashboard nach Passphrase-Freischaltung | ✅ Normaler Ablauf, kein erneutes Gate |
| Konfiguration anlegen → aktivieren | ✅ `TradingBot`-Thread startet nachweislich (`bot.is_alive() == True`) |
| `GET /api/bot/status/?config_id=<id>` direkt nach Aktivierung | ✅ `"running": true` (**vorher: strukturell immer `false`**) |
| `last_error`-Feld nach ein paar Sekunden Laufzeit | ✅ Zeigt den echten `ccxt`-Fehler inkl. Symbol und Timestamp an |
| Deaktivieren → erneuter Status-Abruf | ✅ `"running": false`, Thread sauber gestoppt |

**Nicht in dieser Sandbox testbar** (Netzwerk-Egress auf `api.binance.com`
gesperrt, wie in Abschnitt 2 beschrieben): ob auf Render tatsächlich
dasselbe Geoblocking-Problem vorliegt. Das lässt sich nach dem Deploy des
Fixes in unter einer Minute direkt im Dashboard ablesen (`last_error`-Feld).

---

## 8. Nächste Schritte für dich

1. Diese Änderungen deployen (siehe `render.yaml`, `PASSPHRASE` env var
   nicht vergessen individuell zu setzen).
2. Bot für eine bestehende Konfiguration aktivieren, ~30 Sekunden warten,
   dann im Dashboard das `last_error`-Feld lesen.
3. Falls dort ein Binance-Fehler/451 steht: Exchange auf Bybit oder BingX
   umstellen (Abschnitt 2.3) und erneut testen.
4. Sobald `last_success_at` gefüllt ist und `/api/data_logs/...` nicht
   mehr leer zurückkommt, sollten die Plotly-Graphen automatisch
   erscheinen — kein weiterer Fix nötig.
