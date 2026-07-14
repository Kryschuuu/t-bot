# t-bot — Debugging-Protokoll V3: Thread-Pool-Starvation, Kapital-Anzeige, Performance-Metriken & UI

Fortsetzung von `DEPLOYMENT_PROTOKOLL.md` und `DEBUGGING_PROTOKOLL_V2.md`.

---

## 1. Root Cause: "Bot stoppt immer wieder, vor allem beim Browsen/Plot-Wechsel"

### 1.1 Der Beweis aus deinem Render-Log

```
WARNING  Application instance ... for connection ... uri=/login/ ...       took too long to shut down and was killed.
WARNING  Application instance ... for connection ... uri=/dashboard/?config_id=3 ...  took too long to shut down and was killed.
WARNING  Application instance ... for connection ... uri=/api/bot/status/?config_id=4 ... took too long to shut down and was killed.
INFO     Killed 9 pending application instances
==> Running 'daphne -b 0.0.0.0 -p $PORT trading_bot_project.asgi:application'   <- kompletter Prozess-Neustart
```
Das ist kein "der Bot-Thread stirbt" — das ist der **gesamte Web-Prozess**,
der unter Last hängen bleibt und von Render getötet/neugestartet wird. Da
`TradingBotManager.bots` ein reines In-Memory-Dict ist, sind nach so einem
Neustart **alle laufenden Bots weg** — genau das erklärt "läuft über Nacht
stabil, stoppt aber sobald ich aktiv browse".

### 1.2 Die Ursache

```python
@sync_to_async
def db_get_config(config_id): ...
@sync_to_async
def db_create_datalog_safe(**kwargs): ...
@sync_to_async
def db_create_tradinglog_safe(**kwargs): ...
@sync_to_async
def db_get_recent_deltadelta(symbol, config_id, limit=10): ...
```
`sync_to_async` hat den Default **`thread_sensitive=True`**. Das bedeutet:
**alle** synchronen Django/ORM-Aufrufe im gesamten Prozess — sowohl die der
Bot-Threads (die alle paar Sekunden schreiben) als auch die aller
HTTP-Views (Login, Dashboard, jeder `/api/`-Call) — landen serialisiert auf
**demselben einzigen Thread**. Mit 2 gleichzeitig laufenden Bots plus einem
Nutzer, der aktiv das Dashboard durchklickt (viele parallele Requests:
Seitenaufbau, mehrere `/api/data_logs/`-Polls pro Symbol, Statuscheck...),
staut sich alles auf diesem einen Thread. Ab einer bestimmten Warteschlangen-
länge greift Daphnes eigener Timeout, killt die "hängenden" Application-
Instanzen reihenweise — und Render startet danach den ganzen Prozess neu.

### 1.3 Der Fix

Alle vier DB-Hilfsfunktionen in `trading_bot.py` bekommen jetzt
`thread_sensitive=False`:
```python
@sync_to_async(thread_sensitive=False)
def db_get_config(config_id): ...
```
Damit laufen die DB-Zugriffe der Bot-Threads auf einem **separaten**
Thread-Pool und konkurrieren nicht mehr mit den HTTP-Request-Threads. Das
ist die eigentliche, strukturelle Lösung — kein Workaround.

### 1.4 Workaround zusätzlich zur strukturellen Lösung: Selbstheilung

Da auf Render Free Tier der Prozess *grundsätzlich* jederzeit neu starten
kann (Redeploy, OOM, o.ä.) — auch nach dem Fix aus 1.3 bleibt das
Restrisiko — wurde in `bot_status_api` eine Selbstheilung eingebaut: dieser
Endpoint wird vom Dashboard alle 10 Sekunden gepollt. Findet er eine
Konfiguration mit `is_running=True` in der DB, deren Bot-Thread im
aktuellen Prozess aber nicht (mehr) existiert, wird er automatisch neu
gestartet. Schlägt das fehl, wird `is_running` konsistent auf `False`
zurückgesetzt (siehe auch Abschnitt 3).

```python
if config.is_running and not bot_manager.is_running(config.id):
    try:
        bot_manager.start_bot(config)
    except Exception:
        config.is_running = False
        config.save(update_fields=["is_running"])
```

### 1.5 Verifiziert
Lokaler End-to-End-Test: Konfiguration mit 2 Symbolen aktiviert, Dashboard
mehrfach parallel abgerufen (Login, Dashboard, `/api/info/`, `/api/bot/status/`,
`/errors/`) — alle Requests beantwortet ohne Hänger, kein "took too long"-
Muster mehr reproduzierbar in der lokalen Simulation (natürlich ohne
Render's genaue Speicher-/CPU-Limits 1:1 nachstellen zu können — aber die
strukturelle Ursache, gemeinsamer Thread-Pool, ist eindeutig behoben).

