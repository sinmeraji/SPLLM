"""
API: news ingestion, retrieval, and summarization.
- /news/ingest/{date}: incrementally ingest (gdelt|edgar|local) into CSV cache.
- /news/{date}: time-gated news retrieval for tickers.
- /news/summarize/{date}: demo summaries + SSE events.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import csv

from fastapi import APIRouter, HTTPException

from ..providers.news import LocalCacheNewsProvider, NewsItem, GdeltProvider, EdgarProvider
from ..services.news import append_news_items, read_provider_state, write_provider_state
from ..utils.events import bus


router = APIRouter()


@router.post('/news/mock')
def mock_news(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Generate mock news items for a given date and tickers into data/news/YYYY-MM-DD.csv.
    payload: { date: 'YYYY-MM-DD', tickers: ['AAPL', 'MSFT'], items_per_ticker: 3 }
    """
    d_s = payload.get('date')
    tickers = [t.upper() for t in (payload.get('tickers') or [])]
    n = int(payload.get('items_per_ticker') or 3)
    if not d_s or not tickers:
        raise HTTPException(status_code=400, detail='date and tickers are required')
    try:
        d = date.fromisoformat(d_s)
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid date')

    root = Path('data/news')
    root.mkdir(parents=True, exist_ok=True)
    fp = root / f"{d.isoformat()}.csv"

    rows: List[Dict[str, str]] = []
    base_dt = datetime.combine(d, time(9, 35))
    for t in tickers:
        for i in range(n):
            ts = base_dt + timedelta(minutes=15 * i)
            rows.append({
                'ts': ts.isoformat(),
                'ticker': t,
                'title': f"{t} mock headline #{i+1}",
                'url': f"https://example.com/{t}/{d.isoformat()}/{i+1}",
                'source': 'mock',
                'sentiment': ''
            })

    # Write with header (append if exists)
    header = ['ts', 'ticker', 'title', 'url', 'source', 'sentiment']
    write_header = not fp.exists()
    with fp.open('a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=header)
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow(r)

    return {'written': len(rows), 'file': str(fp)}
@router.post('/news/ingest/{d}')
def ingest_news_for_day(d: str, tickers: Optional[str] = None, provider: Optional[str] = None) -> Dict[str, Any]:
    """Incrementally ingest news for a day and cache to CSV. Provider: gdelt|edgar|local.
    Uses provider state to support incremental pulls (placeholder until remote providers implemented).
    """
    try:
        day = date.fromisoformat(d)
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid date')
    tickers_list = [t.strip().upper() for t in (tickers.split(',') if tickers else []) if t.strip()]

    prov = (provider or 'local').lower()
    if prov == 'gdelt':
        p = GdeltProvider()
    elif prov == 'edgar':
        p = EdgarProvider()
    else:
        p = LocalCacheNewsProvider()

    # Read state to support incremental fetch (e.g., since_ts); local provider ignores it
    state = read_provider_state(prov, day)
    window_end = time(23, 59)
    items: List[NewsItem] = p.get_time_gated(day, window_end, tickers_list or ['AAPL','MSFT','NVDA','QQQ'])

    res = append_news_items(day, items)
    # Update state (placeholder: record count)
    state['last_ingested_count'] = state.get('last_ingested_count', 0) + res['written']
    write_provider_state(prov, day, state)
    return {'date': day.isoformat(), 'provider': prov, **res}


@router.get('/news/{d}')
def get_news_for_day(d: str, tickers: Optional[str] = None) -> Dict[str, Any]:
    try:
        day = date.fromisoformat(d)
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid date')
    tickers_list = [t.strip().upper() for t in (tickers.split(',') if tickers else []) if t.strip()]
    provider = LocalCacheNewsProvider()
    # return up to end of RTH by default
    items: List[NewsItem] = provider.get_time_gated(day, time(16, 0), tickers_list or ['AAPL','MSFT','NVDA','QQQ'])
    out = [{
        'ts': it.ts.isoformat(),
        'ticker': it.ticker,
        'title': it.title,
        'url': it.url,
        'source': it.source,
        'sentiment': it.sentiment,
    } for it in items]
    return {'date': day.isoformat(), 'count': len(out), 'items': out}


@router.post('/news/summarize/{d}')
async def summarize_news_for_day(d: str) -> Dict[str, Any]:
    try:
        day = date.fromisoformat(d)
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid date')
    provider = LocalCacheNewsProvider()
    items = provider.get_time_gated(day, time(16, 0), ['AAPL','MSFT','NVDA','QQQ'])
    # naive per-ticker rollup
    per_ticker: Dict[str, List[NewsItem]] = {}
    for it in items:
        per_ticker.setdefault(it.ticker, []).append(it)
    summaries: Dict[str, str] = {}
    for t, arr in per_ticker.items():
        titles = '; '.join([a.title for a in arr[:3]])
        summaries[t] = f"{len(arr)} items. Top: {titles}"
        # emit SSE event
        await bus.publish({'type': 'news_summary', 'date': day.isoformat(), 'ticker': t, 'summary': summaries[t]})
    return {'date': day.isoformat(), 'summaries': summaries}


