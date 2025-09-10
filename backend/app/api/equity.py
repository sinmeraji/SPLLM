from __future__ import annotations

from datetime import date
from pathlib import Path
import csv
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..models.portfolio import Order


router = APIRouter()


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur = date.fromordinal(cur.toordinal() + 1)


def read_day_close(ticker: str, d: date) -> float | None:
    fp = Path('data/prices') / ticker.upper() / 'minute' / f"{d.isoformat()}.csv"
    if not fp.exists():
        return None
    last_close = None
    with fp.open('r', newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                last_close = float(row['close'])
            except Exception:
                continue
    return last_close


@router.get('/equity/range')
def get_equity_range(start: str, end: str, db: Session = Depends(get_db)) -> dict:
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail='Invalid start/end')
    if end_d < start_d:
        start_d, end_d = end_d, start_d

    # Load all orders in chronological order to reconstruct PnL
    orders: List[Order] = (
        db.query(Order)
        .filter(Order.ts_et >= start_d.isoformat())
        .filter(Order.ts_et <= end_d.isoformat())
        .order_by(Order.ts_et.asc())
        .all()
    )

    cash = float(settings.initial_cash_usd)
    positions: Dict[str, float] = {}
    order_idx = 0
    last_close: Dict[str, float] = {}
    series: List[dict] = []

    for d in daterange(start_d, end_d):
        # Apply orders up to end of this day
        while order_idx < len(orders) and orders[order_idx].ts_et.date() <= d:
            o = orders[order_idx]
            qty = float(o.quantity)
            px = float(o.price)
            if o.side.upper() == 'BUY':
                cash -= qty * px
                cash -= float(o.commission_usd or 0.0)
                positions[o.ticker] = positions.get(o.ticker, 0.0) + qty
            else:  # SELL
                cash += qty * px
                cash -= float(o.commission_usd or 0.0)
                positions[o.ticker] = positions.get(o.ticker, 0.0) - qty
            order_idx += 1

        # Mark-to-market
        equity = cash
        for ticker, qty in positions.items():
            if qty == 0:
                continue
            close_px = read_day_close(ticker, d)
            if close_px is not None:
                last_close[ticker] = close_px
            px = last_close.get(ticker)
            if px is not None:
                equity += qty * px
        series.append({'date': d.isoformat(), 'equity': round(equity, 2)})

    return {'start': start_d.isoformat(), 'end': end_d.isoformat(), 'series': series}


