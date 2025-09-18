"""
Service: analyst ingestion and metrics computation.
- Upserts AnalystEvent rows from provider items with idempotency by (ticker, ts, type, firm).
- Computes AnalystMetric per ticker/date/window (1d/7d/30d) with counts and average PT/est deltas.
"""
from __future__ import annotations

from datetime import datetime, date, time, timedelta
from typing import List, Dict

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..models.analyst import AnalystEvent, AnalystMetric
from ..providers.analyst import get_recent_for_ticker


def upsert_events_for_ticker(db: Session, ticker: str, limit: int = 50) -> int:
    items = get_recent_for_ticker(ticker, limit=limit)
    written = 0
    for it in items:
        # Idempotency by (ticker, ts, type, firm)
        exists = (
            db.query(AnalystEvent.id)
            .filter(
                AnalystEvent.ticker == it.ticker,
                AnalystEvent.ts == it.ts,
                AnalystEvent.type == it.type,
                AnalystEvent.firm == it.firm,
            )
            .first()
        )
        if exists:
            continue
        row = AnalystEvent(
            ts=it.ts,
            ticker=it.ticker,
            type=it.type,
            firm=it.firm,
            from_rating=it.from_rating,
            to_rating=it.to_rating,
            old_pt=it.old_pt,
            new_pt=it.new_pt,
            source=it.source,
        )
        db.add(row)
        written += 1
    if written:
        db.commit()
    return written


def compute_metrics_for_date(db: Session, d: date, tickers: List[str]) -> Dict[str, int]:
    windows = [1, 7, 30]
    total = 0
    for t in tickers:
        for w in windows:
            start_dt = datetime.combine(d - timedelta(days=w - 1), datetime.min.time())
            end_dt = datetime.combine(d, datetime.max.time())
            rows: List[AnalystEvent] = (
                db.query(AnalystEvent)
                .filter(AnalystEvent.ticker == t)
                .filter(AnalystEvent.ts >= start_dt, AnalystEvent.ts <= end_dt)
                .all()
            )
            up = sum(1 for r in rows if r.type in ("upgrade", "pt_raise", "est_raise"))
            down = sum(1 for r in rows if r.type in ("downgrade", "pt_cut", "est_cut"))
            pt_deltas = [((r.new_pt - r.old_pt) / r.old_pt) * 100.0 for r in rows if r.old_pt and r.new_pt]
            pt_avg = (sum(pt_deltas) / len(pt_deltas)) if pt_deltas else 0.0
            # Placeholder: estimate deltas not provided by FMP basic endpoints
            est_avg = 0.0
            # Upsert metric row
            m = (
                db.query(AnalystMetric)
                .filter(AnalystMetric.date == d, AnalystMetric.ticker == t, AnalystMetric.window == f"{w}d")
                .one_or_none()
            )
            if not m:
                m = AnalystMetric(date=datetime.combine(d, time(0, 0)), ticker=t, window=f"{w}d")
                db.add(m)
            m.up_count = int(up)
            m.down_count = int(down)
            m.pt_delta_avg_pct = float(pt_avg)
            m.est_delta_avg_pct = float(est_avg)
            total += 1
    db.commit()
    return {"metrics_written": total}


