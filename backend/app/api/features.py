from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models.prices import PriceIndicator
from ..services.features import recompute_indicators_for_date


router = APIRouter()


@router.post('/features/recompute/{d}')
def recompute_features(d: str, tickers: Optional[str] = None, db: Session = Depends(get_db)) -> dict:
    try:
        day = date.fromisoformat(d)
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid date')
    tickers_list = [t.strip().upper() for t in (tickers.split(',') if tickers else []) if t.strip()] or ['AAPL','MSFT']
    ok = 0
    for t in tickers_list:
        if recompute_indicators_for_date(db, ticker=t, d=day):
            ok += 1
    return {'date': day.isoformat(), 'tickers': tickers_list, 'ok': ok}


@router.get('/features/{ticker}/{d}')
def get_features(ticker: str, d: str, db: Session = Depends(get_db)) -> dict:
    try:
        day = date.fromisoformat(d)
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid date')
    row = db.query(PriceIndicator).filter(PriceIndicator.ticker == ticker.upper(), PriceIndicator.date == day).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='No indicators for date')
    return {
        'ticker': ticker.upper(),
        'date': day.isoformat(),
        'r1d': row.r1d,
        'r5d': row.r5d,
        'r20d': row.r20d,
        'mom_60d': row.mom_60d,
        'vol_20d': row.vol_20d,
        'rsi_14': row.rsi_14,
        'macd': row.macd,
        'v_zscore_20d': row.v_zscore_20d,
    }


