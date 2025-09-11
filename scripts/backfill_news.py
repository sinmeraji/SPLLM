#!/usr/bin/env python3
"""
Backfill historical news into the DB for a date range and tickers.
- Sources: GDELT (breaking) + EDGAR Submissions (filings).
- For each day: fetch items per provider, upsert to DB, recompute metrics.
Env usage: source `configs/env/.env` before running for provider headers.

Usage:
  START_DATE=2024-01-01 END_DATE=2025-09-11 TICKERS=AAPL,MSFT \
  python scripts/backfill_news.py
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, time
from typing import List

from backend.app.core.db import SessionLocal
from backend.app.providers.news import GdeltProvider, EdgarSubmissionsProvider
from backend.app.services.news_db import upsert_news_items_to_db, compute_metrics_for_date


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main() -> None:
    start_s = os.getenv("START_DATE")
    end_s = os.getenv("END_DATE")
    tickers_s = os.getenv("TICKERS") or "AAPL,MSFT,NVDA,QQQ"
    if not start_s or not end_s:
        raise SystemExit("Set START_DATE and END_DATE (YYYY-MM-DD)")
    start = _parse_date(start_s)
    end = _parse_date(end_s)
    tickers = [t.strip().upper() for t in tickers_s.split(",") if t.strip()]

    gdelt = GdeltProvider()
    edgar = EdgarSubmissionsProvider()

    with SessionLocal() as db:
        for d in _daterange(start, end):
            # Headlines
            try:
                items_g = gdelt.get_time_gated(d, time(23, 59), tickers)
                upsert_news_items_to_db(db, items_g, explicit_type=None)
            except Exception:
                pass
            # Filings
            try:
                items_e = edgar.get_time_gated(d, time(23, 59), tickers)
                upsert_news_items_to_db(db, items_e, explicit_type="filings")
            except Exception:
                pass
            # Metrics
            try:
                compute_metrics_for_date(db, d, tickers)
            except Exception:
                pass


if __name__ == "__main__":
    main()


