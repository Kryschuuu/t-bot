#!/usr/bin/env bash
# ============================================================================
# docker/tuner-entrypoint.sh
#
# Wird beim `docker compose up --build` VOR Redis/Postgres/Web/Worker im
# `tuner`-One-Shot-Container ausgefuehrt. Erkennt die der Umgebung zur
# Verfuegung stehenden CPU/RAM/Disk-Ressourcen, berechnet optimierte
# Parameter und schreibt sie in ein gemeinsam genutztes Volume
# (/tbot-runtime/tuning.env), das alle anderen Container sourcen.
#
# Das Skript ist idempotent und bricht bei Fehlern mit nicht-null Exit-Code
# ab, damit Compose den Start der abhaengigen Services nicht fortsetzt.
# ============================================================================
set -euo pipefail

RUNTIME_DIR="${TUNING_RUNTIME_DIR:-/tbot-runtime}"
ENV_OUT="${RUNTIME_DIR}/tuning.env"
REPORT_OUT="${RUNTIME_DIR}/hardware-report.txt"

mkdir -p "${RUNTIME_DIR}"

echo "[tuner] Starte Hardware-Analyse..."
/app/hardware-test.sh \
  --env-out="${ENV_OUT}" \
  --report-out="${REPORT_OUT}" \
  --format=text

chmod 644 "${ENV_OUT}" "${REPORT_OUT}"
echo "[tuner] Tuning-Datei bereit: ${ENV_OUT}"
echo "[tuner] Empfohlene Werte:"
sed 's/^/[tuner]   /' "${ENV_OUT}"
