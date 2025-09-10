from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import List
import csv

from fastapi import APIRouter, HTTPException

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
def get_prices(ticker: str, iso_date: str) -> dict:
    # Reads data/prices/<ticker>/minute/<date>.csv
    try:
        d = date.fromisoformat(iso_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")

    path = Path('data/prices') / ticker.upper() / 'minute' / f"{d.isoformat()}.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No data for ticker/date")

    rows: List[dict] = []
    with path.open('r', newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append({
                "ts": row["ts"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0) or 0),
            })
    return {"ticker": ticker.upper(), "date": iso_date, "bars": rows}



@router.get('/prices/available-dates/{ticker}')
def get_available_dates(ticker: str) -> dict:
    root = Path('data/prices') / ticker.upper() / 'minute'
    if not root.exists():
        return {'dates': []}
    dates = sorted([p.stem for p in root.glob('*.csv')])
    return {'dates': dates}

@router.get('/prices/range/{ticker}')
def get_prices_range(ticker: str, start: str, end: str) -> dict:
    from datetime import date
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='Invalid start/end')
    root = Path('data/prices') / ticker.upper() / 'minute'
    if not root.exists():
        return {'ticker': ticker.upper(), 'bars': []}
    import csv
    bars = []
    cur = start_d
    while cur <= end_d:
        fp = root / f"{cur.isoformat()}.csv"
        if fp.exists():
            with fp.open('r', newline='', encoding='utf-8') as f:
                r = csv.DictReader(f)
                for row in r:
                    bars.append({
                        'ts': row['ts'],
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': float(row.get('volume', 0) or 0),
                    })
        cur = date.fromordinal(cur.toordinal()+1)
    return {'ticker': ticker.upper(), 'start': start, 'end': end, 'bars': bars}
