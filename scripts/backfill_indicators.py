#!/usr/bin/env python
"""
Script: indicators backfill (daily 2y + intraday 90d)
- Computes and upserts daily and intraday indicators for tickers.
- Phases selectable via CLI flags or env.

Usage examples:
- Env only:
  TICKERS=AAPL,MSFT START_DATE=YYYY-MM-DD END_DATE=YYYY-MM-DD python -u scripts/backfill_indicators.py
- CLI flags (override env):
  python -u scripts/backfill_indicators.py --tickers AAPL,MSFT \
    --start 2024-01-01 --end 2025-09-16 --only-daily
  python -u scripts/backfill_indicators.py --only-intraday

Flags:
- --only-daily / --only-intraday
- --skip-daily / --skip-intraday
"""
from __future__ import annotations

import os
import sys
import argparse
from datetime import date, timedelta

from backend.app.core.db import SessionLocal
from backend.app.services.features import (
    recompute_indicators_for_date,
    recompute_intraday_indicators_last_30d_5m,
)


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Backfill price indicators")
    ap.add_argument("--tickers", type=str, help="Comma-separated tickers (override env TICKERS)")
    ap.add_argument("--start", type=str, help="Start date YYYY-MM-DD (override env START_DATE)")
    ap.add_argument("--end", type=str, help="End date YYYY-MM-DD (override env END_DATE)")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--only-daily", action="store_true", help="Run daily phase only")
    grp.add_argument("--only-intraday", action="store_true", help="Run intraday phase only")
    ap.add_argument("--skip-daily", action="store_true", help="Skip daily phase")
    ap.add_argument("--skip-intraday", action="store_true", help="Skip intraday phase")
    return ap.parse_args()


def _resolve_config() -> tuple[list[str], date, date, bool, bool]:
    args = _parse_args()
    env_tickers = os.getenv("TICKERS", "AAPL,MSFT")
    tickers_str = args.tickers if args.tickers else env_tickers
    tickers = [t.strip().upper() for t in tickers_str.split(",") if t.strip()]
    end_s = args.end if args.end else os.getenv("END_DATE", date.today().isoformat())
    end_d = date.fromisoformat(end_s)
    start_s = args.start if args.start else os.getenv("START_DATE", (date(end_d.year - 2, end_d.month, end_d.day)).isoformat())
    start_d = date.fromisoformat(start_s)
    only_daily = bool(args.only_daily)
    only_intra = bool(args.only_intraday)
    skip_daily = bool(args.skip_daily)
    skip_intra = bool(args.skip_intraday)
    # Normalize flags
    if only_daily:
        skip_intra = True
    if only_intra:
        skip_daily = True
    return tickers, start_d, end_d, skip_daily, skip_intra


def main() -> None:
    tickers, start_d, end_d, skip_daily, skip_intra = _resolve_config()
    with SessionLocal() as db:
        if not skip_daily:
            print(f"START daily start={start_d} end={end_d} tickers={len(tickers)}", flush=True)
            total_daily = 0
            cur = start_d
            while cur <= end_d:
                if cur.weekday() < 5:  # skip weekends
                    for t in tickers:
                        ok = recompute_indicators_for_date(db, ticker=t, d=cur)
                        if ok:
                            total_daily += 1
                            print(f"daily {t} {cur.isoformat()} ok", flush=True)
                        else:
                            print(f"daily {t} {cur.isoformat()} skipped", flush=True)
                cur = date.fromordinal(cur.toordinal() + 1)
            print(f"DONE daily_total={total_daily}", flush=True)

        if not skip_intra:
            print(f"START intraday(5m/30d) as_of={end_d} tickers={len(tickers)}", flush=True)
            total_intra = 0
            for t in tickers:
                print(f"intraday {t} last30d_5m start", flush=True)
                n = recompute_intraday_indicators_last_30d_5m(db, ticker=t, as_of=end_d)
                total_intra += n
                print(f"intraday {t} last30d_5m +{n}", flush=True)
            print(f"DONE intraday_total(5m/30d)={total_intra}", flush=True)


if __name__ == "__main__":
    main()


