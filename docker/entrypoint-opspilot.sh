#!/usr/bin/env bash
# Supervises the private OpsPilot agent API (127.0.0.1:8100) and the public Operations Desk (0.0.0.0:3001).
# Exits as soon as either child dies; forwards SIGTERM/SIGINT to both.
set -uo pipefail
cd /app

python -m uvicorn opspilot_service.app:app --host 127.0.0.1 --port 8100 --no-server-header --no-proxy-headers &
API=$!
HOSTNAME=0.0.0.0 PORT=3001 node /app/web/server.js &
WEB=$!

trap 'kill -TERM "$API" "$WEB" 2>/dev/null' TERM INT
wait -n "$API" "$WEB"
STATUS=$?
kill -TERM "$API" "$WEB" 2>/dev/null || true
wait
exit "$STATUS"
