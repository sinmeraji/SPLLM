#!/usr/bin/env python3
"""
Backfill historical news into the DB for a date range and tickers.
- Sources: GDELT (breaking) + EDGAR Submissions (filings) + optional Yahoo RSS (headlines).
- For each day: fetch items per provider, upsert to DB, recompute metrics.
Env usage: source `configs/env/.env` before running for provider headers.

Usage:
  # Explicit range
  START_DATE=2024-01-01 END_DATE=2025-09-11 TICKERS=AAPL,MSFT \
    python scripts/backfill_news.py

  # Defaults (no env):
  # - Providers from NEWS_PROVIDERS or fall back to edgar_submissions
  python scripts/backfill_news.py
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, time
from typing import List

from backend.app.core.db import SessionLocal
from backend.app.providers.news import GdeltProvider, EdgarSubmissionsProvider, YahooRSSProvider
from backend.app.services.news_db import upsert_news_items_to_db, compute_metrics_for_date


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
        return [t.strip().upper() for t in env.split(",") if t.strip()]
    p = os.path.join("configs", "universe", "tickers.txt")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            vals = [ln.strip().upper() for ln in f if ln.strip() and not ln.strip().startswith('#')]
            if vals:
                return vals
    return ["AAPL", "MSFT", "NVDA", "QQQ"]


def _load_providers():
    val = (os.getenv("NEWS_PROVIDERS") or "edgar_submissions").lower()
    parts = [p.strip() for p in val.split(",") if p.strip()]
    enabled = set(parts)
    return enabled


def main() -> None:
    start_s = os.getenv("START_DATE")
    end_s = os.getenv("END_DATE")
    tickers = _load_tickers()

    enabled = _load_providers()
    use_gdelt = "gdelt" in enabled
    use_edgar = "edgar_submissions" in enabled or "edgar" in enabled
    use_yahoo = "yahoo" in enabled or "yahoo_rss" in enabled

    gdelt = GdeltProvider() if use_gdelt else None
    edgar = EdgarSubmissionsProvider() if use_edgar else None
    yahoo = YahooRSSProvider() if use_yahoo else None

    today = datetime.now().date()
    if not start_s or not end_s:
        # Default horizons per provider
        ranges = []
        if use_gdelt:
            ranges.append((today - timedelta(days=90), today, "gdelt"))
        if use_edgar:
            ranges.append((today - timedelta(days=365), today, "edgar"))
        if use_yahoo:
            # Yahoo is live-oriented; if explicitly enabled, backfill only a few days
            horizon_days = int(os.getenv("YAHOO_BACKFILL_DAYS", "7") or "7")
            ranges.append((today - timedelta(days=horizon_days), today, "yahoo"))
    else:
        s = _parse_date(start_s)
        e = _parse_date(end_s)
        ranges = []
        if use_gdelt:
            ranges.append((s, e, "gdelt"))
        if use_edgar:
            ranges.append((s, e, "edgar"))
        if use_yahoo:
            ranges.append((s, e, "yahoo"))

    with SessionLocal() as db:
        for start, end, kind in ranges:
            for d in _daterange(start, end):
                # Yahoo headlines
                if kind == "yahoo" and yahoo is not None:
                    try:
                        items_y = yahoo.get_time_gated(d, time(23, 59), tickers)
                        res = upsert_news_items_to_db(db, items_y, explicit_type=None)
                        print(f"{d} yahoo items={len(items_y)} written={res.get('written')} skipped={res.get('skipped')}")
                    except Exception as e:
                        print(f"{d} yahoo ERROR {e}")
                # GDELT headlines
                if kind == "gdelt" and gdelt is not None:
                    try:
                        items_g = gdelt.get_time_gated(d, time(23, 59), tickers)
                        res = upsert_news_items_to_db(db, items_g, explicit_type=None)
                        print(f"{d} gdelt items={len(items_g)} written={res.get('written')} skipped={res.get('skipped')}")
                    except Exception as e:
                        print(f"{d} gdelt ERROR {e}")
                # EDGAR filings
                if kind == "edgar" and edgar is not None:
                    try:
                        items_e = edgar.get_time_gated(d, time(23, 59), tickers)
                        res = upsert_news_items_to_db(db, items_e, explicit_type="filings")
                        print(f"{d} edgar items={len(items_e)} written={res.get('written')} skipped={res.get('skipped')}")
                    except Exception as e:
                        print(f"{d} edgar ERROR {e}")
                # Metrics
                try:
                    mr = compute_metrics_for_date(db, d, tickers)
                    print(f"{d} metrics_written={mr.get('metrics_written')}")
                except Exception as e:
                    print(f"{d} metrics ERROR {e}")


if __name__ == "__main__":
    main()



