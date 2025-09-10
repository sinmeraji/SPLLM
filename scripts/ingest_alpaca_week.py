#!/usr/bin/env python
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os

from backend.app.providers.alpaca import fetch_minute_bars, save_bars_csv

TICKERS = ["AAPL", "MSFT", "NVDA", "QQQ"]

async def main():
    start = os.getenv("INGEST_START", "2025-01-06T14:30:00Z")
    end = os.getenv("INGEST_END", "2025-01-10T21:00:00Z")
    tasks = []
    for t in TICKERS:
        tasks.append(fetch_minute_bars(t, start, end))
    results = await asyncio.gather(*tasks)
    for t, bars in zip(TICKERS, results):
        save_bars_csv(t, bars)
        print(f"saved {t}: {len(bars)} bars")

if __name__ == "__main__":
    asyncio.run(main())
