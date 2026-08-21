#!/usr/bin/env bash
# ============================================================================
# scripts/setup_local.sh - Ein-Schritt-Setup fuer die lokale t-bot-Umgebung
#
# Was das Skript macht:
#   1. Prueft, ob Docker/Compose verfuegbar ist, und bietet optional die
#      Installation ueber install.sh an (--install-deps).
#   2. Fuehrt hardware-test.sh aus, um .env.local mit optimierten Werten
#      fuer Redis, PostgreSQL und die Compose-CPU-Limits zu erzeugen.
#      Bereits vorhandene Secrets (SECRET_KEY, PASSPHRASE, POSTGRES_PASSWORD)
#      bleiben beim Retuning erhalten.
#   3. Legt beim ersten Lauf .env.local an (Mode 0600), schreibt aber nie
#      hartcodierte Credentials.
#   4. Baut die Images und startet den isolierten Stack mit
#      `docker compose up --build -d`.
#
# Nutzung:
#   scripts/setup_local.sh                    # Setup + Start
#   scripts/setup_local.sh --install-deps     # vorher auch Systempakete/ Docker
#   scripts/setup_local.sh --no-up           # nur .env.local erzeugen, nicht starten
#   scripts/setup_local.sh --render-free-simulation
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

ENV_LOCAL="${ENV_LOCAL:-.env.local}"
TUNING_ENV="${TUNING_ENV:-config/hardware.env}"
INSTALL_DEPS=0
DO_UP=1
RENDER_FREE=0

# ANSI-Farben
if [[ -t 1 ]]; then
  C_RED=$'\033[0;31m'; C_GREEN=$'\033[0;32m'; C_YELLOW=$'\033[0;33m'
  C_BOLD=$'\033[1m'; C_RESET=$'\033[0m'
else
  C_RED=""; C_GREEN=""; C_YELLOW=""; C_BOLD=""; C_RESET=""
fi

