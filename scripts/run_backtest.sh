#!/bin/sh
set -e
cd "$(dirname "$0")/.."
. backend/.venv/bin/activate
export SIM_CONFIG=${SIM_CONFIG:-./configs/sim_config.yaml}
python - << 'PY'
from sqlalchemy.orm import Session
from backend.app.core.db import SessionLocal
from backend.app.sim.runner import run_backtest

with SessionLocal() as db:
    res = run_backtest(db)
    print(res)
PY
