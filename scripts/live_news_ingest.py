#!/usr/bin/env python3
"""
Live news ingest script (to run a few times per day via cron/launchd).
- Fetches from selected providers for a given DATE (default: today) and tickers.
- Upserts into DB (`news_raw`) with sentiment scoring and recomputes `news_metrics`.

Usage examples:
  DATE=$(date +%F) TICKERS=AAPL,MSFT,NVDA,QQQ PROVIDERS=gdelt,edgar_submissions \
  python scripts/live_news_ingest.py

Notes:
- Providers: gdelt, edgar (Atom), edgar_submissions (JSON)
- Ensure venv and PYTHONPATH are set, e.g., export PYTHONPATH=./
"""
from __future__ import annotations

import os
from datetime import date, datetime, time
from typing import List

from backend.app.core.db import SessionLocal
from backend.app.providers.news import GdeltProvider, EdgarProvider, EdgarSubmissionsProvider, NewsItem
from backend.app.services.news_db import upsert_news_items_to_db, compute_metrics_for_date


def _parse_date(s: str | None) -> date:
    if not s:
        return datetime.now().date()
    return date.fromisoformat(s)


def _load_tickers() -> List[str]:
    env = os.getenv("TICKERS")
    if env:
        return [t.strip().upper() for t in env.split(",") if t.strip()]
    p = os.path.join("configs", "universe", "tickers.txt")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return [ln.strip().upper() for ln in f if ln.strip()]
    return ["AAPL", "MSFT", "NVDA", "QQQ"]


def _providers_from_env():
    names = (os.getenv("PROVIDERS") or "gdelt,edgar_submissions").lower().split(",")
    out = []
    for n in [x.strip() for x in names if x.strip()]:
        if n == "gdelt":
            out.append((GdeltProvider(), None))
        elif n == "edgar":
            out.append((EdgarProvider(), "filings"))
        elif n in ("edgar_submissions", "edgar_json"):
            out.append((EdgarSubmissionsProvider(), "filings"))
    return out


def main() -> None:
    d = _parse_date(os.getenv("DATE"))
    tickers = _load_tickers()
    providers = _providers_from_env()
    with SessionLocal() as db:
        for prov, explicit_type in providers:
            try:
                items: List[NewsItem] = prov.get_time_gated(d, time(23, 59), tickers)
                upsert_news_items_to_db(db, items, explicit_type=explicit_type)
            except Exception:
                # best effort per provider
                continue
        compute_metrics_for_date(db, d, tickers)


if __name__ == "__main__":
    main()


