#!/usr/bin/env bash
# ============================================================================
# docker/load-tuning.sh
#
# Helfer, der in anderen Entrypoint-Skripten gesourct wird, um die von
# hardware-test.sh generierten Tuning-Variablen in die Umgebung zu laden.
# Nutzung:
#   # shellcheck source=docker/load-tuning.sh
#   . /app/docker/load-tuning.sh
# ============================================================================
TUNING_FILE="${TUNING_RUNTIME_DIR:-/tbot-runtime}/tuning.env"
if [[ -r "${TUNING_FILE}" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "${TUNING_FILE}"
  set +a
  echo "[tuning] geladen: ${TUNING_FILE}" >&2
else
  echo "[tuning] keine Tuning-Datei (${TUNING_FILE}) - verwende Compose-Defaults." >&2
fi
