from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List
import csv
import os
import httpx

from sqlalchemy.orm import Session

from ..models.prices import PriceBar


def ingest_csv_bars(db: Session, *, ticker: str, d: date, timeframe: str = "minute") -> int:
    ticker = ticker.upper()
    tf = timeframe
    if tf not in ("minute", "5min", "daily", "day"):
        raise ValueError("invalid timeframe")
    # Map folder and ts granularity
    folder = "minute" if tf in ("minute", "5min") else "daily"
    root = Path("data/prices") / ticker / folder
    fp = root / f"{d.isoformat()}.csv"
    if not fp.exists():
        return 0
    rows = 0
    with fp.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            ts = datetime.fromisoformat(row["ts"])  # naive ET
            bar = db.get(PriceBar, {"ticker": ticker, "ts": ts, "timeframe": ("min" if folder=="minute" else "day")})
            # Upsert by composite key
            existing = db.query(PriceBar).filter(
                PriceBar.ticker == ticker,
                PriceBar.ts == ts,
                PriceBar.timeframe == ("min" if folder=="minute" else "day"),
            ).one_or_none()
            if existing:
                existing.open = float(row["open"])
                existing.high = float(row["high"])
                existing.low = float(row["low"])
                existing.close = float(row["close"])
                existing.volume = float(row.get("volume", 0) or 0)
            else:
                db.add(PriceBar(
                    ticker=ticker,
                    ts=ts,
                    timeframe=("min" if folder=="minute" else "day"),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0) or 0),
                ))
            rows += 1
    db.commit()
    return rows


def ingest_provider_bars(db: Session, *, provider: str, ticker: str, d: date, timeframe: str = "minute") -> int:
    provider = provider.lower()
    if provider == 'alpaca':
        return _ingest_alpaca(db, ticker=ticker, d=d, timeframe=timeframe)
    # fallback to csv if unknown
    return ingest_csv_bars(db, ticker=ticker, d=d, timeframe=timeframe)


def _ingest_alpaca(db: Session, *, ticker: str, d: date, timeframe: str) -> int:
    key = os.getenv('ALPACA_KEY_ID')
    secret = os.getenv('ALPACA_SECRET_KEY')
    if not key or not secret:
        return 0
    # Alpaca Market Data v2 bars endpoint
    # Docs: https://docs.alpaca.markets/reference/market-data-api-bars
    tf = '1Min' if timeframe.startswith('min') else '1Day'
    start = datetime(d.year, d.month, d.day, 9, 30).isoformat() + 'Z'
    end = datetime(d.year, d.month, d.day, 16, 0).isoformat() + 'Z'
    url = f"https://data.alpaca.markets/v2/stocks/{ticker.upper()}/bars"
    params = {"start": start, "end": end, "timeframe": tf, "limit": 10000, "adjustment": "raw"}
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
            bars = data.get('bars') or []
            rows = 0
            for b in bars:
                # Alpaca returns ISO8601 with Z
                ts = datetime.fromisoformat(b['t'].replace('Z', '+00:00')).astimezone(None).replace(tzinfo=None)
                existing = db.query(PriceBar).filter(
                    PriceBar.ticker == ticker.upper(),
                    PriceBar.ts == ts,
                    PriceBar.timeframe == ('min' if tf == '1Min' else 'day'),
                ).one_or_none()
                if existing:
                    existing.open = float(b['o'])
                    existing.high = float(b['h'])
                    existing.low = float(b['l'])
                    existing.close = float(b['c'])
                    existing.volume = float(b.get('v', 0) or 0)
                else:
                    db.add(PriceBar(
                        ticker=ticker.upper(),
                        ts=ts,
                        timeframe=('min' if tf == '1Min' else 'day'),
                        open=float(b['o']),
                        high=float(b['h']),
                        low=float(b['l']),
                        close=float(b['c']),
                        volume=float(b.get('v', 0) or 0),
                    ))
                rows += 1
            db.commit()
            return rows
    except Exception:
        return 0
