#!/usr/bin/env bash
# ============================================================================
# tests/run_tests.sh - Test-Runner fuer install.sh und hardware-test.sh
#
# Entdeckt alle test_*.sh Dateien im tests/-Verzeichnis, fuehrt sie aus und
# fasst die Ergebnisse zusammen. Beendet mit Exit-Code 1, falls mindestens
# ein Test fehlschlaegt.
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export REPO_ROOT
export TESTS_DIR="${SCRIPT_DIR}"
export FIXTURES_DIR="${SCRIPT_DIR}/fixtures"

# ANSI-Farben (nur wenn stdout ein Terminal ist)
if [[ -t 1 ]]; then
  C_RED=$'\033[0;31m'; C_GREEN=$'\033[0;32m'; C_YELLOW=$'\033[0;33m'
  C_BOLD=$'\033[1m'; C_RESET=$'\033[0m'
else
  C_RED=""; C_GREEN=""; C_YELLOW=""; C_BOLD=""; C_RESET=""
fi

TESTS_RUN=0
TESTS_FAILED=0
FAILED_TESTS=()

run_test_file() {
  local test_file="$1"
  local test_name
  test_name="$(basename "${test_file}" .sh)"
  printf '%s[RUN]%s  %s\n' "${C_BOLD}" "${C_RESET}" "${test_name}"
  TESTS_RUN=$((TESTS_RUN + 1))

  local log
  log="$(mktemp -t tbot-test.XXXXXXXXXX.log)"
  if bash "${test_file}" >"${log}" 2>&1; then
    printf '%s[ OK]%s  %s\n' "${C_GREEN}" "${C_RESET}" "${test_name}"
  else
    printf '%s[FAIL]%s %s\n' "${C_RED}" "${C_RESET}" "${test_name}"
    sed 's/^/       | /' "${log}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    FAILED_TESTS+=("${test_name}")
  fi
  rm -f "${log}"
}

main() {
  local test_file
  local -a test_files=()

  if [[ "$#" -gt 0 ]]; then
    test_files=("$@")
  else
    for test_file in "${SCRIPT_DIR}"/test_*.sh; do
      [[ -e "${test_file}" ]] && test_files+=("${test_file}")
    done
  fi

  if [[ "${#test_files[@]}" -eq 0 ]]; then
    printf 'Keine Tests gefunden.\n' >&2
    exit 1
  fi

  printf '\n%s==> t-bot-lokal Test-Suite <==%s\n\n' "${C_BOLD}" "${C_RESET}"

  for test_file in "${test_files[@]}"; do
    if [[ ! -r "${test_file}" ]]; then
      printf '%s[WARN]%s Testdatei nicht lesbar: %s\n' "${C_YELLOW}" "${C_RESET}" "${test_file}"
      continue
    fi
    run_test_file "${test_file}"
  done

  printf '\n'
  if [[ "${TESTS_FAILED}" -eq 0 ]]; then
    printf '%s%d/%d Tests bestanden.%s\n' "${C_GREEN}" "${TESTS_RUN}" "${TESTS_RUN}" "${C_RESET}"
    exit 0
  else
    printf '%s%d/%d Tests fehlgeschlagen:%s\n' "${C_RED}" "${TESTS_FAILED}" "${TESTS_RUN}" "${C_RESET}"
    local t
    for t in "${FAILED_TESTS[@]}"; do
      printf '  - %s\n' "${t}"
    done
    exit 1
  fi
}

main "$@"
