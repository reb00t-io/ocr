#!/usr/bin/env bash
set -euo pipefail

: "${PORT:?PORT must be set}"

./scripts/build.sh
docker compose up -d
trap 'docker compose down' EXIT

echo "waiting for server..."
timeout 120 bash -c '
  until curl -sf "http://localhost:'"$PORT"'/health" > /dev/null; do
    sleep 1
  done
'

echo "checking /health..."
body=$(curl -sf "http://localhost:${PORT}/health")
echo "  $body"

if ! echo "$body" | grep -q '"status": *"ok"'; then
  echo "FAIL: /health did not return status=ok"
  echo "$body"
  exit 1
fi

echo "checking deploy date..."
deploy_date=$(echo "$body" | sed -n 's/.*"deployed": *"\([^"]*\)".*/\1/p')
if [ -z "$deploy_date" ] || [ "$deploy_date" = "unknown" ]; then
  echo "FAIL: /health did not include a deployed timestamp"
  exit 1
fi

if deploy_ts=$(date -u -d "$deploy_date" +%s 2>/dev/null); then
  : # GNU date (Linux)
elif deploy_ts=$(date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$deploy_date" +%s 2>/dev/null); then
  : # BSD date (macOS)
else
  echo "FAIL: could not parse deploy date: ${deploy_date}"
  exit 1
fi
now_ts=$(date -u +%s)
age=$(( now_ts - deploy_ts ))

if [ "$age" -gt 300 ]; then
  echo "FAIL: deploy date is ${age}s old (max 300s)"
  exit 1
fi

echo "deploy date is ${age}s old, ok"
echo "e2e test passed"
