#!/usr/bin/env python3
"""
Rescore sentiment for existing NewsRaw rows in a date range and refresh metrics.
- Uses VADER on `title` to compute compound sentiment for rows with 0/None.
- Recomputes NewsMetric aggregates per day in the range for affected tickers.

Env usage (source configs/env/.env first if needed):
  START_DATE=YYYY-MM-DD END_DATE=YYYY-MM-DD TICKERS="AAPL,MSFT" \
  python scripts/rescore_news_sentiment.py
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import List, Set

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from backend.app.core.db import SessionLocal
from backend.app.models.news import NewsRaw
from backend.app.services.news_db import compute_metrics_for_date


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main() -> None:
    start_s = os.getenv("START_DATE")
    end_s = os.getenv("END_DATE")
    tickers_s = os.getenv("TICKERS")
    if not start_s or not end_s:
        raise SystemExit("Set START_DATE and END_DATE (YYYY-MM-DD)")
    start_dt = datetime.fromisoformat(f"{start_s}T00:00:00")
    end_dt = datetime.fromisoformat(f"{end_s}T23:59:59")
    tickers = None
    if tickers_s:
        tickers = [t.strip().upper() for t in tickers_s.split(',') if t.strip()]

    sia = SentimentIntensityAnalyzer()

    with SessionLocal() as db:
        q = db.query(NewsRaw).filter(NewsRaw.ts >= start_dt, NewsRaw.ts <= end_dt)
        if tickers:
            q = q.filter(NewsRaw.ticker.in_(tickers))
        rows = q.all()
        changed_dates: Set[date] = set()
        for r in rows:
            # Only rescore when missing or zero
            if r.sentiment is None or float(r.sentiment) == 0.0:
                vs = sia.polarity_scores(r.title or "")
                r.sentiment = float(vs.get("compound", 0.0))
                changed_dates.add(r.ts.date())
        db.commit()

        # Refresh metrics for changed dates (and only selected tickers)
        for d in sorted(changed_dates):
            compute_metrics_for_date(db, d, tickers)


if __name__ == "__main__":
    main()


