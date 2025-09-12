#!/usr/bin/env bash
#
# Stop all Spllm backend-related processes.
# - Kills uvicorn backend server
# - Kills sqlite-web DB browser
# - Frees ports 8000 (API) and 8081 (DB UI)
#
set -euo pipefail

echo "Stopping uvicorn (backend)..."
pkill -9 -f 'uvicorn .*backend.app.main:app' || true

echo "Stopping sqlite-web (DB browser)..."
pkill -9 -f 'sqlite_web .*backend/app/app.db' || true

echo "Freeing ports (8000, 8081) if any remain..."
for p in 8000 8081; do
  PIDS=$(lsof -ti tcp:$p || true)
  if [ -n "$PIDS" ]; then
    kill -9 $PIDS || true
  fi
done

echo "All backend-related processes signaled to stop."
