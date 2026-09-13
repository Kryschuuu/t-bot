# Arena-AI-Prompts & Fix-Historie

**Stand:** 8. September 2026 · **Version:** 2.3.2

Diese Datei protokolliert datengesteuert alle von Arena AI (Co-Autor `arena-agent`)
umgesetzten Fixes, Features und Dokumentationsänderungen — mit PR-Nummern,
Commit-Hashes und dem jeweiligen Dokumentationsstatus. Ziel: Jede Änderung aus
der Git-Historie ist genau einer Dokumentationsstelle zugeordnet; Lücken werden
hier explizit als behoben oder als offenes Follow-up markiert.

Pflege-Regel: Jeder neue gemergte PR erhält unten einen Eintrag
(PR-Nummer, Commits, geänderte Docs, offene Punkte).

## Übersicht: Pull Requests

| PR | Titel | Branch | Status | Release | Doku-Status |
|---|---|---|---|---|---|
| #3 | `fix(help)`: Manual-500-Fix, Indikatornamen, Tooltips | `arena/01a02aef-t-bot` | gemergt (`98c9af9`, 22.08.2026) | 2.3.1 | ✅ vollständig (`CHANGELOG.md`, `MANUAL.md`) |
| #2 | v2.3.0-Konsolidierung + Konfliktauflösung | `arena/01a02633-t-bot-lokal` (Fork RG4all) | **geschlossen, nicht gemergt** (21.08.2026) | — | ⚠️ teils: Redis-POSIX-Fix `4ffa267` erst mit 2.3.2 übernommen; Rest bewusst nicht portiert (siehe Follow-ups) |
| #1 | `feat(install)`: Distro-agnostischer Installer + Hardware-Tuning | `arena/01a02633-t-bot-lokal` (Fork RG4all) | gemergt (`94cc67a`, 22.08.2026) | 2.3.0 | ✅ vollständig (`CHANGELOG.md`, `README.md`, `LOCAL_DEVELOPMENT.md`, `PEER_REVIEW.md`) |

## Übersicht: letzte 10 Commits (Stand `98c9af9`)

| # | Commit | Datum | Titel | Doku-Status |
|---|---|---|---|---|
| 1 | `98c9af9` | 22.08.2026 | Merge PR #3 | ✅ via PR-#3-Eintrag |
| 2 | `129344a` | 22.08.2026 | `fix(help)`: Manual-500, Indikatornamen, Tooltips | ✅ `CHANGELOG.md` [2.3.1], `MANUAL.md` Kap. 3/6/13 |
| 3 | `e32b34e` | 22.08.2026 | `move md to docs` | ⚠️ war undokumentiert → mit 2.3.2 nachgetragen (neue Stamm-`README.md`, Link-Reparaturen) |
| 4 | `94cc67a` | 22.08.2026 | Merge PR #1 | ✅ via PR-#1-Eintrag |
| 5 | `ce0ce1c` | 22.08.2026 | Merge `arena/01a01bc6-t-bot` → Feature-Branch | ✅ kein Doku-Bedarf (reiner Vorbereitungs-Merge) |
| 6 | `af4b81e` | 21.08.2026 | `feat(install)`: Installer + Hardware-Tuning (v2.3.0) | ✅ `CHANGELOG.md` [2.3.0] Teil A, `PEER_REVIEW.md` |
| 7 | `67c55a1` | 21.08.2026 | Release v2.3.0 (Python-Pfad: Installer, Tuner) | ✅ `CHANGELOG.md` [2.3.0] Teil B, `LOCAL_SETUP_PEER_REVIEW.md` |
| 8 | `639ed0d` | 21.08.2026 | Release v2.2.0 (isolierter Backtesting-Stack) | ✅ `CHANGELOG.md` [2.2.0], `LOCAL_DEVELOPMENT.md`, `BACKTESTING_STUDY.md` |
| 9 | `0c9ac1e` | 21.08.2026 | `Create foo.txt` (Test-Artefakt) | ✅ kein Doku-Bedarf (in `e32b34e` wieder entfernt) |
| 10 | `0ae96d4` | 21.08.2026 | Peer-Review Backtesting-/24/7-Architektur (ChatGPT) | ✅ Datei `Peer-Review_Backtesting-chatGPT.md` liegt vor; Referenz in Stamm-`README.md` ergänzt |

Ältere Releases (`d3e7835` v2.1.0, `35b104a` v2.0.4, `9b245ce` v2.0.3,
`371fe69` v2.0.2, `aa33e68` v2.0.1, `cfe0cf4` v2.0.0) sind vollständig in
`CHANGELOG.md` abgebildet; die Prüfung am 08.09.2026 ergab dort keine Lücken.

## PR #3 — `fix(help)` (gemergt als `98c9af9`)

**Commit:** `129344a5299cbe30c029a646ec53aeb5b88070d2` · **Release:** 2.3.1

Umgesetzte Fixes/Features und ihre Doku-Abbildung:

