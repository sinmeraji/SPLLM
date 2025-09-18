#!/usr/bin/env python
"""
Script: Verify DB price coverage for universe
Purpose:
- Checks that for each ticker in configs/universe/tickers.txt:
  - Daily and minute bars exist for the last N business days (configurable)
  - Daily indicators and intraday indicators are populated (basic presence checks)
  - News metrics are computed for days that have news (1d window presence)

Env (optional):
- DATE: ISO date (YYYY-MM-DD). Defaults to today (ET)
- TICKERS: override list (comma-separated). Defaults to universe file
- VERIFY_N_DAYS: integer window of recent business days to verify (default 5)
- VERIFY_MINUTE_DENSITY: minimum minute bars per day threshold (default 300)
- VERIFY_INTRADAY_ROWS: minimum intraday indicator rows per day threshold (default 50)

Exit code:
- 0 if no missing days detected
- 1 if any gaps are found
"""
from __future__ import annotations

from pathlib import Path
from datetime import date, datetime, timedelta, time as dtime
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
from backend.app.models.prices import PriceIndicator, PriceIndicatorExt, PriceIndicatorIntraday
from backend.app.models.news import NewsRaw, NewsMetric


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


def _thresholds() -> tuple[int, int]:
    minute_threshold = int(os.getenv("VERIFY_MINUTE_DENSITY", "300") or 300)
    intra_threshold = int(os.getenv("VERIFY_INTRADAY_ROWS", "50") or 50)
    return minute_threshold, intra_threshold


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
    minute_threshold, intra_threshold = _thresholds()

    # Define windows
    daily_start = date(end_d.year - 2, end_d.month, end_d.day)
    daily_end = end_d - timedelta(days=1)  # exclude today to avoid partial
    minute_start = end_d - timedelta(days=60)

    # Determine trading-day sets using benchmark bars (handles holidays)
    with SessionLocal() as db:
        benchmark = "SPY" if "SPY" in tickers else ("QQQ" if "QQQ" in tickers else (tickers[0] if tickers else None))
        exp_daily: Set[date]
        exp_minute: Set[date]
        if benchmark:
            rows = (
                db.query(PriceBar.ts)
                .filter(PriceBar.ticker == benchmark)
                .filter(PriceBar.timeframe == 'day')
                .filter(PriceBar.ts >= datetime.combine(daily_start, datetime.min.time()))
                .filter(PriceBar.ts <= datetime.combine(daily_end, datetime.max.time()))
                .all()
            )
            exp_daily = {r[0].date() for r in rows}
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

    # Report header
    print("Verification (full windows):")
    print(f"  Daily window:  {daily_start}..{daily_end} trading_days={len(exp_daily)}")
    print(f"  Minute window: {minute_start}..{end_d} trading_days={len(exp_minute)}")
    print(f"  Universe size: {len(tickers)}")
    print("")

    any_missing = False
    with SessionLocal() as db:
        for t in tickers:
            t_missing_daily: List[date] = []
            t_missing_minute: List[date] = []
            t_sparse_minute: List[tuple[date,int]] = []
            t_missing_daily_ind: List[date] = []
            t_missing_intra_ind: List[date] = []
            t_missing_news_metrics: List[date] = []

            # Check daily window
            for d in sorted(exp_daily):
                # DAILY bars presence
                d_start = datetime.combine(d, datetime.min.time())
                d_end = datetime.combine(d, datetime.max.time())
                cnt_day = (
                    db.query(PriceBar)
                    .filter(PriceBar.ticker == t)
                    .filter(PriceBar.timeframe == 'day')
                    .filter(PriceBar.ts >= d_start, PriceBar.ts <= d_end)
                    .count()
                )
                if cnt_day == 0:
                    t_missing_daily.append(d)

            # Check minute window
            for d in sorted(exp_minute):
                start_mkt = datetime.combine(d, dtime(9, 30))
                end_mkt = datetime.combine(d, dtime(16, 0))
                cnt_min = (
                    db.query(PriceBar)
                    .filter(PriceBar.ticker == t)
                    .filter(PriceBar.timeframe == 'min')
                    .filter(PriceBar.ts >= start_mkt, PriceBar.ts <= end_mkt)
                    .count()
                )
                if cnt_min == 0:
                    t_missing_minute.append(d)
                elif cnt_min < minute_threshold:
                    t_sparse_minute.append((d, cnt_min))
            # DAILY indicators presence across daily window
            for d in sorted(exp_daily):
                has_daily_ind = db.query(PriceIndicator).filter(PriceIndicator.ticker == t, PriceIndicator.date == d).count() > 0
                has_daily_ext = db.query(PriceIndicatorExt).filter(PriceIndicatorExt.ticker == t, PriceIndicatorExt.date == d).count() > 0
                if not (has_daily_ind and has_daily_ext):
                    t_missing_daily_ind.append(d)

            # INTRADAY indicators presence across minute window
            for d in sorted(exp_minute):
                start_mkt = datetime.combine(d, dtime(9, 30))
                end_mkt = datetime.combine(d, dtime(16, 0))
                cnt_intra = (
                    db.query(PriceIndicatorIntraday)
                    .filter(PriceIndicatorIntraday.ticker == t)
                    .filter(PriceIndicatorIntraday.ts >= start_mkt, PriceIndicatorIntraday.ts <= end_mkt)
                    .count()
                )
                if cnt_intra < intra_threshold:
                    t_missing_intra_ind.append(d)

            # NEWS metrics presence for days that have news within daily window
            for d in sorted(exp_daily):
                d_start = datetime.combine(d, datetime.min.time())
                d_endnext = datetime.combine(d + timedelta(days=1), datetime.min.time())
                has_news = (
                    db.query(NewsRaw)
                    .filter(NewsRaw.ticker == t)
                    .filter(NewsRaw.ts >= d_start, NewsRaw.ts < d_endnext)
                    .limit(1)
                    .count()
                ) > 0
                if has_news:
                    has_metric_1d = (
                        db.query(NewsMetric)
                        .filter(NewsMetric.ticker == t)
                        .filter(NewsMetric.date == d)
                        .filter(NewsMetric.window == "1d")
                        .limit(1)
                        .count()
                    ) > 0
                    if not has_metric_1d:
                        t_missing_news_metrics.append(d)

            # Print per-ticker summary if any issues
            if t_missing_daily or t_missing_minute or t_sparse_minute or t_missing_daily_ind or t_missing_intra_ind or t_missing_news_metrics:
                any_missing = True
                print(f"Ticker {t} issues:")
                if t_missing_daily:
                    print(f"  - Missing DAILY bars on: {', '.join(d.isoformat() for d in t_missing_daily)}")
                if t_missing_minute:
                    print(f"  - Missing MINUTE bars on: {', '.join(d.isoformat() for d in t_missing_minute)}")
                if t_sparse_minute:
                    print("  - Sparse MINUTE days (count<threshold):" )
                    for d,c in t_sparse_minute:
                        print(f"      {d.isoformat()}: {c}")
                if t_missing_daily_ind:
                    print(f"  - Missing DAILY indicators on: {', '.join(d.isoformat() for d in t_missing_daily_ind)}")
                if t_missing_intra_ind:
                    print(f"  - Missing/low INTRADAY indicators on: {', '.join(d.isoformat() for d in t_missing_intra_ind)}")
                if t_missing_news_metrics:
                    print(f"  - Missing NEWS metrics(1d) on: {', '.join(d.isoformat() for d in t_missing_news_metrics)}")

    if not any_missing:
        print("All checks passed for the selected windows.")
    raise SystemExit(1 if any_missing else 0)


if __name__ == "__main__":
    main()


