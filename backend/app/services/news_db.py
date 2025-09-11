"""
Service: database-backed news ingestion and metrics rollups.
- Upserts `NewsRaw` rows from provider items with idempotency checks.
- Computes `NewsMetric` aggregates per ticker/type over 1d/7d/30d/90d windows.
Usage: called by API routes to ingest (GDELT/EDGAR) and materialize metrics.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import and_, func, select, delete
from sqlalchemy.orm import Session

from ..models.news import NewsRaw, NewsMetric
from ..providers.news import NewsItem


def _infer_type_from_source(source: str, explicit_type: Optional[str]) -> str:
    if explicit_type:
        return explicit_type
    s = (source or "").lower()
    if "edgar" in s or s == "edgar":
        return "filings"
    if "gdelt" in s:
        return "breaking"
    return "other"


def upsert_news_items_to_db(
    db: Session,
    items: Iterable[NewsItem],
    explicit_type: Optional[str] = None,
) -> Dict[str, int]:
    """Insert news items into NewsRaw if not already present by (ticker, ts, url).
    Returns counts {written, skipped}.
    """
    written = 0
    skipped = 0
    for it in items:
        ticker = it.ticker.upper()
        ts = it.ts
        url = it.url or ""
        # Idempotency check
        exists_q = (
            db.query(NewsRaw.id)
            .filter(
                and_(NewsRaw.ticker == ticker, NewsRaw.ts == ts, NewsRaw.url == url)
            )
            .first()
        )
        if exists_q:
            skipped += 1
            continue
        row = NewsRaw(
            ts=ts,
            ticker=ticker,
            type=_infer_type_from_source(it.source, explicit_type),
            title=it.title or "",
            url=url,
            source=it.source or "",
            sentiment=0.0 if it.sentiment is None else float(it.sentiment),
        )
        db.add(row)
        written += 1
    if written:
        db.commit()
    return {"written": written, "skipped": skipped}


def _window_days_list() -> List[int]:
    return [1, 7, 30, 90]


def compute_metrics_for_date(
    db: Session,
    d: date,
    tickers: Optional[List[str]] = None,
) -> Dict[str, int]:
    """Compute NewsMetric rows for a given date d across standard windows.
    Rewrites metrics for that date (idempotent refresh) for requested tickers.
    """
    tickers_u = [t.upper() for t in (tickers or [])]

    # For each window, aggregate from NewsRaw where ts.date in [d - (w-1), d]
    total_written = 0
    total_deleted = 0

    # Build deletion filter for refresh
    del_filter = [NewsMetric.date == d]
    if tickers_u:
        del_filter.append(NewsMetric.ticker.in_(tickers_u))
    db.execute(delete(NewsMetric).where(and_(*del_filter)))
    db.commit()
    # We count deletions approximately by affected tickers * windows; optional to compute exact count

    for w in _window_days_list():
        start_day = d - timedelta(days=w - 1)
        # Aggregate by ticker, type
        q = (
            db.query(
                func.date(NewsRaw.ts).label("day"),
                NewsRaw.ticker,
                NewsRaw.type,
                func.count().label("count"),
                func.avg(NewsRaw.sentiment).label("sentiment_avg"),
            )
            .filter(NewsRaw.ts >= datetime.combine(start_day, datetime.min.time()))
            .filter(NewsRaw.ts < datetime.combine(d + timedelta(days=1), datetime.min.time()))
        )
        if tickers_u:
            q = q.filter(NewsRaw.ticker.in_(tickers_u))
        q = q.group_by(NewsRaw.ticker, NewsRaw.type)

        for row in q.all():
            nm = NewsMetric(
                date=d,
                ticker=row.ticker,
                type=row.type,
                window=f"{w}d",
                count=int(row.count or 0),
                novelty=0.0,
                reliability=0.0,
                sentiment_avg=float(row.sentiment_avg) if row.sentiment_avg is not None else 0.0,
            )
            db.add(nm)
            total_written += 1
        db.commit()
    return {"metrics_written": total_written, "metrics_deleted": total_deleted}


