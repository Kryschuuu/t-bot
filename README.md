# t-bot

Django-/Channels-Anwendung für **Paper Trading**, Marktvisualisierung und parametrisierte Backtests. Der Bot simuliert Orders; er sendet keine echten Kauf- oder Verkaufsaufträge an eine Börse.

Aktuelle Version: [`VERSION`](VERSION) · Branch: `arena/t-bot-render`

## Schnellstart (Docker Compose, empfohlen)

```bash
# Erkennt lokale Hardware, schreibt .env.local und startet den Stack:
scripts/setup_local.sh

# Auf frischem Linux zusätzlich Distribution/Paketmanager automatisch behandeln:
scripts/setup_local.sh --install-deps
```

Danach: <http://localhost:8000/>. Details in [`docs/LOCAL_DEVELOPMENT.md`](docs/LOCAL_DEVELOPMENT.md).

## Schnellstart ohne Docker

```bash
./install.sh                # automatische Erkennung Host/Container
set -a; . ./config/local.env; set +a
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py runserver
```

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [`docs/README.md`](docs/README.md) | Vollständige Projekt-README (Installation, Hardware-Tuning, QA, Render-Deployment) |
| [`docs/MANUAL.md`](docs/MANUAL.md) | Benutzer- und Indikatorhandbuch (auch in der App unter `/help/`) |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | Versionshistorie (Semantic Versioning) |
| [`docs/ARENA_AI_PROMPTS.md`](docs/ARENA_AI_PROMPTS.md) | Arena-AI-Fix-Historie mit PR-/Commit-Referenzen |
| [`docs/LOCAL_DEVELOPMENT.md`](docs/LOCAL_DEVELOPMENT.md) | Lokale Docker-Entwicklungsumgebung, Tuning, Debugging |
| [`docs/BACKTESTING_STUDY.md`](docs/BACKTESTING_STUDY.md) | Backtesting-Machbarkeitsstudie und Produktionsarchitektur |
| [`docs/PEER_REVIEW.md`](docs/PEER_REVIEW.md) | Selbst-Review Installer/Hardware-Tuning (Shell-Pfad) |
| [`docs/LOCAL_SETUP_PEER_REVIEW.md`](docs/LOCAL_SETUP_PEER_REVIEW.md) | Peer Review lokales Setup (Python-Pfad) |
| [`docs/Peer-Review_Backtesting-chatGPT.md`](docs/Peer-Review_Backtesting-chatGPT.md) | Externes Architektur-Review (Free-Tier-Abgleich) |

## Qualitätssicherung

```bash
bash tests/run_tests.sh   # Shell-Test-Suite (6/6 grün)
python manage.py check
python manage.py test
```
