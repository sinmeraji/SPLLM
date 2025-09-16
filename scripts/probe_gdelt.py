#!/usr/bin/env python3
"""
Probe GDELT provider with verbose debug to inspect requests and responses.

Usage:
  GDELT_DEBUG=1 START_DATE=2025-09-12 END_DATE=2025-09-15 TICKERS=AAPL,MSFT \
    PYTHONPATH=/Users/sina.meraji/Code/Spllm /Users/sina.meraji/Code/Spllm/backend/.venv/bin/python scripts/probe_gdelt.py
"""
from __future__ import annotations

import os
import logging
from datetime import date, datetime, timedelta, time
from typing import List

from backend.app.providers.news import GdeltProvider


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
            return vals[:8]
    return ["AAPL", "MSFT", "NVDA", "GOOGL"]


def main() -> None:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.environ.setdefault("GDELT_DEBUG", "1")
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
    prov = GdeltProvider()
    print(f"probing tickers={tickers} range={start}..{end}")
    for d in _daterange(start, end):
        items = prov.get_time_gated(d, time(23, 59), tickers)
        print(f"{d} gdelt count={len(items)}")
        for it in items[:5]:
            print(f"  {it.ticker} {it.ts.time()} {it.source} {(it.title or '')[:80]} -> {it.url}")


if __name__ == "__main__":
    main()



