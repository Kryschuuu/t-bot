#!/usr/bin/env bash
# ============================================================================
# tests/test_helper.sh - Gemeinsame Funktionen fuer alle Test-Skripte
#
# Wird von test_*.sh gesourct. Stellt Assertions und Temp-Verwaltung bereit.
# ============================================================================

set -u

TESTS_TMPDIR="$(mktemp -d -t tbot-tests.XXXXXXXXXX)"
# shellcheck disable=SC2064
trap 'rm -rf "${TESTS_TMPDIR}"' EXIT

TESTS_RUN=0
TESTS_FAILED=0

pass() {
  printf '  [PASS] %s\n' "$*"
}

fail() {
  printf '  [FAIL] %s\n' "$*" >&2
  TESTS_FAILED=$((TESTS_FAILED + 1))
}

assert_eq() {
  local expected="$1" actual="$2" msg="${3:-Wert ungleich}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "${expected}" == "${actual}" ]]; then
    pass "${msg}"
  else
    fail "${msg}: erwartet='${expected}' tatsaechlich='${actual}'"
  fi
}

assert_not_empty() {
  local value="$1" msg="${2:-Wert ist leer}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -n "${value}" ]]; then
    pass "${msg}"
  else
    fail "${msg}"
  fi
}

assert_match() {
  local pattern="$1" value="$2" msg="${3:-Wert matched nicht}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "${value}" =~ ${pattern} ]]; then
    pass "${msg}"
  else
    fail "${msg}: Muster='${pattern}' Wert='${value}'"
  fi
}

assert_file_exists() {
  local path="$1" msg="${2:-Datei fehlt}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -e "${path}" ]]; then
    pass "${msg} (${path})"
  else
    fail "${msg}: ${path}"
  fi
}

assert_contains() {
  local haystack="$1" needle="$2" msg="${3:-Inhalt nicht gefunden}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "${haystack}" == *"${needle}"* ]]; then
    pass "${msg}"
  else
    fail "${msg}: '${needle}' nicht in Ausgabe"
  fi
}

assert_gt() {
  local a="$1" b="$2" msg="${3:-Nicht groesser}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if (( a > b )); then
    pass "${msg}"
  else
    fail "${msg}: ${a} > ${b}"
  fi
}

assert_between() {
  local value="$1" min="$2" max="$3" msg="${4:-Ausserhalb des Bereichs}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if (( value >= min && value <= max )); then
    pass "${msg} (${value} in [${min},${max}])"
  else
    fail "${msg}: ${value} nicht in [${min},${max}]"
  fi
}

finish_test() {
  if (( TESTS_FAILED > 0 )); then
    printf '\n%d/%d Assertions fehlgeschlagen.\n' "${TESTS_FAILED}" "${TESTS_RUN}" >&2
    exit 1
  fi
  printf '\n  Alle %d Assertions bestanden.\n' "${TESTS_RUN}"
}
