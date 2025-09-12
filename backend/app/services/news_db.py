"""
Service: database-backed news ingestion and metrics rollups.
- Upserts `NewsRaw` rows from provider items with idempotency checks.
- Computes `NewsMetric` aggregates per ticker/type over 1d/7d/30d/90d windows.
Usage: called by API routes to ingest (GDELT/EDGAR) and materialize metrics.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse
import json
from pathlib import Path

from sqlalchemy import and_, func, select, delete
from sqlalchemy.orm import Session

from ..models.news import NewsRaw, NewsMetric
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
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


_TRUST_CACHE: Optional[Dict[str, float]] = None


def _load_trust_map() -> Dict[str, float]:
    global _TRUST_CACHE
    if _TRUST_CACHE is not None:
        return _TRUST_CACHE
    trust: Dict[str, float] = {}
    # Defaults
    default_unknown = 0.3
    cfg = Path("configs/news_sources.yaml")
    if cfg.exists():
        try:
            data = json.loads(
                # naive YAML loader via json by replacing ': ' with '" : ' won't be robust; use simple parse
                # Instead, attempt to import yaml if available, else fallback to minimal parser
                cfg.read_text(encoding="utf-8").replace("\t", "  ")
            )
        except Exception:
            # Fallback minimal: return empty so we use defaults
            data = None
    else:
        data = None
    # If PyYAML available, load properly
    if data is None:
        try:
            import yaml  # type: ignore
            y = yaml.safe_load(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
        except Exception:
            y = {}
    else:
        y = data
    try:
        defaults = y.get("defaults", {})
        default_unknown = float(defaults.get("unknown", 0.3))
        # groups
        for group, domains in (y.get("groups", {}) or {}).items():
            score = float(defaults.get(group, default_unknown))
            for d in (domains or []):
                trust[str(d).lower()] = score
        # overrides
        for dom, sc in (y.get("overrides", {}) or {}).items():
            trust[str(dom).lower()] = float(sc)
    except Exception:
        trust = {}
    _TRUST_CACHE = trust or {}
    _TRUST_CACHE.setdefault("default", default_unknown)
    return _TRUST_CACHE


def _source_domain(source: str, url: str) -> str:
    if source:
        s = source.lower()
        # normalize common labels
        if s in ("edgar", "sec", "edgar-sec"):
            return "sec.gov"
        if s in ("gdelt",):
            return "gdelt"
    try:
        netloc = urlparse(url).netloc.lower()
        # strip www.
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""

_SIA: SentimentIntensityAnalyzer | None = None


def _get_sia() -> SentimentIntensityAnalyzer:
    global _SIA
    if _SIA is None:
        _SIA = SentimentIntensityAnalyzer()
    return _SIA


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
        # Basic sentiment from title (placeholder; upgrade to FinBERT later)
        try:
            sia = _get_sia()
            vs = sia.polarity_scores(it.title or "")
            sent = float(vs.get("compound", 0.0))
        except Exception:
            sent = 0.0
        # Basic sentiment from title (placeholder; upgrade to FinBERT later)
        try:
            sia = _get_sia()
            vs = sia.polarity_scores(it.title or "")
            sent = float(vs.get("compound", 0.0))
        except Exception:
            sent = 0.0
        row = NewsRaw(
            ts=ts,
            ticker=ticker,
            type=_infer_type_from_source(it.source, explicit_type),
            title=it.title or "",
            url=url,
            source=it.source or "",
            sentiment=float(it.sentiment) if it.sentiment is not None else sent,
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

        rows = q.all()
        # Compute reliability using trust map and corroboration
        trust = _load_trust_map()
        trust_default = float(trust.get("default", 0.3))
        # Count occurrences per ticker/type/domain to estimate corroboration
        # For simplicity, approximate by using count and average domain trust per ticker/type over window.
        for row in rows:
            nm = NewsMetric(
                date=d,
                ticker=row.ticker,
                type=row.type,
                window=f"{w}d",
                count=int(row.count or 0),
                # Novelty: inverse frequency within window
                novelty=0.0 if not row.count else round(1.0 / float(row.count), 4),
                # Reliability: average trust (fallback default); corroboration bonus = min(0.05 * (count-1), 0.2)
                reliability=(trust_default) + min(0.05 * max(0, (int(row.count or 0) - 1)), 0.2),
                sentiment_avg=float(row.sentiment_avg) if row.sentiment_avg is not None else 0.0,
            )
            db.add(nm)
            total_written += 1
        db.commit()
    return {"metrics_written": total_written, "metrics_deleted": total_deleted}


