#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

print_command() {
  printf '+ '
  printf '%q ' "$@"
  printf '\n'
}

INSTALL_DEPS=0
NO_START=0
RENDER_SIM=0
WITH_SCHEDULER=0
DRY_RUN=0
ENV_FILE=.env.local
for arg in "$@"; do
  case "$arg" in
    --install-deps) INSTALL_DEPS=1 ;;
    --no-start) NO_START=1 ;;
    --render-free-simulation) RENDER_SIM=1 ;;
    --with-scheduler) WITH_SCHEDULER=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --env-file=*) ENV_FILE=${arg#*=} ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/setup_local.sh [options]
  --install-deps              Force distro package installation
  --no-start                  Tune and build only
  --render-free-simulation    Explicitly cap web to 0.1 CPU (off by default)
  --with-scheduler            Start optional Celery Beat profile
  --dry-run                   Print install/build/start plan without executing Docker
  --env-file=PATH             Generated env file (default .env.local)
EOF
      exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [[ $DRY_RUN -eq 0 ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    INSTALL_DEPS=1
  elif ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
    INSTALL_DEPS=1
  fi
fi
if [[ $INSTALL_DEPS -eq 1 ]]; then
  INSTALL_ARGS=()
  [[ $DRY_RUN -eq 1 ]] && INSTALL_ARGS+=(--dry-run)
  "$ROOT_DIR/scripts/install_system_dependencies.sh" "${INSTALL_ARGS[@]}"
fi

if [[ $DRY_RUN -eq 1 ]]; then
  COMPOSE=(docker compose)
elif ! command -v docker >/dev/null 2>&1; then
  echo "Docker was installed but is not available in this shell. Re-login if the docker group changed." >&2
  exit 1
elif docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose v2 is required." >&2
  exit 1
fi

ARCH=$(uname -m)
case "$ARCH" in
  x86_64|amd64) export DOCKER_DEFAULT_PLATFORM=linux/amd64 ;;
  aarch64|arm64) export DOCKER_DEFAULT_PLATFORM=linux/arm64 ;;
  armv7l|armv7) export DOCKER_DEFAULT_PLATFORM=linux/arm/v7 ;;
  ppc64le) export DOCKER_DEFAULT_PLATFORM=linux/ppc64le ;;
  s390x) export DOCKER_DEFAULT_PLATFORM=linux/s390x ;;
  *) echo "Unsupported container architecture: $ARCH" >&2; exit 1 ;;
esac

TUNER_ARGS=(--output "$ENV_FILE")
[[ $RENDER_SIM -eq 1 ]] && TUNER_ARGS+=(--render-free-simulation)
[[ $DRY_RUN -eq 1 ]] && TUNER_ARGS+=(--print-only)
python3 scripts/tune_local_hardware.py "${TUNER_ARGS[@]}"

echo "Building native image for $DOCKER_DEFAULT_PLATFORM with profile $ENV_FILE"
if [[ $DRY_RUN -eq 1 ]]; then
  print_command "${COMPOSE[@]}" --env-file "$ENV_FILE" build --pull
  if [[ $WITH_SCHEDULER -eq 1 ]]; then PROFILE_ARGS=(--profile scheduler); else PROFILE_ARGS=(); fi
  print_command "${COMPOSE[@]}" --env-file "$ENV_FILE" "${PROFILE_ARGS[@]}" up -d
  printf 'Dry-run complete; Render-Free simulation=%s.\n' "$RENDER_SIM"
  exit 0
fi
"${COMPOSE[@]}" --env-file "$ENV_FILE" build --pull
if [[ $NO_START -eq 1 ]]; then
  echo "Build complete. Start with: ${COMPOSE[*]} --env-file $ENV_FILE up -d"
  exit 0
fi

UP_ARGS=(up -d)
[[ $WITH_SCHEDULER -eq 1 ]] && UP_ARGS=(--profile scheduler up -d)
"${COMPOSE[@]}" --env-file "$ENV_FILE" "${UP_ARGS[@]}"
"${COMPOSE[@]}" --env-file "$ENV_FILE" ps

echo "t-bot local stack is starting at http://localhost:$(grep '^WEB_PORT=' "$ENV_FILE" | cut -d= -f2-)"
