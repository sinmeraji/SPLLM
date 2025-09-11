#!/usr/bin/env python
from __future__ import annotations

from datetime import date, timedelta
import os

from backend.app.core.db import SessionLocal
from backend.app.services.prices_ingest import ingest_provider_bars

TICKERS = [t.strip().upper() for t in os.getenv("TICKERS", "AAPL,MSFT").split(",") if t.strip()]
START = date.fromisoformat(os.getenv("START_DATE", date.today().isoformat()))
END = date.fromisoformat(os.getenv("END_DATE", (START + timedelta(days=7)).isoformat()))

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
