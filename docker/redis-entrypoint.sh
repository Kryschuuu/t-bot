#!/usr/bin/env bash
# ============================================================================
# docker/redis-entrypoint.sh
#
# Startet Redis mit den von hardware-test.sh berechneten Parametern aus
# /tbot-runtime/tuning.env (sofern verfuegbar). Andernfalls werden sichere
# Defaults verwendet. Dadurch passt sich der Redis-Container automatisch an
# die verfuegbaren Ressourcen der laufenden Umgebung an.
# ============================================================================
set -euo pipefail

TUNING_FILE="${TUNING_RUNTIME_DIR:-/tbot-runtime}/tuning.env"

# Sichere Defaults (passen zur bisherigen Konfiguration im Compose-File).
REDIS_MAXMEMORY_MB="${REDIS_MAXMEMORY_MB:-48}"
REDIS_MAXMEMORY_POLICY="${REDIS_MAXMEMORY_POLICY:-noeviction}"
REDIS_IO_THREADS="${REDIS_IO_THREADS:-1}"

if [[ -r "${TUNING_FILE}" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "${TUNING_FILE}"
  set +a
  echo "[redis] Tuning-Datei geladen: ${TUNING_FILE}"
else
  echo "[redis] Keine Tuning-Datei gefunden - verwende Defaults."
fi

echo "[redis] maxmemory=${REDIS_MAXMEMORY_MB}mb policy=${REDIS_MAXMEMORY_POLICY} io-threads=${REDIS_IO_THREADS}"

# Konfigurations-Argumente fuer redis-server.
args=(
  --save ""
  --appendonly no
  --maxmemory "${REDIS_MAXMEMORY_MB}mb"
  --maxmemory-policy "${REDIS_MAXMEMORY_POLICY}"
)

# io-threads lohnt sich nur, wenn > 1; ansonsten nicht setzen.
if [[ "${REDIS_IO_THREADS}" =~ ^[0-9]+$ ]] && (( REDIS_IO_THREADS > 1 )); then
  args+=(--io-threads "${REDIS_IO_THREADS}")
fi

exec redis-server "${args[@]}"
