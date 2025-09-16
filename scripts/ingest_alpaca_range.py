#!/usr/bin/env python
# Script: DB-based Alpaca range ingestion
# - Ingests bars into SQLite DB for given tickers and date range (env)
# - TIMEFRAME env controls granularity: minute | day (default minute)
# Usage:
#   TICKERS=AAPL,MSFT START_DATE=YYYY-MM-DD END_DATE=YYYY-MM-DD TIMEFRAME=minute \
#     python scripts/ingest_alpaca_range.py
from __future__ import annotations

import os
from datetime import date, timedelta, datetime, time

from backend.app.core.db import SessionLocal
from backend.app.services.prices_ingest import ingest_provider_bars
from backend.app.utils.logging import setup_logging
from backend.app.models.prices import PriceBar
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

TICKERS = [t.strip().upper() for t in os.getenv("TICKERS", "AAPL,MSFT").split(",") if t.strip()]
END = date.fromisoformat(os.getenv("END_DATE", date.today().isoformat()))
START = date.fromisoformat(os.getenv("START_DATE", (date(END.year-2, END.month, END.day)).isoformat()))
TIMEFRAME = os.getenv("TIMEFRAME", "minute").strip().lower()

def ingest_daily_range_once(db: SessionLocal, ticker: str, start_d: date, end_d: date) -> int:
    import os as _os, httpx as _httpx
    key = _os.getenv('ALPACA_KEY_ID')
    secret = _os.getenv('ALPACA_SECRET_KEY')
    if not key or not secret:
        return 0
    ET = __import__('zoneinfo').ZoneInfo('America/New_York')
    start_dt = datetime.combine(start_d, time(9, 30), tzinfo=ET).astimezone(__import__('zoneinfo').ZoneInfo('UTC'))
    end_dt = datetime.combine(end_d, time(16, 0), tzinfo=ET).astimezone(__import__('zoneinfo').ZoneInfo('UTC'))
    feed = _os.getenv('ALPACA_FEED', 'iex')
    params = {
        "start": start_dt.isoformat().replace('+00:00', 'Z'),
        "end": end_dt.isoformat().replace('+00:00', 'Z'),
        "timeframe": "1Day",
        "limit": 10000,
        "adjustment": "raw",
        "feed": feed,
    }
    url = f"https://data.alpaca.markets/v2/stocks/{ticker.upper()}/bars"
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    rows = 0
    log_errors = _os.getenv("INGEST_LOG_ERRORS", "1") == "1"
    verbose = _os.getenv("INGEST_VERBOSE", "0") == "1"
    try:
        with _httpx.Client(timeout=30) as client:
            for attempt in (1, 2):
                r = client.get(url, params=params, headers=headers)
                if verbose:
                    print(f"GET {url} status={r.status_code} ticker={ticker} range={start_d}..{end_d}")
                if r.status_code == 429 and attempt == 1:
                    # simple backoff and retry once
                    __import__('time').sleep(3)
                    continue
                r.raise_for_status()
                data = r.json()
                bars = data.get('bars') or []
                if verbose:
                    print(f"ticker={ticker} daily bars fetched={len(bars)}")
                for b in bars:
                    ts = datetime.fromisoformat(b['t'].replace('Z', '+00:00')).astimezone(None).replace(tzinfo=None)
                    stmt = sqlite_insert(PriceBar).values(
                        ticker=ticker.upper(), ts=ts, timeframe='day',
                        open=float(b['o']), high=float(b['h']), low=float(b['l']), close=float(b['c']),
                        volume=float(b.get('v', 0) or 0)
                    )
                    upsert = stmt.on_conflict_do_update(
                        index_elements=['ticker', 'ts', 'timeframe'],
                        set_={
                            'open': stmt.excluded.open,
                            'high': stmt.excluded.high,
                            'low': stmt.excluded.low,
                            'close': stmt.excluded.close,
                            'volume': stmt.excluded.volume,
                        }
                    )
                    db.execute(upsert)
                    rows += 1
                db.commit()
                break
    except Exception as e:
        db.rollback()
        if log_errors:
            print(f"ERROR daily ingest {ticker} {start_d}..{end_d}: {e}")
        return 0
    return rows


def main():
    setup_logging()
    # Quick connectivity check: ensure keys exist and Alpaca reachable for the first ticker/day
    import os as _os, httpx as _httpx
    if not _os.getenv("ALPACA_KEY_ID") or not _os.getenv("ALPACA_SECRET_KEY"):
        raise SystemExit("Missing ALPACA_KEY_ID/ALPACA_SECRET_KEY in environment.")
    try:
        with _httpx.Client(timeout=5) as _c:
            _c.get("https://data.alpaca.markets/v2/stocks/AAPL/bars", params={"timeframe":"1Day","limit":1})
    except Exception as _e:
        raise SystemExit(f"Alpaca unreachable: {_e}")

    QUIET = _os.getenv("INGEST_QUIET", "0") == "1"
    VERBOSE = _os.getenv("INGEST_VERBOSE", "0") == "1"
    if VERBOSE:
        QUIET = False
    with SessionLocal() as db:
        cur = START
        total = 0
        if TIMEFRAME == 'day':
            # Efficient daily ingestion: one API call per ticker for full range
            import time as _time
            try:
                SLEEP_MS = int(_os.getenv("INGEST_SLEEP_MS", "0"))
            except Exception:
                SLEEP_MS = 0
            test_first_four = _os.getenv("INGEST_TEST_FOUR", "0") == "1"
            tickers = TICKERS[:4] if test_first_four else TICKERS
            if VERBOSE:
                print(f"tickers={tickers} start={START} end={END} timeframe=day")
            for t in tickers:
                n = ingest_daily_range_once(db, t, START, END)
                if not QUIET:
                    print(f"{t} {START.isoformat()}..{END.isoformat()} +{n}")
                total += n
                if SLEEP_MS > 0:
                    _time.sleep(SLEEP_MS / 1000.0)
        else:
            # Optional throttle between provider calls to avoid rate limits
            import time as _time
            try:
                SLEEP_MS = int(_os.getenv("INGEST_SLEEP_MS", "0"))
            except Exception:
                SLEEP_MS = 0
            while cur <= END:
                if cur.weekday() < 5:
                    for t in TICKERS:
                        n = ingest_provider_bars(db, provider='alpaca', ticker=t, d=cur, timeframe=TIMEFRAME)
                        if not QUIET:
                            print(f"{t} {cur.isoformat()} +{n}")
                        total += n
                        if SLEEP_MS > 0:
                            _time.sleep(SLEEP_MS / 1000.0)
                cur = date.fromordinal(cur.toordinal()+1)
        if not QUIET:
            print(f"DONE total={total}")

if __name__ == "__main__":
    main()
