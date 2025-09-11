"""
API: prices and universe endpoints.
- Reads minute bars from DB (no CSV fallback) and exposes day/range queries.
- Ingestion endpoint pulls from Alpaca and writes to DB.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..core.db import get_db
from ..services.prices_ingest import ingest_csv_bars
from ..models.prices import PriceBar

router = APIRouter()


@router.get("/universe")
def get_universe() -> dict:
    path = Path('configs/universe/tickers.txt')
    if not path.exists():
        return {"tickers": []}
    tickers = [t.strip() for t in path.read_text().splitlines() if t.strip()]
    return {"tickers": tickers}


# Removed ambiguous alias to avoid route conflicts with dynamic date route

@router.get("/prices/day/{ticker}/{iso_date}")
def get_prices(ticker: str, iso_date: str, db: Session = Depends(get_db)) -> dict:
    try:
        d = date.fromisoformat(iso_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")
    start = datetime.combine(d, datetime.min.time())
    end = start + timedelta(days=1)
    bars = (
        db.query(PriceBar)
        .filter(
            PriceBar.ticker == ticker.upper(),
            PriceBar.timeframe == 'min',
            PriceBar.ts >= start,
            PriceBar.ts < end,
        )
        .order_by(PriceBar.ts.asc())
        .all()
    )
    if not bars:
        raise HTTPException(status_code=404, detail="No data for ticker/date")
    rows = [{
        "ts": b.ts.isoformat(),
        "open": b.open,
        "high": b.high,
        "low": b.low,
        "close": b.close,
        "volume": b.volume,
    } for b in bars]
    return {"ticker": ticker.upper(), "date": iso_date, "bars": rows}


@router.get('/prices/available-dates/{ticker}')
def get_available_dates(ticker: str, db: Session = Depends(get_db)) -> dict:
    # Distinct dates present in minute bars
    rows = db.execute(
        text(
            """
            SELECT DISTINCT DATE(ts) as d
            FROM price_bars
            WHERE ticker = :ticker AND timeframe = 'min'
            ORDER BY d
            """
        ),
        {"ticker": ticker.upper()},
    ).fetchall()
    dates = [str(r[0]) for r in rows]
    return {'dates': dates}

@router.get('/prices/range/{ticker}')
def get_prices_range(ticker: str, start: str, end: str, db: Session = Depends(get_db)) -> dict:
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='Invalid start/end')
    start_dt = datetime.combine(start_d, datetime.min.time())
    end_dt = datetime.combine(end_d, datetime.min.time()) + timedelta(days=1)
    bars = (
        db.query(PriceBar)
        .filter(
            PriceBar.ticker == ticker.upper(),
            PriceBar.timeframe == 'min',
            PriceBar.ts >= start_dt,
            PriceBar.ts < end_dt,
        )
        .order_by(PriceBar.ts.asc())
        .all()
    )
    out = [{
        'ts': b.ts.isoformat(),
        'open': b.open,
        'high': b.high,
        'low': b.low,
        'close': b.close,
        'volume': b.volume,
    } for b in bars]
    return {'ticker': ticker.upper(), 'start': start, 'end': end, 'bars': out}


@router.post('/prices/ingest/{iso_date}')
def ingest_prices_db(iso_date: str, tickers: Optional[str] = None, timeframe: str = 'minute', source: str = 'alpaca', db: Session = Depends(get_db)) -> dict:
    try:
        d = date.fromisoformat(iso_date)
    except ValueError:
        raise HTTPException(status_code=400, detail='Invalid date')
    if tickers:
        tickers_list = [t.strip().upper() for t in tickers.split(',') if t.strip()]
    else:
        # default first 4 from universe
        path = Path('configs/universe/tickers.txt')
        arr = [t.strip() for t in path.read_text().splitlines() if t.strip()] if path.exists() else []
        tickers_list = [t for t in arr if t in ('AAPL','MSFT','NVDA','QQQ')][:4] or ['AAPL','MSFT','NVDA','QQQ']
    total = 0
    if source.lower() != 'alpaca':
        raise HTTPException(status_code=400, detail='Unsupported source; use source=alpaca')
    from ..services.prices_ingest import ingest_provider_bars
    for t in tickers_list:
        total += ingest_provider_bars(db, provider='alpaca', ticker=t, d=d, timeframe=timeframe)
    return {"date": d.isoformat(), "timeframe": timeframe, "source": source, "tickers": tickers_list, "rows": total}