---

## 2. Performance-Metriken & "Kapital ändert sich nicht" — zwei Bugs, ein Fund

### 2.1 Bug A: Kaputter `peak`-Tracking-Code (Backend)

In `info_api` wurde `peak` (das bisherige Kapital-Allzeithoch, Basis für
Max-/Current-Drawdown) **initialisiert, aber nie aktualisiert**:
```python
peak = None
...
if peak is None or peak <= 0:
    drawdown = Decimal("0")
```
`peak` blieb für immer `None` → `max_drawdown`/Risk-Metriken waren
strukturell immer `0`. **Fix:** `peak = max(peak, cap)` wird jetzt bei
jedem Log-Eintrag aktualisiert.

### 2.2 Bug B: `info_api` lieferte gar nicht die Felder, die das Frontend erwartet

Das Dashboard-JS erwartet u.a. `current_capital`, `tank`, `buy_orders`,
`win_rate`, `avg_win`, `risk_reward`, `profit_factor`, `sharpe_ratio`,
`equity_timestamps`/`equity_curve`, ein `metrics`-Objekt usw. — `info_api`
lieferte bisher nur `{"equity": [...], "sharpe": ..., "max_drawdown": ...}`.
**Fix:** `info_api` wurde komplett neu geschrieben und berechnet jetzt alle
genannten Felder direkt aus den `TradingLog`-Einträgen (Win-Rate, Ø
Gewinn/Verlust, Risk/Reward, Profit-Factor, größter Gewinn/Verlust, Sharpe,
Max-/Current-Drawdown, Equity-Kurve in zwei Formaten für beide
Frontend-Konsumenten).

### 2.3 Bug C (der eigentliche Grund für "Kapital bleibt bei 100"): doppelter `.json()`-Aufruf

```js
fetch("{% url 'info_api' config.id %}")
    .then(response => response.json())
    .then(r => r.json())        // <-- BUG: r ist bereits das geparste Objekt, hat keine .json()-Methode!
    .then(data => { ... })
    .catch(error => console.error(...));
```
`response.json()` liefert bereits das fertige JS-Objekt. Der zweite
`.json()`-Aufruf darauf wirft zwangsläufig einen `TypeError`, der von
`.catch()` stillschweigend verschluckt wird. **Das komplette Infofeld
(Kapital, Tank, alle Performance-Metriken) wurde dadurch nach dem initialen
Seitenaufbau nie wieder aktualisiert** — daher "bleibt bei 100", obwohl im
Hintergrund längst Trades passiert sind. **Fix:** doppelten `.json()`-Aufruf
entfernt. Dieser eine Bug war die Hauptursache für zwei deiner gemeldeten
Symptome gleichzeitig (Kapital + Performance-Metriken).

### 2.4 Verifiziert
`GET /api/info/<id>/` liefert jetzt lokal ein vollständiges JSON mit allen
erwarteten Feldern (siehe Testergebnisse, Abschnitt 7). `updateInfoPanel()`
wird jetzt außerdem sofort beim Laden **und** alle 5s aufgerufen (vorher nur
alle 5s, mit dem defekten Code faktisch nie).

---

## 3. "Bot Aktiv" oben vs. "Bot stopped" im Plot — jetzt konsistent & oben zusammengefasst

Die Selbstheilung aus Abschnitt 1.4 sorgt dafür, dass `config.is_running`
(DB) und der tatsächliche Thread-Status jetzt synchron bleiben: läuft der
Bot nicht mehr und lässt sich auch nicht automatisch neu starten, wird
`is_running` serverseitig zurückgesetzt — das obere Badge und der Live-Status
zeigen dann konsistent "gestoppt".

Zusätzlich: **Der Live-Bot-Status (inkl. `last_error`) wurde ganz nach oben
verschoben**, direkt unter das "Bot aktiv"/"Bot inaktiv"-Badge — beide
Anzeigen stehen jetzt zusammen am Seitenanfang, wie gewünscht.

---

## 4. Verbindungslinie zwischen Buy/Sell-Dreiecken

Die Buy/Sell-Trade-Traces selbst hatten bereits `mode: 'markers'` (keine
Linie) — der optische Eindruck einer "Verbindungslinie" kam mit hoher
Wahrscheinlichkeit von der **Preis-Linie**, die bei Datenlücken (z.B.
während ein Trade verarbeitet wird) von Plotly automatisch als gerade
diagonale Linie über die Lücke hinweg gezeichnet wird — und dabei zufällig
nahe an den Buy-/Sell-Dreiecken vorbeiläuft.

**Fix:** Die Preis-Linie bricht jetzt bei Zeitlücken > 3× `time_interval`
(mind. 10s) ab (`null`-Werte an den Lückenstellen, `connectgaps: false`),
statt durchgezogen zu interpolieren. Zusätzlich defensiv `line: {width: 0}`
auf den Buy/Sell-Traces ergänzt.

