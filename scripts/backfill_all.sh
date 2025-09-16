#!/usr/bin/env bash
# Script: Backfill prices and indicators sequentially (background-safe)
# Purpose:
# - Ingest daily bars for ~2 years, then 1-minute bars for ~60 days,
# - THEN compute daily and intraday indicators. Ensures correct order.
# Usage:
#   nohup bash scripts/backfill_all.sh > logs/backfill_all.log 2>&1 & echo $!
# Env:
#   Reads configs/env/.env for DATE, TICKERS (optional), and uses universe fallback.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p logs

# Load env and venv
if [[ -f configs/env/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . configs/env/.env
  set +a
fi

# Activate venv
# shellcheck disable=SC1091
. backend/.venv/bin/activate
export PYTHONPATH="$ROOT_DIR"

echo "[backfill_all] Using DATE=${DATE:-<today>}"

# Determine tickers
if [[ -n "${TICKERS:-}" ]]; then
  TICKS="$TICKERS"
else
  TICKS="$(/usr/bin/env python3 - <<'PY'
from pathlib import Path
p=Path('configs/universe/tickers.txt')
vals=[ln.strip().upper() for ln in p.read_text().splitlines() if ln.strip()] if p.exists() else ["AAPL","MSFT","NVDA","QQQ"]
print(",".join(vals))
PY
)"
fi

echo "[backfill_all] TICKERS=$TICKS"

# Dates (macOS BSD date)
END_DATE="${DATE:-$(date +%F)}"
DAILY_START="$(date -v-2y +%F)"
MINUTE_START="$(date -v-60d +%F)"

echo "[backfill_all] Daily range:   $DAILY_START .. $END_DATE"
echo "[backfill_all] Minute range:  $MINUTE_START .. $END_DATE"

echo "[backfill_all] Testing Alpaca connectivity..."
backend/.venv/bin/python scripts/test_alpaca.py

echo "[backfill_all] Step 1/3: Ingest DAILY bars (sequential)"
# Use IEX feed for historical daily, add small throttle and verbose option via env
ALPACA_FEED=${ALPACA_FEED:-iex} \
INGEST_SLEEP_MS=${INGEST_SLEEP_MS:-200} \
INGEST_VERBOSE=${INGEST_VERBOSE:-0} \
TICKERS="$TICKS" START_DATE="$DAILY_START" END_DATE="$END_DATE" TIMEFRAME=day \
  backend/.venv/bin/python scripts/ingest_alpaca_range.py | tee logs/ingest_daily.log

# Verify daily bars written to DB
echo "[backfill_all] Verify DAILY bars present in DB"
TICKS_ENV="$TICKS" DAILY_START_ENV="$DAILY_START" END_DATE_ENV="$END_DATE" \
backend/.venv/bin/python - <<'PY'
import os
from datetime import datetime
from backend.app.core.db import SessionLocal
from backend.app.models.prices import PriceBar

tickers = [t.strip().upper() for t in os.getenv('TICKS_ENV','').split(',') if t.strip()]
start = datetime.fromisoformat(os.getenv('DAILY_START_ENV')+"T00:00:00")
end = datetime.fromisoformat(os.getenv('END_DATE_ENV')+"T23:59:59")
with SessionLocal() as db:
    q = db.query(PriceBar).filter(PriceBar.timeframe=='day', PriceBar.ts>=start, PriceBar.ts<=end)
    if tickers:
        q = q.filter(PriceBar.ticker.in_(tickers))
    count = q.count()
    print(f"[verify] daily rows={count}")
    if count == 0:
        raise SystemExit("No daily bars found after ingest; aborting")
PY

echo "[backfill_all] Step 2/3: Ingest MINUTE bars (sequential)"
# Add small throttle to avoid 429s; provider path reads ALPACA_FEED (defaults to iex)
INGEST_SLEEP_MS=${INGEST_SLEEP_MS_MINUTE:-300} \
INGEST_VERBOSE=${INGEST_VERBOSE:-0} \
TICKERS="$TICKS" START_DATE="$MINUTE_START" END_DATE="$END_DATE" TIMEFRAME=minute \
  backend/.venv/bin/python scripts/ingest_alpaca_range.py | tee logs/ingest_minute.log

# Verify minute bars written to DB
echo "[backfill_all] Verify MINUTE bars present in DB"
TICKS_ENV="$TICKS" MINUTE_START_ENV="$MINUTE_START" END_DATE_ENV="$END_DATE" \
backend/.venv/bin/python - <<'PY'
import os
from datetime import datetime
from backend.app.core.db import SessionLocal
from backend.app.models.prices import PriceBar

tickers = [t.strip().upper() for t in os.getenv('TICKS_ENV','').split(',') if t.strip()]
start = datetime.fromisoformat(os.getenv('MINUTE_START_ENV')+"T00:00:00")
end = datetime.fromisoformat(os.getenv('END_DATE_ENV')+"T23:59:59")
with SessionLocal() as db:
    q = db.query(PriceBar).filter(PriceBar.timeframe=='min', PriceBar.ts>=start, PriceBar.ts<=end)
    if tickers:
        q = q.filter(PriceBar.ticker.in_(tickers))
    count = q.count()
    print(f"[verify] minute rows={count}")
    if count == 0:
        raise SystemExit("No minute bars found after ingest; aborting")
PY

echo "[backfill_all] Step 3/3: Compute indicators (daily + intraday last 90d)"
TICKERS="$TICKS" START_DATE="$DAILY_START" END_DATE="$END_DATE" \
  backend/.venv/bin/python scripts/backfill_indicators.py | tee logs/backfill_indicators.log

echo "[backfill_all] Done. Logs: logs/ingest_daily.log, logs/ingest_minute.log, logs/backfill_indicators.log"


