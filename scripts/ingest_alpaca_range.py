#!/usr/bin/env python
from __future__ import annotations

import os
from datetime import datetime, date, time, timedelta
import asyncio
from zoneinfo import ZoneInfo

from backend.app.providers.alpaca import fetch_minute_bars, save_bars_csv

ET = ZoneInfo("America/New_York")

TICKERS = [t.strip().upper() for t in os.getenv("TICKERS", "AAPL,MSFT,NVDA,QQQ").split(",") if t.strip()]
START_STR = os.getenv("START_DATE", "2025-01-01")
END_STR = os.getenv("END_DATE", datetime.now(tz=ET).date().isoformat())

start_day = date.fromisoformat(START_STR)
end_day = date.fromisoformat(END_STR)

async def fetch_day_range_utc(d: date) -> tuple[str, str]:
    # Convert 09:30–16:00 ET to UTC ISO strings for the given date
    start_dt = datetime.combine(d, time(9, 30), tzinfo=ET).astimezone(ZoneInfo("UTC"))
    end_dt = datetime.combine(d, time(16, 0), tzinfo=ET).astimezone(ZoneInfo("UTC"))
    return start_dt.isoformat().replace("+00:00", "Z"), end_dt.isoformat().replace("+00:00", "Z")

async def ingest_day(ticker: str, d: date):
    if d.weekday() >= 5:  # skip weekends
        return 0
    start_iso, end_iso = await fetch_day_range_utc(d)
    bars = await fetch_minute_bars(ticker, start_iso, end_iso)
    save_bars_csv(ticker, bars)
    return len(bars)

async def main():
    cur = start_day
    total = 0
    while cur <= end_day:
        for t in TICKERS:
            try:
                n = await ingest_day(t, cur)
                print(f"{t} {cur.isoformat()} {n} bars")
                total += n
            except Exception as e:
                print(f"ERROR {t} {cur}: {e}")
        cur = date.fromordinal(cur.toordinal() + 1)
    print(f"DONE total_bars={total}")

if __name__ == "__main__":
    asyncio.run(main())
