#!/usr/bin/env python
"""
Script: Backfill missing or sparse daily/minute price gaps only.
Purpose:
- Detects business days per ticker for:
  * Daily bars over ~2 years (up to yesterday)
  * Minute bars over last 60 days (up to today)
- Ingests missing days and RE-INGESTS SPARSE minute days using a threshold.
  Threshold defaults to:
    - MINUTE_MIN_ROWS env (1-minute bars), else
    - VERIFY_MINUTE_DENSITY*5 if set (assuming VERIFY is 5-min), else 300.

Env (optional):
- DATE: ISO date (YYYY-MM-DD). Defaults to today (ET)
- TICKERS: override list (comma-separated). Defaults to universe file
- SLEEP_MS: throttle between provider calls (default 200)
- MINUTE_MIN_ROWS: minimum expected 1-minute bars per trading day (default 300)
- DRY_RUN: 1 to only report gaps without ingesting

Exit code:
- 0 on success, 1 if ingestion encountered errors
"""
from __future__ import annotations

from pathlib import Path
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import os
import time
from typing import List, Dict, Set, Tuple

from dotenv import load_dotenv

import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.db import SessionLocal
from backend.app.models.prices import PriceBar
from backend.app.services.prices_ingest import ingest_provider_bars


ET = ZoneInfo("America/New_York")


def load_env() -> None:
    envp = ROOT / "configs" / "env" / ".env"
    if envp.exists():
        load_dotenv(dotenv_path=str(envp), override=False)


def business_days(start_d: date, end_d: date) -> List[date]:
    out: List[date] = []
    cur = start_d
    while cur <= end_d:
        if cur.weekday() < 5:
            out.append(cur)
        cur = date.fromordinal(cur.toordinal() + 1)
    return out


def resolve_tickers() -> List[str]:
    override = os.getenv("TICKERS")
    if override:
        arr = [t.strip().upper() for t in override.split(",") if t.strip()]
        if arr:
            return arr
    fp = ROOT / "configs" / "universe" / "tickers.txt"
    if fp.exists():
        arr = [ln.strip().upper() for ln in fp.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith('#')]
        if arr:
            return arr
    return ["AAPL", "MSFT", "NVDA", "QQQ"]


def main() -> None:
    load_env()
    tickers = resolve_tickers()
    end = os.getenv("DATE")
    end_d = date.fromisoformat(end) if end else datetime.now(tz=ET).date()
    sleep_ms = int(os.getenv("SLEEP_MS", "200") or 0)
    dry_run = os.getenv("DRY_RUN", "0") == "1"
    # Determine minute threshold in 1-minute bars
    try:
        minute_min_rows = int(os.getenv("MINUTE_MIN_ROWS", "0") or 0)
    except Exception:
        minute_min_rows = 0
    if minute_min_rows <= 0:
        try:
            verify_5m = int(os.getenv("VERIFY_MINUTE_DENSITY", "0") or 0)
        except Exception:
            verify_5m = 0
        # Approximate: 5-minute threshold * 5 => 1-minute rows
        minute_min_rows = verify_5m * 5 if verify_5m > 0 else 300

    daily_start = date(end_d.year - 2, end_d.month, end_d.day)
    minute_start = end_d - timedelta(days=60)
    daily_end = end_d - timedelta(days=1)

    exp_daily = set(business_days(daily_start, daily_end))
    exp_minute = set(business_days(minute_start, end_d))

    missing_daily_by_ticker: Dict[str, Set[date]] = {}
    missing_minute_days_by_ticker: Dict[str, Set[date]] = {}
    sparse_minute_days_by_ticker: Dict[str, List[Tuple[date,int]]] = {}

    with SessionLocal() as db:
        # Detect gaps
        for t in tickers:
            rows = (
                db.query(PriceBar.ts)
                .filter(PriceBar.ticker == t)
                .filter(PriceBar.timeframe == 'day')
                .filter(PriceBar.ts >= datetime.combine(daily_start, datetime.min.time()))
                .filter(PriceBar.ts <= datetime.combine(daily_end, datetime.max.time()))
                .all()
            )
            daily_present = {r[0].date() for r in rows}
            miss_daily = exp_daily - daily_present
            if miss_daily:
                missing_daily_by_ticker[t] = miss_daily

            miss_min_days: Set[date] = set()
            sparse_min_days: List[Tuple[date,int]] = []
            for d in exp_minute:
                start_dt = datetime.combine(d, datetime.min.time())
                end_dt = datetime.combine(d, datetime.max.time())
                cnt = (
                    db.query(PriceBar)
                    .filter(PriceBar.ticker == t)
                    .filter(PriceBar.timeframe == 'min')
                    .filter(PriceBar.ts >= start_dt, PriceBar.ts <= end_dt)
                    .count()
                )
                if cnt == 0:
                    miss_min_days.add(d)
                elif cnt < minute_min_rows:
                    sparse_min_days.append((d, cnt))
            if miss_min_days:
                missing_minute_days_by_ticker[t] = miss_min_days
            if sparse_min_days:
                sparse_minute_days_by_ticker[t] = sparse_min_days

        # Report
        print("Backfill gaps summary:")
        print(f"  Daily window:  {daily_start}..{daily_end} (business_days={len(exp_daily)})")
        print(f"  Minute window: {minute_start}..{end_d} (business_days={len(exp_minute)})")
        total_daily_gaps = sum(len(v) for v in missing_daily_by_ticker.values())
        total_minute_gaps = sum(len(v) for v in missing_minute_days_by_ticker.values())
        total_minute_sparse = sum(len(v) for v in sparse_minute_days_by_ticker.values())
        print(f"  Missing daily gaps:  {total_daily_gaps}")
        print(f"  Missing minute gaps: {total_minute_gaps}")
        print(f"  Sparse minute days (<{minute_min_rows} 1-min bars): {total_minute_sparse}")

        if dry_run:
            print("DRY_RUN=1 -> not ingesting. Exiting.")
            return

        # Ingest missing
        failed = 0
        # Daily gaps (per day per ticker)
        for t, days in missing_daily_by_ticker.items():
            for d in sorted(days):
                try:
                    n = ingest_provider_bars(db, provider='alpaca', ticker=t, d=d, timeframe='day', skip_if_exists=False)
                    print(f"daily {t} {d} +{n}")
                except Exception as e:
                    print(f"daily {t} {d} ERROR {e}")
                    failed += 1
                if sleep_ms:
                    time.sleep(sleep_ms / 1000.0)

        # Minute gaps (no bars) and sparse days (below threshold) -> re-ingest
        # Combine to a unique set of days per ticker
        for t in tickers:
            need_days: Set[date] = set()
            if t in missing_minute_days_by_ticker:
                need_days.update(missing_minute_days_by_ticker[t])
            if t in sparse_minute_days_by_ticker:
                need_days.update(d for d,_ in sparse_minute_days_by_ticker[t])
            for d in sorted(need_days):
                try:
                    n = ingest_provider_bars(db, provider='alpaca', ticker=t, d=d, timeframe='minute', skip_if_exists=False)
                    print(f"minute {t} {d} +{n}")
                except Exception as e:
                    print(f"minute {t} {d} ERROR {e}")
                    failed += 1
                if sleep_ms:
                    time.sleep(sleep_ms / 1000.0)

    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()



