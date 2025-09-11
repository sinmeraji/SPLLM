#!/usr/bin/env python
# Script: DB-based Alpaca range ingestion
# - Ingests minute bars into SQLite DB for given tickers and date range (env)
# Usage: TICKERS=AAPL,MSFT START_DATE=YYYY-MM-DD END_DATE=YYYY-MM-DD python scripts/ingest_alpaca_range.py
from __future__ import annotations

import os
from datetime import date, timedelta

from backend.app.core.db import SessionLocal
from backend.app.services.prices_ingest import ingest_provider_bars

TICKERS = [t.strip().upper() for t in os.getenv("TICKERS", "AAPL,MSFT").split(",") if t.strip()]
END = date.fromisoformat(os.getenv("END_DATE", date.today().isoformat()))
START = date.fromisoformat(os.getenv("START_DATE", (date(END.year-2, END.month, END.day)).isoformat()))


def main():
    with SessionLocal() as db:
        cur = START
        total = 0
        while cur <= END:
            if cur.weekday() < 5:
                for t in TICKERS:
                    n = ingest_provider_bars(db, provider='alpaca', ticker=t, d=cur, timeframe='minute')
                    print(f"{t} {cur.isoformat()} +{n}")
                    total += n
            cur = date.fromordinal(cur.toordinal()+1)
        print(f"DONE total={total}")

if __name__ == "__main__":
    main()
