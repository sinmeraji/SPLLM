#!/bin/sh
set -e
cd "$(dirname "$0")/.."
. backend/.venv/bin/activate
# Load env if present
if [ -f configs/env/.env ]; then
  set -a; . configs/env/.env; set +a
fi
export SIM_CONFIG=${SIM_CONFIG:-./configs/sim_config.yaml}
export AUTO_TRADER=${AUTO_TRADER:-0}
exec uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
