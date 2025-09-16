#!/usr/bin/env python
"""
Script: Verify DB price coverage for universe
Purpose:
- Checks that for each ticker in configs/universe/tickers.txt:
  - Daily bars exist for the last ~2 years (business days) up to (END_DATE-1)
  - Minute bars exist for each business day in the last 60 days (at least one row per day)

Env (optional):
- DATE: ISO date (YYYY-MM-DD). Defaults to today (ET)
- TICKERS: override list (comma-separated). Defaults to universe file

Exit code:
- 0 if no missing days detected
- 1 if any gaps are found
"""
from __future__ import annotations

from pathlib import Path
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import os
from typing import List, Dict, Set

from dotenv import load_dotenv

# Ensure local imports
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.db import SessionLocal
from backend.app.models.prices import PriceBar


ET = ZoneInfo("America/New_York")


def load_env() -> None:
    envp = ROOT / "configs" / "env" / ".env"
    if envp.exists():
        load_dotenv(dotenv_path=str(envp), override=False)


def weekday_days(start_d: date, end_d: date) -> List[date]:
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
    if end:
        end_d = date.fromisoformat(end)
    else:
        end_d = datetime.now(tz=ET).date()

    daily_start = date(end_d.year - 2, end_d.month, end_d.day)
    minute_start = end_d - timedelta(days=60)

    # For daily, exclude the END date itself to avoid partial/today
    daily_end = end_d - timedelta(days=1)

    # Expected trading calendars derived from a benchmark ticker's actual bars (preferred over naive weekdays)
    # Use SPY if available in universe; else QQQ; else fallback to weekday list
    benchmark = "SPY" if "SPY" in tickers else ("QQQ" if "QQQ" in tickers else None)
    exp_daily: Set[date]
    exp_minute: Set[date]
    with SessionLocal() as db:
        if benchmark:
            # Daily trading days from benchmark actual bars
            rows = (
                db.query(PriceBar.ts)
                .filter(PriceBar.ticker == benchmark)
                .filter(PriceBar.timeframe == 'day')
                .filter(PriceBar.ts >= datetime.combine(daily_start, datetime.min.time()))
                .filter(PriceBar.ts <= datetime.combine(daily_end, datetime.max.time()))
                .all()
            )
            exp_daily = {r[0].date() for r in rows}
            # Minute trading days: any day with ≥1 minute bar on benchmark
            exp_minute = set()
            cur = minute_start
            while cur <= end_d:
                start_dt = datetime.combine(cur, datetime.min.time())
                end_dt = datetime.combine(cur, datetime.max.time())
                has = (
                    db.query(PriceBar)
                    .filter(PriceBar.ticker == benchmark)
                    .filter(PriceBar.timeframe == 'min')
                    .filter(PriceBar.ts >= start_dt, PriceBar.ts <= end_dt)
                    .limit(1)
                    .count()
                )
                if has:
                    exp_minute.add(cur)
                cur = date.fromordinal(cur.toordinal() + 1)
        else:
            exp_daily = set(weekday_days(daily_start, daily_end))
            exp_minute = set(weekday_days(minute_start, end_d))

    missing_daily_by_ticker: Dict[str, Set[date]] = {}
    missing_minute_days_by_ticker: Dict[str, Set[date]] = {}

    with SessionLocal() as db:
        for t in tickers:
            # Daily present dates
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

            # Minute: for each business day, check at least one minute bar exists
            miss_min_days: Set[date] = set()
            for d in exp_minute:
                start_dt = datetime.combine(d, datetime.min.time())
                end_dt = datetime.combine(d, datetime.max.time())
                cnt = (
                    db.query(PriceBar)
                    .filter(PriceBar.ticker == t)
                    .filter(PriceBar.timeframe == 'min')
                    .filter(PriceBar.ts >= start_dt, PriceBar.ts <= end_dt)
                    .limit(1)
                    .count()
                )
                if cnt == 0:
                    miss_min_days.add(d)
            if miss_min_days:
                missing_minute_days_by_ticker[t] = miss_min_days

    # Report
    any_missing = False
    print("Verification window:")
    print(f"  Daily:  {daily_start}..{daily_end} trading_days={len(exp_daily)}")
    print(f"  Minute: {minute_start}..{end_d} trading_days={len(exp_minute)}")
    print("")
    if missing_daily_by_ticker:
        any_missing = True
        print("Missing DAILY bars:")
        for t, miss in sorted(missing_daily_by_ticker.items()):
            print(f"  {t}: missing_days={len(miss)}")
    else:
        print("Daily bars: OK (no missing)")
    print("")
    if missing_minute_days_by_ticker:
        any_missing = True
        print("Missing MINUTE days (no minute bars on these days):")
        for t, miss in sorted(missing_minute_days_by_ticker.items()):
            print(f"  {t}: missing_days={len(miss)}")
    else:
        print("Minute bars: OK (every business day has at least one bar)")

    raise SystemExit(1 if any_missing else 0)


if __name__ == "__main__":
    main()


