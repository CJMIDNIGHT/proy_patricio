#!/usr/bin/env bash
# Prueba desde la API que la BBDD responde y que INSERT/SELECT funcionan.
# Uso: ./scripts/probar_db_api.sh [base_url]
# Ejemplo: ./scripts/probar_db_api.sh http://127.0.0.1:5000
#
# Requisitos: MySQL con schema.sql aplicado, .env correcto, API en ejecución
# y ENABLE_DB_SELFTEST=true para el segundo paso.

set -euo pipefail
BASE="${1:-http://127.0.0.1:5000}"

echo "== GET ${BASE}/api/db/health"
curl -sS "${BASE}/api/db/health" | python3 -m json.tool

echo ""
echo "== POST ${BASE}/api/db/selftest"
curl -sS -X POST "${BASE}/api/db/selftest" | python3 -m json.tool
