"""
Service: prices ingestion.
- Pulls minute/day bars from providers (Alpaca) and upserts into DB with idempotency.
- Skips existing days; handles on-conflict updates safely for SQLite.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
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
    # Build time window in UTC. For 1Day, query the full local day (midnight to midnight) to avoid empty results.
    ET = ZoneInfo('America/New_York')
    if tf == '1Day':
        start_dt = datetime.combine(d, time(0, 0), tzinfo=ET).astimezone(ZoneInfo('UTC'))
        end_dt = datetime.combine(d, time(23, 59, 59), tzinfo=ET).astimezone(ZoneInfo('UTC'))
    else:
        # 1Min: restrict to market hours
        start_dt = datetime.combine(d, time(9, 30), tzinfo=ET).astimezone(ZoneInfo('UTC'))
        end_dt = datetime.combine(d, time(16, 0), tzinfo=ET).astimezone(ZoneInfo('UTC'))
    start = start_dt.isoformat().replace('+00:00', 'Z')
    end = end_dt.isoformat().replace('+00:00', 'Z')
    url = f"https://data.alpaca.markets/v2/stocks/{ticker.upper()}/bars"
    feed = os.getenv('ALPACA_FEED', 'iex')
    params = {"start": start, "end": end, "timeframe": tf, "limit": 10000, "adjustment": "raw", "feed": feed}
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


def ingest_provider_bars_multi(
    db: Session,
    *,
    provider: str,
    tickers: list[str],
    d: date,
    timeframe: str = "minute",
    skip_if_exists: bool = True,
) -> int:
    """Batch ingestion for multiple tickers in one provider call when supported.

    Returns total rows upserted across all tickers.
    """
    provider = provider.lower()
    if not tickers:
        return 0
    # If skipping and all tickers already have bars for the day, short-circuit
    if skip_if_exists:
        all_have = True
        for t in tickers:
            if not day_has_bars(db, ticker=t, d=d, timeframe=timeframe):
                all_have = False
                break
        if all_have:
            return 0
    if provider == 'alpaca':
        return _ingest_alpaca_multi(db, tickers=tickers, d=d, timeframe=timeframe)
    # Fallback: loop per ticker
    total = 0
    for t in tickers:
        total += ingest_provider_bars(db, provider=provider, ticker=t, d=d, timeframe=timeframe, skip_if_exists=skip_if_exists)
    return total


def _ingest_alpaca_multi(db: Session, *, tickers: list[str], d: date, timeframe: str) -> int:
    key = os.getenv('ALPACA_KEY_ID')
    secret = os.getenv('ALPACA_SECRET_KEY')
    if not key or not secret:
        return 0
    tf = '1Min' if timeframe.startswith('min') else '1Day'
    ET = ZoneInfo('America/New_York')
    if tf == '1Day':
        start_dt = datetime.combine(d, time(0, 0), tzinfo=ET).astimezone(ZoneInfo('UTC'))
        end_dt = datetime.combine(d, time(23, 59, 59), tzinfo=ET).astimezone(ZoneInfo('UTC'))
    else:
        start_dt = datetime.combine(d, time(9, 30), tzinfo=ET).astimezone(ZoneInfo('UTC'))
        end_dt = datetime.combine(d, time(16, 0), tzinfo=ET).astimezone(ZoneInfo('UTC'))
    start = start_dt.isoformat().replace('+00:00', 'Z')
    end = end_dt.isoformat().replace('+00:00', 'Z')
    feed = os.getenv('ALPACA_FEED', 'iex')

    # Chunk symbols to avoid URL length/limits (Alpaca allows many, but keep conservative)
    symbols = [t.upper() for t in tickers]
    chunk_size = int(os.getenv('ALPACA_MULTI_CHUNK', '50'))
    total_rows = 0
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    tf_key = 'min' if tf == '1Min' else 'day'

    with httpx.Client(timeout=25) as client:
        for i in range(0, len(symbols), chunk_size):
            syms = symbols[i:i+chunk_size]
            url = "https://data.alpaca.markets/v2/stocks/bars"
            params = {
                "symbols": ",".join(syms),
                "start": start,
                "end": end,
                "timeframe": tf,
                "limit": 10000,
                "adjustment": "raw",
                "feed": feed,
            }
            try:
                r = client.get(url, params=params, headers=headers)
                r.raise_for_status()
                data = r.json()
                rows = 0
                # Handle both possible shapes:
                # 1) { bars: { "AAPL": [ {t,o,h,l,c,v}, ... ], "MSFT": [...] } }
                # 2) { bars: [ { "S": "AAPL", "t": ..., "o": ... }, ... ] }
                bars_obj = data.get('bars')
                if isinstance(bars_obj, dict):
                    items_iter = []
                    for sym, arr in bars_obj.items() or {}:
                        for b in arr or []:
                            items_iter.append((sym, b))
                elif isinstance(bars_obj, list):
                    items_iter = []
                    for b in bars_obj:
                        sym = b.get('S') or b.get('symbol') or b.get('s')
                        if sym:
                            items_iter.append((sym, b))
                else:
                    items_iter = []

                for sym, b in items_iter:
                    try:
                        ts = datetime.fromisoformat(str(b['t']).replace('Z', '+00:00')).astimezone(None).replace(tzinfo=None)
                        o = float(b['o']); h = float(b['h']); l = float(b['l']); c = float(b['c']); v = float(b.get('v', 0) or 0)
                        stmt = sqlite_insert(PriceBar).values(
                            ticker=str(sym).upper(), ts=ts, timeframe=tf_key,
                            open=o, high=h, low=l, close=c, volume=v
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
                    except Exception:
                        continue
                db.commit()
                total_rows += rows
            except Exception:
                db.rollback()
                continue
    return total_rows


def synthesize_day_from_minutes(db: Session, *, ticker: str, d: date) -> int:
    """
    Create a daily bar by aggregating minute bars when provider returned none.
    open: first minute open; high: max high; low: min low; close: last minute close; volume: sum.
    """
    start_dt = datetime(d.year, d.month, d.day, 0, 0, 0)
    end_dt = datetime(d.year, d.month, d.day, 23, 59, 59)
    q = (
        db.query(PriceBar)
        .filter(PriceBar.ticker == ticker.upper(), PriceBar.timeframe == 'min')
        .filter(PriceBar.ts >= start_dt, PriceBar.ts <= end_dt)
        .order_by(PriceBar.ts.asc())
    )
    mins = q.all()
    if not mins:
        return 0
    o = float(mins[0].open)
    h = max(float(m.high) for m in mins)
    l = min(float(m.low) for m in mins)
    c = float(mins[-1].close)
    v = sum(float(m.volume or 0) for m in mins)
    # Use 16:00 local as the daily bar timestamp
    ts_day = datetime(d.year, d.month, d.day, 16, 0, 0)
    existing = db.query(PriceBar).filter(
        PriceBar.ticker == ticker.upper(), PriceBar.timeframe == 'day', PriceBar.ts == ts_day
    ).one_or_none()
    if existing:
        existing.open = o
        existing.high = h
        existing.low = l
        existing.close = c
        existing.volume = v
    else:
        db.add(PriceBar(
            ticker=ticker.upper(), ts=ts_day, timeframe='day', open=o, high=h, low=l, close=c, volume=v
        ))
    db.commit()
    return 1


def enforce_retention(
    db: Session,
    *,
    minute_keep_days: int = 60,
    day_keep_days: int = 730,
    tickers: list[str] | None = None,
) -> dict:
    """Delete old bars beyond retention windows.

    minute_keep_days: keep this many most recent days of minute bars
    day_keep_days: keep this many most recent days of daily bars
    tickers: optional subset; if None, apply to all
    """
    now = datetime.now()
    cutoff_min = now - timedelta(days=max(1, minute_keep_days))
    cutoff_day = now - timedelta(days=max(1, day_keep_days))

    q_min = db.query(PriceBar).filter(PriceBar.timeframe == 'min', PriceBar.ts < cutoff_min)
    q_day = db.query(PriceBar).filter(PriceBar.timeframe == 'day', PriceBar.ts < cutoff_day)
    if tickers:
        uppers = [t.upper() for t in tickers]
        q_min = q_min.filter(PriceBar.ticker.in_(uppers))
        q_day = q_day.filter(PriceBar.ticker.in_(uppers))

    deleted_min = q_min.delete(synchronize_session=False)
    deleted_day = q_day.delete(synchronize_session=False)
    db.commit()
    return {"deleted_minute": int(deleted_min or 0), "deleted_daily": int(deleted_day or 0)}
