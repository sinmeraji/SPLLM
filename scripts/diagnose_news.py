#!/usr/bin/env python3
"""
Diagnostic: fetch news from Yahoo, GDELT, and EDGAR over a short date range and print counts.

Usage:
  # Last 3 days, default tickers from universe
  PYTHONPATH=/Users/sina.meraji/Code/Spllm /Users/sina.meraji/Code/Spllm/backend/.venv/bin/python scripts/diagnose_news.py

  # Explicit range and tickers
  START_DATE=2025-09-12 END_DATE=2025-09-15 TICKERS=AAPL,MSFT \
    PYTHONPATH=/Users/sina.meraji/Code/Spllm /Users/sina.meraji/Code/Spllm/backend/.venv/bin/python scripts/diagnose_news.py

Env:
  - SEC_USER_AGENT, GDELT_USER_AGENT should be defined in configs/env/.env and sourced by caller.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, time
from typing import List, Dict

from backend.app.providers.news import GdeltProvider, EdgarSubmissionsProvider, YahooRSSProvider


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _load_tickers() -> List[str]:
    env = os.getenv("TICKERS")
    if env:
        vals = [t.strip().upper() for t in env.split(",") if t.strip()]
        if vals:
            return vals
    p = os.path.join("configs", "universe", "tickers.txt")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            vals = [ln.strip().upper() for ln in f if ln.strip() and not ln.strip().startswith('#')]
            if vals:
                return vals[:10]  # limit for diagnostics
    return ["AAPL", "MSFT", "NVDA", "QQQ"]


def main() -> None:
    start_s = os.getenv("START_DATE")
    end_s = os.getenv("END_DATE")
    tickers = _load_tickers()

    today = datetime.now().date()
    if not start_s or not end_s:
        start = today - timedelta(days=2)
        end = today
    else:
        start = _parse_date(start_s)
        end = _parse_date(end_s)

    gdelt = GdeltProvider()
    edgar = EdgarSubmissionsProvider()
    yahoo = YahooRSSProvider()

    print(f"tickers={tickers}")
    for d in _daterange(start, end):
        try:
            items_y = yahoo.get_time_gated(d, time(23, 59), tickers)
        except Exception as e:
            print(f"{d} yahoo ERROR {e}")
            items_y = []
        try:
            items_g = gdelt.get_time_gated(d, time(23, 59), tickers)
        except Exception as e:
            print(f"{d} gdelt ERROR {e}")
            items_g = []
        try:
            items_e = edgar.get_time_gated(d, time(23, 59), tickers)
        except Exception as e:
            print(f"{d} edgar ERROR {e}")
            items_e = []

        # Provider counts
        print(f"{d} yahoo count={len(items_y)} gdelt count={len(items_g)} edgar count={len(items_e)}")

        # Sample titles to validate plausibility
        for name, items in ("yahoo", items_y), ("gdelt", items_g), ("edgar", items_e):
            if not items:
                continue
            sample = items[:3]
            print(f"  {name} sample: " + " | ".join([f"{it.ticker}:{(it.title or '')[:60]}" for it in sample]))


if __name__ == "__main__":
    main()