info()  { printf '%s[setup]%s %s\n' "${C_GREEN}" "${C_RESET}" "$*" >&2; }
warn()  { printf '%s[setup]%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*" >&2; }
error() { printf '%s[setup]%s %s\n' "${C_RED}"  "${C_RESET}" "$*" >&2; }
die()   { error "$*"; exit 1; }

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

parse_args() {
  for arg in "$@"; do
    case "${arg}" in
      --install-deps) INSTALL_DEPS=1 ;;
      --no-up)        DO_UP=0 ;;
      --render-free-simulation|--render-simulation) RENDER_FREE=1 ;;
      -h|--help)      usage ;;
      *) die "Unbekannte Option: ${arg}" ;;
    esac
  done
}

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# 1. Docker/Compose pruefen (optional installieren)
# ---------------------------------------------------------------------------
check_docker() {
  if have docker && docker compose version >/dev/null 2>&1; then
    info "Docker und Compose v2 verfuegbar."
    return 0
  fi

  if [[ "${INSTALL_DEPS}" -eq 1 ]]; then
    warn "Docker/Compose nicht gefunden - starte install.sh (Host-Modus)..."
    ./install.sh --mode=host --profile=full --yes
    have docker || die "Docker war nach der Installation nicht im PATH. Bitte neu einloggen."
  else
    cat >&2 <<EOF
${C_BOLD}Docker Engine mit Compose v2 wird benoetigt.${C_RESET}
- Docker Desktop: https://docs.docker.com/desktop/
- Linux: https://docs.docker.com/engine/install/
Alternativ:
  scripts/setup_local.sh --install-deps   (versucht Systempakete zu installieren)
EOF
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# 2. Hardware-Analyse durchfuehren
# ---------------------------------------------------------------------------
run_hardware_test() {
  info "Starte Hardware-Analyse -> ${TUNING_ENV}"
  mkdir -p "$(dirname "${TUNING_ENV}")"
  ./hardware-test.sh --env-out="${TUNING_ENV}" --format=text >&2
}

# ---------------------------------------------------------------------------
# 3. .env.local zusammenbauen (Secrets werden beibehalten)
# ---------------------------------------------------------------------------
read_existing_secret() {
  local key="$1"
  [[ -f "${ENV_LOCAL}" ]] || return 0
  local val
  val="$(grep -E "^${key}=" "${ENV_LOCAL}" | head -1 | cut -d= -f2- || true)"
  if [[ -n "${val}" ]]; then
    printf '%s' "${val}"
  fi
}

random_secret() {
  head -c 48 /dev/urandom 2>/dev/null | base64 | tr -d '/+=' | head -c 48
}

write_env_local() {
  local secret_key passphrase pg_password web_port
  secret_key="$(read_existing_secret SECRET_KEY)"
  passphrase="$(read_existing_secret PASSPHRASE)"
  pg_password="$(read_existing_secret POSTGRES_PASSWORD)"
  web_port="$(read_existing_secret WEB_PORT)"

  [[ -z "${secret_key}" ]]  && secret_key="$(random_secret)"
  [[ -z "${passphrase}" ]]   && passphrase="local-t-bot"
  [[ -z "${pg_password}" ]]  && pg_password="$(random_secret)"
  [[ -z "${web_port}" ]]     && web_port="8000"

  info "Schreibe ${ENV_LOCAL} (Mode 0600, Secrets werden beibehalten)..."
  umask 077
  {
    echo "# ============================================================================"
    echo "# t-bot-lokal .env.local - automatisch erzeugt von setup_local.sh"
    echo "# Nicht committen. Bereits vorhandene Werte fuer SECRET_KEY, PASSPHRASE und"
    echo "# POSTGRES_PASSWORD wurden beim Retuning beibehalten."
    echo "# ============================================================================"
    echo ""
    echo "SECRET_KEY=${secret_key}"
    echo "PASSPHRASE=${passphrase}"
    echo "PASSPHRASE_GATE_ENABLED=True"
    echo "AUTOSTART_BOTS=True"
    echo ""
    echo "POSTGRES_DB=tbot"
    echo "POSTGRES_USER=tbot"
    echo "POSTGRES_PASSWORD=${pg_password}"
    echo "WEB_PORT=${web_port}"
    echo ""
    echo "# --- Hardware-Tuning (Quelle: ${TUNING_ENV}) ---"
    if [[ -f "${TUNING_ENV}" ]]; then
      grep -vE '^(#|$)' "${TUNING_ENV}"
    fi
    echo ""
    echo "# --- Render-Free-Simulation (default aus) ---"
    if [[ "${RENDER_FREE}" -eq 1 ]]; then
      echo "RENDER=True"
      echo "RENDER_SIMULATION=True"
      echo "WEB_CPUS=0.10"
    else
      echo "RENDER=False"
      echo "RENDER_SIMULATION=False"
    fi
  } > "${ENV_LOCAL}"
  chmod 0600 "${ENV_LOCAL}"
  info "${ENV_LOCAL} geschrieben."
}

# ---------------------------------------------------------------------------
# 4. Stack starten
# ---------------------------------------------------------------------------
start_stack() {
  [[ "${DO_UP}" -eq 1 ]] || { info "--no-up gesetzt - Stack wird nicht gestartet."; return 0; }

  # Compose liest .env automatisch; .env.local muss explizit eingebunden werden.
  info "Lade ${ENV_LOCAL} und starte 'docker compose up --build -d'..."
  set -a
  # shellcheck source=/dev/null
  . "./${ENV_LOCAL}"
  set +a
  docker compose --env-file "${ENV_LOCAL}" up --build -d
  info "Stack gestartet. Health:"
  docker compose ps || true
  info "App: http://localhost:${web_port:-8000}/"
}

main() {
  parse_args "$@"
  check_docker
  run_hardware_test
  write_env_local
  start_stack
}

main "$@"
