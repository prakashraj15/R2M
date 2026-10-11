#!/usr/bin/env bash
# Supervises the private API (127.0.0.1:8000) and public Next server (0.0.0.0:3000).
# Exits as soon as either child dies; forwards SIGTERM/SIGINT to both.
set -uo pipefail
cd /app

python -m uvicorn r2m_platform.main:app --host 127.0.0.1 --port 8000 --no-server-header &
API=$!
HOSTNAME=0.0.0.0 PORT=3000 node /app/web/server.js &
WEB=$!

trap 'kill -TERM "$API" "$WEB" 2>/dev/null' TERM INT
wait -n "$API" "$WEB"
STATUS=$?
kill -TERM "$API" "$WEB" 2>/dev/null || true
wait
exit "$STATUS"
