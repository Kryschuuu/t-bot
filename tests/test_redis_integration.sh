#!/usr/bin/env bash
# ============================================================================
# tests/test_redis_integration.sh
#
# Testet die Redis-Integrationslogik von install.sh mit gemockten
# redis-cli/systemctl-Befehlen. Prueft:
#   * PING-Wiederholung und Erfolg
#   * Erneuter Start-Versuch bei Fehlschlag
#   * Konfigurationsdatei mit redis-URL
# ============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FIXTURES="${FIXTURES_DIR:-${SCRIPT_DIR}/fixtures}"

# shellcheck source=tests/test_helper.sh
. "${SCRIPT_DIR}/test_helper.sh"

MOCK_BIN="${FIXTURES}/mock-bin"
chmod +x "${MOCK_BIN}"/* 2>/dev/null || true
export PATH="${MOCK_BIN}:${PATH}"
export MOCK_PM_LOG="${TESTS_TMPDIR}/pm.log"
: > "${MOCK_PM_LOG}"

# shellcheck source=install.sh
. "${REPO_ROOT}/install.sh"

INSTALL_LOG="${TESTS_TMPDIR}/install.log"; : > "${INSTALL_LOG}"
CONFIG_DIR="${TESTS_TMPDIR}/config"
CONFIG_FILE="${CONFIG_DIR}/local.env"
ASSUME_YES=1
MODE="host"

# Mock systemctl ist bereits im PATH.
# wait_for_redis soll mit dem mock redis-cli (PONG) sofort erfolgreich sein.
if wait_for_redis "redis://127.0.0.1:6379/0"; then
  pass "wait_for_redis mit PONG erfolgreich"
else
  fail "wait_for_redis mit PONG fehlgeschlagen"
fi

# Stelle sicher, dass bei nicht erreichbarem Redis nach max. 30 Versuchen
# ein Fehler zurueckkommt. Wir ersetzen redis-cli und sleep durch Mocks,
# damit die Schleife nicht 30 Sekunden dauert.
FAIL_DIR="${TESTS_TMPDIR}/failbin"
mkdir -p "${FAIL_DIR}"
cat > "${FAIL_DIR}/redis-cli" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat > "${FAIL_DIR}/sleep" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "${FAIL_DIR}/redis-cli" "${FAIL_DIR}/sleep"
ORIGINAL_PATH="${PATH}"
export PATH="${FAIL_DIR}:${PATH}"

set +e
if wait_for_redis "redis://localhost:6379/0" 2>/dev/null; then
  redis_fail_result="UNEXPECTED_SUCCESS"
else
  redis_fail_result="EXPECTED_FAILURE"
fi
set -e
export PATH="${ORIGINAL_PATH}"

assert_eq "EXPECTED_FAILURE" "${redis_fail_result}" "wait_for_redis schlaegt bei fehlendem PONG fehl"

# ---------------------------------------------------------------------------
# Konfigurationsdatei enthaelt Redis-URL
# ---------------------------------------------------------------------------
write_local_config
assert_file_exists "${CONFIG_FILE}" "lokale Config erzeugt"
if grep -q '^REDIS_URL=redis://127.0.0.1:6379/0' "${CONFIG_FILE}"; then
  pass "REDIS_URL in local.env gesetzt"
else
  fail "REDIS_URL nicht in local.env"
fi

# ---------------------------------------------------------------------------
# Render-Simulation ist standardmaessig deaktiviert
# ---------------------------------------------------------------------------
if grep -qE '^RENDER_SIMULATION=False' "${CONFIG_FILE}"; then
  pass "RENDER_SIMULATION standardmaessig deaktiviert"
else
  fail "RENDER_SIMULATION sollte standardmaessig False sein"
fi
if grep -qE '^RENDER=False' "${CONFIG_FILE}"; then
  pass "RENDER standardmaessig False"
else
  fail "RENDER sollte standardmaessig False sein"
fi

# ---------------------------------------------------------------------------
# Mit --render-simulation ist RENDER_SIMULATION=True
# ---------------------------------------------------------------------------
rm -rf "${CONFIG_DIR}"
RENDER_SIMULATION=1
write_local_config
if grep -qE '^RENDER_SIMULATION=True' "${CONFIG_FILE}"; then
  pass "RENDER_SIMULATION=True bei aktivierter Simulation"
else
  fail "RENDER_SIMULATION sollte True sein"
fi
# RENDER selbst bleibt False (lokales Setup wird nicht beeinflusst)
if grep -qE '^RENDER=False' "${CONFIG_FILE}"; then
  pass "RENDER bleibt False (lokal) trotz aktivierter Simulation"
else
  fail "RENDER sollte lokal False bleiben"
fi

finish_test
