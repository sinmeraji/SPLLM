#!/usr/bin/env bash
#
# Stop any running backend processes, then start backend API and sqlite-web.
# Prints health and DB UI URL.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

# Stop existing processes
"$DIR/scripts/stop_backend.sh" || true

# Activate venv
. "$DIR/backend/.venv/bin/activate"

# Load env if present
if [ -f "$DIR/configs/env/.env" ]; then
  set -a; . "$DIR/configs/env/.env"; set +a
fi

export PYTHONPATH="$DIR"
export SIM_CONFIG=${SIM_CONFIG:-./configs/sim_config.yaml}

mkdir -p "$DIR/logs"

echo "Starting backend (uvicorn)..."
nohup uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload > "$DIR/logs/backend_server.log" 2>&1 &
BACK_PID=$!
echo "Backend PID: $BACK_PID"
echo $BACK_PID > /tmp/spllm_backend.pid

echo "Starting sqlite-web..."
nohup "$DIR/backend/.venv/bin/sqlite_web" "$DIR/backend/app/app.db" --host 127.0.0.1 --port 8081 > "$DIR/logs/sqlite_web.log" 2>&1 &
SQL_PID=$!
echo "SQLite-web PID: $SQL_PID"
echo $SQL_PID > /tmp/spllm_sqlite.pid

sleep 1
echo "Health: $(curl -s http://127.0.0.1:8000/health || echo failed)"
echo "API:   http://127.0.0.1:8000/"
echo "UI:    http://127.0.0.1:8000/app/"
echo "DB UI: http://127.0.0.1:8081/"
