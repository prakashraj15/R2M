#!/usr/bin/env bash
# Supervises the private API (127.0.0.1:8000) and public Next server (0.0.0.0:3000).
# Exits as soon as either child dies; forwards SIGTERM/SIGINT to both.
set -uo pipefail
cd /app

# Idempotent, advisory-locked. The API needs the r2m_app role and RLS policies from the migrations.
python scripts/init_db.py || exit 1

# --no-proxy-headers: uvicorn would otherwise trust X-Forwarded-For from localhost, and Next.js passes the
# client's own (spoofable) value through, letting anyone pick their apparent IP and dodge per-IP limits.
python -m uvicorn r2m_platform.main:app --host 127.0.0.1 --port 8000 --no-server-header --no-proxy-headers &
API=$!
HOSTNAME=0.0.0.0 PORT=3000 node /app/web/server.js &
WEB=$!

trap 'kill -TERM "$API" "$WEB" 2>/dev/null' TERM INT
wait -n "$API" "$WEB"
STATUS=$?
kill -TERM "$API" "$WEB" 2>/dev/null || true
wait
exit "$STATUS"
