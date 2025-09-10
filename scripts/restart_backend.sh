#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
"$DIR/stop_backend.sh" || true
nohup bash "$DIR/run_backend.sh" > "$DIR/../backend_server.log" 2>&1 & disown
sleep 2
echo "Backend restarted."


