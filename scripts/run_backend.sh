#!/bin/sh
set -e
cd "$(dirname "$0")/.."
. backend/.venv/bin/activate
export SIM_CONFIG=${SIM_CONFIG:-./configs/sim_config.yaml}
exec uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