1. **`/help/` 500-Fix** — `_render_manual()` in `trading/views.py` prüft
   `docs/MANUAL.md` und `MANUAL.md`, cacht via `@lru_cache(maxsize=1)`.
   → `CHANGELOG.md` [2.3.1], `MANUAL.md` Kap. 13.
2. **Indikatornamen** — `div_DVA_prev_NDA_threshold_buy`,
   `deltadelta_threshold_buy`, `nda_threshold_buy` erhalten sprechende
   `verbose_name`s; Plotly-Traces in `trading/backtesting.py` umbenannt
   (`Beschleunigung (DVA/prev NDA)`, `DeltaDelta (Momentum)`,
   `NDA (% Preisänderung)`).
   → `CHANGELOG.md` [2.3.1], `MANUAL.md` Kap. 3.2/6.
3. **ⓘ-Tooltip-System** — `field.help_text` → `title`-Attribute in
   `trading/forms.py`, `ⓘ`-Spans mit Bootstrap-5-Tooltips in allen
   Formular-Templates (`_configuration_fields.html`, `backtesting_form.html`,
   `analyse.html`, `dashboard.html`, `error_log.html`, `login.html`,
   `register.html`, `passphrase_gate.html`), Tooltip-Init in `base.html`,
   Styling in `static/css/custom.css`.
   → `CHANGELOG.md` [2.3.1], `MANUAL.md` Kap. 2/3/15.
4. **Migration `0012`** — reine Metadaten-Migration
   (`verbose_name`/`help_text`, keine Schemaänderung).
   → mit 2.3.2 im `CHANGELOG.md` [2.3.1] explizit nachgetragen.
5. **Tests** — `trading/tests/test_core.py` (+45 Zeilen: Manual-Rendering,
   Labels, Help-Texte, Backtest-Zuordnung).
   → `CHANGELOG.md` [2.3.1].

Lückenstatus: keine offen.

## PR #1 — `feat(install)` (gemergt als `94cc67a`)

**Commit:** `af4b81e62cf54226fb3f4cd6138a3058148e37eb` · **Release:** 2.3.0 (Teil A)

- `install.sh` (apt/pacman/dnf/yum, Modi auto/host/container, Profile
  full/runtime, Redis-Service-Setup, sudo-Re-Exec).
- `hardware-test.sh` (CPU/RAM/Disk-Heuristik, 64-MB-`dd`-Test, env/json/text).
- Docker-Tuning (`tuner`-Service, `tuning.env`-Volume, `redis-entrypoint.sh`,
  `load-tuning.sh`, `Dockerfile`-Build via `install.sh --mode=container`).
- `config.template`, Test-Suite `tests/` (6 Dateien, 6/6 grün), Smoke-Tests.
- → `CHANGELOG.md` [2.3.0] Teil A, `README.md`, `LOCAL_DEVELOPMENT.md`,
  `PEER_REVIEW.md`.

