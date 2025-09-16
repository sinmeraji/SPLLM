#!/usr/bin/env bash
# Script: restart backend services (uvicorn + sqlite-web)
# - Stops running services, purges log files for a clean start, then starts backend.
# Usage: bash scripts/restart_backend.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

# Stop services if running
"$DIR/stop_backend.sh" || true

# Purge log files (keep directory structure)
ROOT="$(cd "$DIR/.." && pwd)"
mkdir -p "$ROOT/logs"
find "$ROOT/logs" -type f \( -name '*.log' -o -name '*.jsonl' \) -delete || true
rm -f "$ROOT/backend_server.log" "$ROOT/logs/backend_server.log" "$ROOT/logs/backend_app.log" || true

# Recreate primary app log so tail -f works immediately after restart
touch "$ROOT/logs/backend_app.log"

# Start backend
nohup bash "$DIR/run_backend.sh" > "$DIR/../backend_server.log" 2>&1 & disown
sleep 2
echo "Backend restarted."


