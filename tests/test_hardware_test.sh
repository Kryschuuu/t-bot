#!/usr/bin/env bash
# ============================================================================
# tests/test_hardware_test.sh
#
# Testet die CPU-/RAM-Erkennung, die Heuristik der Empfehlungsberechnung
# und die Generierung der Env-/Berichtsdateien von hardware-test.sh.
# Disk-I/O-Tests werden fuer reproduzierbare Tests gemockt.
# ============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FIXTURES="${FIXTURES_DIR:-${SCRIPT_DIR}/fixtures}"

# shellcheck source=tests/test_helper.sh
. "${SCRIPT_DIR}/test_helper.sh"

# hardware-test.sh als Bibliothek laden.
# shellcheck source=hardware-test.sh
__HARDWARE_TEST_SOURCED=1
. "${REPO_ROOT}/hardware-test.sh"

# ---------------------------------------------------------------------------
# Setup: Mocks
# ---------------------------------------------------------------------------
MOCK_BIN="${FIXTURES}/mock-bin"
chmod +x "${MOCK_BIN}"/* 2>/dev/null || true

# Hardware-Pfade auf Fixtures umlenken.
export HW_MEMINFO="${FIXTURES}/meminfo_4gb"
export HW_CPUINFO="${FIXTURES}/cpuinfo_quad"
export HW_NPROC_CMD="${MOCK_BIN}/nproc"
export HW_UNAME_CMD="${MOCK_BIN}/uname"
# Free wird nicht benoetigt, wenn /proc/meminfo existiert.
export SKIP_DISK_TEST=1
export MOCK_NPROC=4
export MOCK_UNAME_M="x86_64"

# ---------------------------------------------------------------------------
# Test: CPU-Erkennung
# ---------------------------------------------------------------------------
detect_cpu
assert_eq "4"        "${CPU_COUNT}" "CPU-Anzahl erkannt"
assert_eq "x86_64"   "${CPU_ARCH}"  "CPU-Architektur erkannt"
assert_match "Xeon"  "${CPU_MODEL}" "CPU-Modell geparst"
assert_eq "2400"     "${CPU_MHZ}"   "CPU-Takt geparst"

# ---------------------------------------------------------------------------
# Test: RAM-Erkennung
# ---------------------------------------------------------------------------
detect_memory
assert_eq "4096000"  "${RAM_TOTAL_KB}"     "RAM total aus /proc/meminfo"
assert_eq "2048000"  "${RAM_AVAILABLE_KB}" "RAM available aus /proc/meminfo"

# ---------------------------------------------------------------------------
# Test: Empfehlungen fuer 4 GB / 4 Kerne
# ---------------------------------------------------------------------------
compute_recommendations
assert_eq "384000"   "${CELERY_WORKER_MAX_MEMORY_PER_CHILD}" "Celery-Mem bei 4GB"
assert_eq "2"        "${BOT_DB_WORKERS}"   "BOT_DB_WORKERS = nproc/2"
assert_eq "8"        "${DB_POOL_SIZE}"     "DB_POOL_SIZE = workers*4"
assert_eq "2"        "${WEB_CONCURRENCY}"  "WEB_CONCURRENCY bei 4 Kernen"
# >= 4 Kerne -> io-threads=2
assert_eq "2"        "${REDIS_IO_THREADS}" "Redis io-threads = 2 bei 4 Kernen"
assert_eq "noeviction" "${REDIS_MAXMEMORY_POLICY}" "Redis-Policy ist noeviction"
# 10% von 4000 MB (4096000 kB / 1024) = 400 MB
assert_eq "400"      "${REDIS_MAXMEMORY_MB}" "Redis maxmemory = 10% RAM (400 MB)"

# ---------------------------------------------------------------------------
# Test: Empfehlungen fuer 16 GB / 8 Kerne
# ---------------------------------------------------------------------------
HW_MEMINFO="${FIXTURES}/meminfo_16gb"
MOCK_NPROC=8
detect_memory
detect_cpu
compute_recommendations
# 16384000 kB / 1024 = 16000 MB -> >= 8192, aber < 16384 (16 GiB Schwelle) -> 512000
assert_eq "512000"   "${CELERY_WORKER_MAX_MEMORY_PER_CHILD}" "Celery-Mem bei 16 GB"
assert_eq "4"        "${BOT_DB_WORKERS}"   "BOT_DB_WORKERS bei 8 Kernen"
assert_eq "16"       "${DB_POOL_SIZE}"     "DB_POOL_SIZE bei 8 Kernen"
assert_eq "4"        "${WEB_CONCURRENCY}"  "WEB_CONCURRENCY bei 8 Kernen (cap=4)"
assert_eq "4"        "${REDIS_IO_THREADS}" "Redis io-threads bei 8 Kernen (cap=4)"
# 10% von 16000 MB = 1600, wird aber auf 1024 gedeckelt.
assert_eq "1024"     "${REDIS_MAXMEMORY_MB}" "Redis maxmemory bei 16GB gedeckelt"
# Hoehere CPU-Limits
assert_eq "1.00"     "${WEB_CPUS}" "WEB_CPUS bei 8 Kernen"

# ---------------------------------------------------------------------------
# Test: Kleine Maschine (1 GB / 1 Kern)
# ---------------------------------------------------------------------------
cat > "${TESTS_TMPDIR}/meminfo_1gb" <<'EOF'
MemTotal:        1024000 kB
MemFree:          128000 kB
MemAvailable:     512000 kB
EOF
HW_MEMINFO="${TESTS_TMPDIR}/meminfo_1gb"
MOCK_NPROC=1
detect_memory
detect_cpu
compute_recommendations
assert_eq "192000"   "${CELERY_WORKER_MAX_MEMORY_PER_CHILD}" "Celery-Mem bei 1GB"
assert_eq "1"        "${BOT_DB_WORKERS}"   "BOT_DB_WORKERS min=1"
assert_eq "4"        "${DB_POOL_SIZE}"     "DB_POOL_SIZE min=4"
assert_eq "1"        "${WEB_CONCURRENCY}"  "WEB_CONCURRENCY min=1"
assert_eq "1"        "${REDIS_IO_THREADS}" "Redis io-threads min=1"
# Redis darf nicht mehr als die Haelfte des verfuegbaren RAMs belegen.
if (( REDIS_MAXMEMORY_MB <= 256 )); then
  pass "Redis maxmemory bei 1GB begrenzt (${REDIS_MAXMEMORY_MB} MB)"
else
  fail "Redis maxmemory bei 1GB zu hoch (${REDIS_MAXMEMORY_MB} MB)"
fi

# ---------------------------------------------------------------------------
# Test: Env-Datei-Generierung
# ---------------------------------------------------------------------------
ENV_OUT="${TESTS_TMPDIR}/tuning.env"
REPORT_OUT="${TESTS_TMPDIR}/report.txt"
# Mit sinnvollen Werten fuer die Dateiausgabe.
HW_MEMINFO="${FIXTURES}/meminfo_4gb"
MOCK_NPROC=4
detect_cpu; detect_memory; compute_recommendations
render_env > "${ENV_OUT}"
assert_file_exists "${ENV_OUT}" "Env-Datei erzeugt"
if grep -q "^REDIS_MAXMEMORY_MB=" "${ENV_OUT}"; then pass "ENV enthaelt REDIS_MAXMEMORY_MB"; else fail "ENV: REDIS_MAXMEMORY_MB fehlt"; fi
if grep -q "^BOT_DB_WORKERS="     "${ENV_OUT}"; then pass "ENV enthaelt BOT_DB_WORKERS";     else fail "ENV: BOT_DB_WORKERS fehlt"; fi
if grep -q "^CELERY_WORKER_MAX_MEMORY_PER_CHILD=" "${ENV_OUT}"; then pass "ENV enthaelt CELERY_WORKER_MAX_MEMORY_PER_CHILD"; else fail "ENV: CELERY_... fehlt"; fi

# Jede Zeile sollte ein Kommentar, KEY=VALUE oder leer sein.
bad_lines="$(grep -vE '^(#.*|[A-Z0-9_]+=.*|)$' "${ENV_OUT}" || true)"
assert_eq "" "${bad_lines}" "Keine ungueltigen Zeilen im ENV-Format"

# ---------------------------------------------------------------------------
# Test: JSON-Ausgabe ist syntaktisch korrekt (wenn python3 verfuegbar)
# ---------------------------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
  if render_json | python3 -c 'import json,sys; json.load(sys.stdin)'; then
    pass "JSON-Ausgabe valide"
  else
    fail "JSON-Ausgabe ungueltig"
  fi
else
  pass "python3 nicht verfuegbar - JSON-Validierung uebersprungen"
fi

# ---------------------------------------------------------------------------
# Test: Text-Bericht enthaelt alle Sektionen
# ---------------------------------------------------------------------------
report="$(render_text_report)"
assert_contains "${report}" "Hardware-Analyse"     "Bericht: Titel"
assert_contains "${report}" "CPU"                  "Bericht: CPU-Sektion"
assert_contains "${report}" "Speicher"             "Bericht: Speicher-Sektion"
assert_contains "${report}" "Empfohlene Konfiguration" "Bericht: Empfehlungen"

finish_test
