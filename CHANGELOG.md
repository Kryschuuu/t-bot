# Changelog

Alle relevanten Änderungen dieses Projekts werden hier dokumentiert. Das Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [2.0.1] – 2026-08-20

### Render-Postgres-Verfügbarkeits-Hotfix

- Kurzzeitige `connection refused`-/DNS-Ausfälle liefern im Web statt eines internen 500-Fehlers eine verständliche HTTP-503-Seite beziehungsweise JSON-Antwort mit `Retry-After`.
- Passphrase-/Session-Zugriffe behandeln einen Datenbankausfall explizit; `/health/` bleibt unabhängig erreichbar.
- Bot-Reconnects werden pro Prozess koordiniert, sodass mehrere aktive Bots PostgreSQL nach einem Ausfall nicht gleichzeitig mit parallelen Reconnect-Schleifen belasten.
- Die bereits vorhandenen libpq-Keepalives, Connect-Timeouts und exponentiellen Reconnects bleiben aktiv.

## [2.0.0] – 2026-08-20

### Major-Update: Reporting, Betriebssicherheit und Exchange-UX

#### Hinzugefügt

- Aussagekräftige PDF-Dateinamen im Format `username_exchange_config-id_timestamp.pdf`.
- Downloadbare HTML- und CSV-Trading-Reports mit identischem Namensschema.
- Serverseitige Trading-Log-Pagination mit exakt 100 Einträgen pro Seite.
- Kill-Switch zum sofortigen Schließen aller offenen Paper-Positionen mit frisch abgerufenen Marktpreisen, doppelter Browserbestätigung und serverseitiger Doppelbestätigung.
- Deutliche rote Hervorhebung fehlerhafter Konfigurationsfelder inklusive feldbezogener Fehlermeldungen.
- Bitunix-Integration für öffentliche Spot- und Futures-Marktdaten. Futures-Ticker werden gebündelt abgerufen; bei fehlender/unverfügbarer API wird die Konfiguration sicher abgelehnt und kein Request-Loop gestartet.
- Kontextabhängige Symbol-Autovervollständigung für Exchange sowie Spot/Futures. Vorschläge sind zwischengespeichert und nur beratend; beim Speichern bleibt die Live-Validierung verbindlich.
- `CHANGELOG.md`, `MANUAL.md` und maschinenlesbare `VERSION`.
- Tests für Reportexporte, Pagination, Kill-Switch, Bitunix, Autocomplete und Formularfehler.

#### Geändert

- Dashboard-Aktionsbereich konsolidiert: PDF, HTML, CSV, Kill-Switch und Log-Reset sind klar gruppiert.
- Trading-Log wird neueste-zuerst dargestellt und belastet Browser/Server nicht mehr mit der gesamten Historie.
- Konfigurationsformulare verwenden ein gemeinsames, wartbares Template und Bootstrap-Validierungsstile.
- Symbolkataloge werden für 15 Minuten pro Exchange/Markt gecacht, um API-Last zu begrenzen.

#### Sicherheit

- Alle Exporte, Symbolvorschläge und Kill-Switch-Aufrufe sind authentifiziert und benutzerbezogen autorisiert.
- Kill-Switch und weitere Zustandsänderungen bleiben POST-/CSRF-geschützt.
- Dateinamenbestandteile werden gegen problematische Zeichen bereinigt.
- CSV wird streamend erzeugt und skaliert auch bei großen Logbeständen.

## [1.3.0] – 2026-08-20

### Stabilität von Datenbank und Marktdaten

- Persistenter Binance-`miniTicker`-WebSocket statt REST-Polling; dadurch kein REST-Request-Weight und keine Verlängerung von HTTP-418-Bans.
- Automatische WebSocket-Wiederverbindung mit Backoff, Endpunkt-Fallback und proaktivem 23-Stunden-Reconnect.
- Exakter Binance-`banned until`-Timestamp wird bei HTTP-Fallbackfehlern respektiert.
- BitMart-V3-Marktdatenadapter als Ersatz für den aus CCXT entfernten BitMart-Adapter.
- Live-Symbolvalidierung beim Speichern und Aktivieren einer Konfiguration.
- PostgreSQL-Reconnect mit DNS-Erkennung, Jitter, Keepalive und `wait_for_database` beim Containerstart.
- Erweitertes Fehler-Log mit Schweregrad, Exception-Typ, technischen Details, Filtern, Pagination und Erledigt-Status.

## [1.2.0] – 2026-08-19

### Trading- und Backtesting-Korrekturen

- Gebühren werden beim Kauf und Verkauf korrekt berücksichtigt.
- Verkaufsmenge entspricht der tatsächlich gekauften Menge.
- Offene Paper-Positionen und realisierter P/L werden nach Neustarts aus dem Trading-Log wiederhergestellt.
- Kapital, Equity, Drawdown, Sharpe, Win-Rate, Profit-Faktor und Risk/Reward korrigiert.
- Stop-Loss im Backtesting ergänzt; Verkäufe verwenden den tatsächlichen Kurs statt eines festen Take-Profit-Werts.
- Backtests akzeptieren Decimal-/Float-Schwellenwerte konsistent, begrenzen Kombinationen und speichern nur das beste Ergebnis pro Symbol.
- Pause/Resume/Cancel sowie unterbrochene lokale Tasks stabilisiert.
- Daten- und Fehler-Log-Wachstum begrenzt bzw. dedupliziert.

## [1.1.0] – 2026-08-19

### Render-Deployment

- Docker-Deployment mit unprivilegiertem Benutzer und WeasyPrint-Systembibliotheken.
- Eindeutiges `docker-entrypoint.sh`: Datenbank abwarten, migrieren, Daphne per `exec` starten.
- Render Blueprint mit PostgreSQL, generierten Secrets, Frankfurt-Region und öffentlichem Health-Check.
- WhiteNoise/Manifest-Staticfiles, sichere Proxy-/Cookie-/HSTS-Einstellungen und ASGI-WebSocket-Originprüfung.
- In-Memory-Fallbacks für Channels/Celery auf einer kostenlosen Einzelinstanz.

## [1.0.0] – 2026-08-18

### Initiale Plattform

- Django-Anwendung mit Benutzerregistrierung, Login und Passphrase-Gate.
- Konfigurierbarer Paper-Trading-Bot für mehrere Exchanges und Symbole.
- Dashboard, Trading- und Daten-Logs, Plotly-Charts und PDF-Reports.
- Parametrisierte Backtests mit Fortschritts-WebSocket.
- Technische Strategieindikatoren: DA, NDA, vorherige NDA, DVA/Beschleunigung, DeltaDelta und MVD.

[2.0.0]: https://github.com/Kryschuuu/t-bot/compare/4b38bd9...HEAD
[1.3.0]: https://github.com/Kryschuuu/t-bot/commit/4b38bd9