Bekannter Mangel aus diesem PR (nicht der Doku, sondern des Codes): der
mitgelieferte `docker/redis-entrypoint.sh` war Bash-only und konnte unter
`redis:7.4-alpine` (`/bin/sh`) nicht laufen — behoben mit 2.3.2 (siehe PR #2).

## PR #2 — Konsolidierung (geschlossen, NICHT gemergt)

**Commits:** `bbae53b` (Konsolidierung), `ee45496` (Konflikt-Merge),
`4ffa267` (Redis-POSIX-Fix) · **Release:** keiner (Änderungen lagen nur im Fork-Branch).

Enthaltene Fixes und ihr Verbleib:

| Fix aus PR #2 | Verbleib |
|---|---|
| Redis-Entrypoint POSIX-sh (`4ffa267`) | ✅ mit 2.3.2 portiert (`docker/redis-entrypoint.sh`), verifiziert mit `sh`/`dash`/BusyBox-`ash`; dokumentiert in `CHANGELOG.md` [2.3.2] |
| `docker/postgres-entrypoint.sh` (neu, POSIX) | ❌ nicht portiert — `docker-compose.yml` referenziert keinen Postgres-Entrypoint; Einbau wäre eine Verhaltensänderung → Follow-up |
| zypper/apk-Support in `install.sh`, Arch-Normalisierung, Postgres-Heuristik in `hardware-test.sh` | ❌ nicht portiert — zypper/apk werden bereits von `scripts/install_system_dependencies.sh` abgedeckt, Arch-/Postgres-Tuning von `scripts/tune_local_hardware.py`; Doppelimplementierung vermeiden → Follow-up (bei Bedarf als eigene Version) |
| Konfliktauflösungen in `README.md`/`LOCAL_DEVELOPMENT.md` (löschten Python-Pfad-Doku) | ❌ verworfen — aktueller Stand enthält beide Pfade; stattdessen mit 2.3.2 sauber zusammengeführt |
| Test-Fixtures Alpine/openSUSE, Mock-Binaries apk/zypper | ❌ nicht portiert (gehört zu den nicht portierten Installer-Änderungen) → Follow-up |

## Einzelcommits außerhalb der PRs #1–#3

- **`e32b34e` „move md to docs“** (22.08.2026): Alle `*.md` in `docs/`
  verschoben, `foo.txt` gelöscht. War im Changelog nie erwähnt und brach zwei
  relative Links (`VERSION`, `render.worker.example.yaml`) sowie die
  GitHub-Stammseite (keine `README.md` mehr). → Mit 2.3.2 behoben: neue
  Stamm-`README.md`, Links auf `../…` korrigiert, Umzug im
  `CHANGELOG.md` [2.3.2] nachgetragen.
- **`67c55a1` Release v2.3.0, Python-Pfad** (21.08.2026):
  `scripts/install_system_dependencies.sh` (apt/pacman/dnf/yum/zypper/apk),
  `scripts/tune_local_hardware.py` (CPU-Hashrate, fsync, `.env.local` Mode 0600),
  `scripts/setup_local.sh`, `trading/tests/test_local_setup.py`,
  `LOCAL_SETUP_PEER_REVIEW.md`. → `CHANGELOG.md` [2.3.0] Teil B.
- **`639ed0d` Release v2.2.0** (21.08.2026): Compose-Stack
  (web/backtest-worker/redis/postgres/scheduler), `celery_config.py`
  (Queue `backtest`, Concurrency 1, 384-MB-Limit), `worker_status.py`,
  `/api/backtesting/status/`, strukturierte `event=backtest.*`-Logs.
  → `CHANGELOG.md` [2.2.0], `LOCAL_DEVELOPMENT.md`, `BACKTESTING_STUDY.md`.
- **`0ae96d4` ChatGPT-Peer-Review** (21.08.2026):
  `Peer-Review_Backtesting-chatGPT.md` (Free-Tier-Abgleich Render/Railway/
  Cloud Run/Lambda/Workers/Oracle, Empfehlung lokale Instanz / Oracle Always
  Free). Inhaltlich eigenständiges Review-Dokument ohne Changelog-Eintrag;
  Referenz in der Stamm-`README.md` ergänzt.

## Offene Follow-ups (bewusst nicht in 2.3.2 enthalten)

1. **`docker/postgres-entrypoint.sh` aus PR #2** — nur mit Compose-Verdrahtung
   und Tests übernehmen (eigener PR, Minor-Version).
2. **zypper/apk + Arch-Normalisierung + Postgres-Heuristik für
   `install.sh`/`hardware-test.sh`** — nur übernehmen, wenn der Shell-Pfad
   den Python-Pfad ersetzen soll; aktuell bewusst zwei Pfade.
3. **Alpine-/openSUSE-Fixtures und apk/zypper-Mocks** in `tests/` — gehört zu
   Follow-up 2.
4. **Automatische Übernahme von `DB_POOL_SIZE` in `settings.py`** — bereits in
   `PEER_REVIEW.md` Kap. 7 als Follow-up vermerkt; weiterhin offen.

## Prüfprotokoll 08.09.2026 (Release 2.3.2)

Geprüft: alle 3 PRs (`gh pr list/diff`), letzte 10 Commits
(`98c9af9`…`0ae96d4`, je `git show --stat` und Detail-Diffs),
alle 8 Markdown-Dateien in `docs/`, `VERSION`, alle Versionsnennungen
(`grep 2\.[0-9]+\.[0-9]+`), alle relativen Markdown-Links, Shell-Test-Suite
(`tests/run_tests.sh`, 6/6 grün), Redis-Entrypoint unter
`sh`/`dash`/BusyBox-`ash` mit Mock-`redis-server`.

Gefundene und in 2.3.2 behobene Lücken:

1. Redis-Entrypoint lief unter Alpine nicht (PR-#2-Fix nie gemergt) → portiert.
2. Doppelte `[2.3.0]`-Changelog-Abschnitte → zusammengeführt.
3. Fehlende `docs/ARENA_AI_PROMPTS.md` → erstellt (diese Datei).
4. Fehlende Stamm-`README.md` nach `e32b34e` → erstellt.
5. Zwei defekte relative Links in `docs/README.md` → repariert.
6. Doppelte Service-Tabellenzeilen in `docs/LOCAL_DEVELOPMENT.md` → vereint.
7. Falsche `dd`-Größe (256 MB statt 64 MB) in `docs/PEER_REVIEW.md` → korrigiert.
8. Veralteter Branch `arena/01a01bc6-t-bot` in `docs/README.md` → `arena/t-bot-render`.
9. Unvollständige Installer-Abdeckung in `docs/README.md` (zypper/apk-Pfad
   unerwähnt) → beide Installer präzise zugeordnet.
10. Veraltete Vergleichslinks am Changelog-Ende → alle Versionen verlinkt.
11. Migration `0012` im [2.3.1]-Abschnitt unerwähnt → nachgetragen.
12. Versionsköpfe (`MANUAL.md`, `BACKTESTING_STUDY.md`,
    `LOCAL_SETUP_PEER_REVIEW.md`) → auf 2.3.2 gebracht bzw. bestätigt.
