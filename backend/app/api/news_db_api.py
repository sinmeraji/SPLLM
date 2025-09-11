"""
API: DB-backed news ingestion and metrics.
- POST /newsdb/ingest/{date}: fetch from provider (gdelt|edgar|local) and upsert to DB.
- POST /newsdb/metrics/{date}: recompute metrics for date (1d/7d/30d/90d).
- GET  /newsdb/{date}: list raw news rows for date/tickers.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..providers.news import LocalCacheNewsProvider, GdeltProvider, EdgarProvider, NewsItem
from ..services.news_db import upsert_news_items_to_db, compute_metrics_for_date
from ..models.news import NewsRaw, NewsMetric


router = APIRouter()


def _provider_from_name(name: Optional[str]):
    prov = (name or "local").lower()
    if prov == "gdelt":
        return GdeltProvider(), None
    if prov == "edgar":
        return EdgarProvider(), "filings"
    return LocalCacheNewsProvider(), None


@router.post("/newsdb/ingest/{d}")
def newsdb_ingest(d: str, tickers: Optional[str] = None, provider: Optional[str] = None, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        day = date.fromisoformat(d)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date")
    tickers_list = [t.strip().upper() for t in (tickers.split(',') if tickers else []) if t.strip()]
    prov, explicit_type = _provider_from_name(provider)
    items: List[NewsItem] = prov.get_time_gated(day, time(23, 59), tickers_list or ['AAPL','MSFT','NVDA','QQQ'])
    res = upsert_news_items_to_db(db, items, explicit_type=explicit_type)
    return {"date": day.isoformat(), "provider": (provider or 'local').lower(), **res}


@router.post("/newsdb/metrics/{d}")
def newsdb_metrics(d: str, tickers: Optional[str] = None, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        day = date.fromisoformat(d)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date")
    tickers_list = [t.strip().upper() for t in (tickers.split(',') if tickers else []) if t.strip()]
    res = compute_metrics_for_date(db, day, tickers_list or None)
    return {"date": day.isoformat(), **res}


@router.get("/newsdb/{d}")
def newsdb_get_raw(d: str, tickers: Optional[str] = None, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        day = date.fromisoformat(d)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date")
    tickers_list = [t.strip().upper() for t in (tickers.split(',') if tickers else []) if t.strip()]
    start = datetime.combine(day, datetime.min.time())
    end = datetime.combine(day, datetime.min.time())
    end = end.replace(hour=23, minute=59, second=59)
    q = db.query(NewsRaw).filter(NewsRaw.ts >= start, NewsRaw.ts <= end)
    if tickers_list:
        q = q.filter(NewsRaw.ticker.in_(tickers_list))
    rows = q.order_by(NewsRaw.ts.asc()).all()
    out = [{
        'ts': r.ts.isoformat(),
        'ticker': r.ticker,
        'type': r.type,
        'title': r.title,
        'url': r.url,
        'source': r.source,
        'sentiment': r.sentiment,
    } for r in rows]
    return {"date": day.isoformat(), "count": len(out), "items": out}


@router.get("/newsdb/metrics/{d}")
def newsdb_get_metrics(d: str, tickers: Optional[str] = None, window: Optional[str] = None, type: Optional[str] = None, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        day = date.fromisoformat(d)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date")
    tickers_list = [t.strip().upper() for t in (tickers.split(',') if tickers else []) if t.strip()]
    q = db.query(NewsMetric).filter(NewsMetric.date == day)
    if tickers_list:
        q = q.filter(NewsMetric.ticker.in_(tickers_list))
    if window:
        q = q.filter(NewsMetric.window == window)
    if type:
        q = q.filter(NewsMetric.type == type)
    rows = q.order_by(NewsMetric.ticker.asc(), NewsMetric.type.asc(), NewsMetric.window.asc()).all()
    out = [{
        'date': r.date.isoformat(),
        'ticker': r.ticker,
        'type': r.type,
        'window': r.window,
        'count': r.count,
        'novelty': r.novelty,
        'reliability': r.reliability,
        'sentiment_avg': r.sentiment_avg,
    } for r in rows]
    return {"date": day.isoformat(), "count": len(out), "items": out}