---

## 5. Trading-Logbuch: Buy/Sell-Paarung visuell erkennbar machen

**Gewählte, einfache Lösung:** FIFO-Zuordnung pro Symbol (der älteste noch
offene Buy eines Symbols wird dem nächsten Sell desselben Symbols
zugeordnet) — implementiert rein im Frontend (`computeTradePairColors()`),
ohne Datenmodell-Änderung. Jedes Buy/Sell-Paar bekommt denselben farbigen
linken Rahmenstreifen in der Tabelle (8 gut unterscheidbare Farben, die
zyklisch wiederverwendet werden). Ein Sell ohne bekannten zugehörigen Buy
(z.B. am Anfang der Historie) bekommt Grau.

*Andere sinnvolle, hier nicht umgesetzte Optionen, falls dir das lieber
ist:* eine `trade_group_id` direkt im `TradingLog`-Modell (müsste vom Bot
beim Ausführen vergeben werden, sauberer aber aufwändiger), oder
eingerückte/verschachtelte Darstellung (Sell-Zeile direkt unter der
zugehörigen Buy-Zeile) statt chronologischer Liste.

---

## 6. Weitere UI-Änderungen

- **Exchange hervorgehoben** + **Countdown**, **Countdown-Reset-Indikatoren**,
  **Time Interval**, **Sales-Stop-Threshold** als Badges direkt unter dem
  Bot-Status, jeweils mit Hover-Tooltip (`title`-Attribut), der erklärt, was
  der Parameter bedeutet.
- **Neue Exception-Log-Seite** (`/errors/`, Link in der Navigation): Ein
  neues Modell `ErrorLog` persistiert jetzt jeden Fehler aus den Bot-Threads
  und aus `config_activate` in der Datenbank — unabhängig von Render's
  kurzlebigen Log-Streams. Zeigt die letzten 300 Fehler über alle eigenen
  Konfigurationen mit Zeitstempel, Konfiguration und Quelle.
- **Reihenfolge geändert:** Infotafeln + Konfigurationsformular → **Plots**
  → **Trading Logbuch** (vorher: Trading Logbuch vor den Plots).

---

## 7. Testergebnisse (diese Session, lokal, End-to-End)

| Test | Ergebnis |
|---|---|
| `python manage.py check` | ✅ Keine Fehler |
| Neue Migration `0006_errorlog` | ✅ Läuft sauber durch |
| Konfiguration (Exchange: Bybit) anlegen + aktivieren | ✅ |
| `GET /dashboard/?config_id=<id>` nach allen Template-Änderungen | ✅ 200, keine Template-Syntaxfehler |
| Reihenfolge-Check (Plots-Marker vor "Trading Logbuch" im HTML) | ✅ Bestätigt (Index-Vergleich im Response-Text) |
| `GET /api/info/<id>/` | ✅ Liefert jetzt alle erwarteten Felder inkl. `metrics`-Objekt |
| `GET /errors/` vor/nach Bot-Laufzeit | ✅ Wächst von 2341 auf 3782 Bytes — Fehler werden live persistiert |
| `GET /api/bot/status/?config_id=<id>` | ✅ `last_error` zeigt konkreten `ccxt`-Fehler (Bybit-Instrumentenabfrage) |
| Mehrere parallele Requests während 2 Bots liefen (Login, Dashboard, Info, Status, Errors) | ✅ Alle beantwortet, kein Hänger reproduzierbar |

**Nicht 1:1 in dieser Sandbox nachstellbar:** Render's exaktes
Speicher-/CPU-Limit unter echter Mehrfach-Bot-Last über Stunden. Die
strukturelle Ursache (gemeinsamer `thread_sensitive`-Pool) ist aber
eindeutig im Code nachgewiesen und behoben, nicht nur vermutet.

---

## 8. Nächste Schritte für dich

1. Deployen, Migration läuft automatisch im Build-Schritt (`render.yaml`
   führt `migrate` weiterhin im `buildCommand` aus).
2. Beide Bots (Bybit, BingX) wie gewohnt aktivieren und aktiv im Dashboard
   browsen/zwischen Symbolen wechseln — der Prozess sollte jetzt nicht mehr
   unter Last kollabieren.
3. Sollte es dennoch nochmal zu einem Neustart kommen (Render Free Tier
   bleibt ressourcenbegrenzt, 512 MB RAM): Der Bot startet jetzt spätestens
   beim nächsten Status-Poll (max. 10s) automatisch von selbst neu — schau
   bei Bedarf in `/errors/` nach, was den Neustart ausgelöst haben könnte.
4. Kapital und Performance-Metriken sollten jetzt live aktualisieren, sobald
   Trades stattfinden.
