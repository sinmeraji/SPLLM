"""
Service: prices ingestion.
- Pulls minute/day bars from providers (Alpaca) and upserts into DB with idempotency.
- Skips existing days; handles on-conflict updates safely for SQLite.
"""
from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Iterable, List
import csv
import os
import httpx
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

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


def _timeframe_key(timeframe: str) -> str:
    return 'min' if timeframe.startswith('min') else 'day'


def day_has_bars(db: Session, *, ticker: str, d: date, timeframe: str) -> bool:
    tf_key = _timeframe_key(timeframe)
    start_dt = datetime(d.year, d.month, d.day, 0, 0, 0)
    end_dt = datetime(d.year, d.month, d.day, 23, 59, 59)
    exists = db.query(PriceBar).filter(
        PriceBar.ticker == ticker.upper(),
        PriceBar.timeframe == tf_key,
        PriceBar.ts >= start_dt,
        PriceBar.ts <= end_dt,
    ).limit(1).first()
    return exists is not None


def ingest_provider_bars(db: Session, *, provider: str, ticker: str, d: date, timeframe: str = "minute", skip_if_exists: bool = True) -> int:
    provider = provider.lower()
    if skip_if_exists and day_has_bars(db, ticker=ticker, d=d, timeframe=timeframe):
        return 0
    if provider == 'alpaca':
        return _ingest_alpaca(db, ticker=ticker, d=d, timeframe=timeframe)
    # fallback to csv if unknown
    return 0


def _ingest_alpaca(db: Session, *, ticker: str, d: date, timeframe: str) -> int:
    key = os.getenv('ALPACA_KEY_ID')
    secret = os.getenv('ALPACA_SECRET_KEY')
    if not key or not secret:
        return 0
    # Alpaca Market Data v2 bars endpoint
    # Docs: https://docs.alpaca.markets/reference/market-data-api-bars
    tf = '1Min' if timeframe.startswith('min') else '1Day'
    # Convert 09:30–16:00 ET to UTC ISO strings with Z
    ET = ZoneInfo('America/New_York')
    start_dt = datetime.combine(d, time(9, 30), tzinfo=ET).astimezone(ZoneInfo('UTC'))
    end_dt = datetime.combine(d, time(16, 0), tzinfo=ET).astimezone(ZoneInfo('UTC'))
    start = start_dt.isoformat().replace('+00:00', 'Z')
    end = end_dt.isoformat().replace('+00:00', 'Z')
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
            tf_key = 'min' if tf == '1Min' else 'day'
            for b in bars:
                ts = datetime.fromisoformat(b['t'].replace('Z', '+00:00')).astimezone(None).replace(tzinfo=None)
                stmt = sqlite_insert(PriceBar).values(
                    ticker=ticker.upper(), ts=ts, timeframe=tf_key,
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
            return rows
    except Exception:
        db.rollback()
        return 0
