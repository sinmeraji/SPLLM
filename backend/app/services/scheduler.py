"""
Service: APScheduler jobs for live updates.
- Every 1 minute (market hours ET): ingest Alpaca minute bars and update intraday indicators.
- End-of-day (16:10 ET): compute daily indicators snapshot.
Env:
  ENABLE_SCHEDULER=1|0, SCHED_TICKERS="AAPL,MSFT", SCHED_MINUTE_CRON="*/1 9-16 * * 1-5"
"""
from __future__ import annotations

import os
from datetime import datetime, date, time
from pathlib import Path
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..services.prices_ingest import ingest_provider_bars
from ..providers.news import GdeltProvider, EdgarProvider, EdgarSubmissionsProvider
from ..services.news_db import upsert_news_items_to_db, compute_metrics_for_date
from ..services.features import (
    recompute_intraday_indicators_last_90d,
    recompute_indicators_for_date,
)
from ..utils.events import bus


ET = ZoneInfo("America/New_York")


def _load_tickers() -> List[str]:
    raw = os.getenv("SCHED_TICKERS")
    if raw:
        return [t.strip().upper() for t in raw.split(",") if t.strip()]
    p = Path("configs/universe/tickers.txt")
    if p.exists():
        arr = [t.strip().upper() for t in p.read_text().splitlines() if t.strip()]
        # default to top few to keep it light
        defaults = ["AAPL", "MSFT", "NVDA", "QQQ"]
        return [t for t in arr if t in defaults] or defaults
    return ["AAPL", "MSFT"]


async def minute_job() -> None:
    d_et = datetime.now(tz=ET).date()
    tickers = _load_tickers()
    try:
        await bus.publish({"type": "job", "name": "minute", "status": "start", "date": d_et.isoformat()})
    except Exception:
        pass
    with SessionLocal() as db:
        for t in tickers:
            try:
                ingest_provider_bars(db, provider="alpaca", ticker=t, d=d_et, timeframe="minute", skip_if_exists=False)
                recompute_intraday_indicators_last_90d(db, ticker=t, as_of=d_et)
            except Exception:
                continue
    try:
        await bus.publish({"type": "job", "name": "minute", "status": "end", "date": d_et.isoformat()})
    except Exception:
        pass


async def eod_job() -> None:
    d_et = datetime.now(tz=ET).date()
    tickers = _load_tickers()
    try:
        await bus.publish({"type": "job", "name": "eod", "status": "start", "date": d_et.isoformat()})
    except Exception:
        pass
    with SessionLocal() as db:
        for t in tickers:
            try:
                recompute_indicators_for_date(db, ticker=t, d=d_et)
            except Exception:
                continue
    try:
        await bus.publish({"type": "job", "name": "eod", "status": "end", "date": d_et.isoformat()})
    except Exception:
        pass


async def news_job() -> None:
    d_et = datetime.now(tz=ET).date()
    tickers = _load_tickers()
    providers_env = os.getenv("SCHED_NEWS_PROVIDERS", "gdelt,edgar_submissions").lower()
    providers = []
    for name in [x.strip() for x in providers_env.split(',') if x.strip()]:
        if name == "gdelt":
            providers.append((GdeltProvider(), None))
        elif name == "edgar":
            providers.append((EdgarProvider(), "filings"))
        elif name in ("edgar_submissions", "edgar_json"):
            providers.append((EdgarSubmissionsProvider(), "filings"))
    try:
        await bus.publish({"type": "job", "name": "news", "status": "start", "date": d_et.isoformat()})
    except Exception:
        pass
    with SessionLocal() as db:
        for prov, explicit_type in providers:
            try:
                items = prov.get_time_gated(d_et, time(23, 59), tickers)
                upsert_news_items_to_db(db, items, explicit_type=explicit_type)
            except Exception:
                continue
        try:
            compute_metrics_for_date(db, d_et, tickers)
        except Exception:
            pass
    try:
        await bus.publish({"type": "job", "name": "news", "status": "end", "date": d_et.isoformat()})
    except Exception:
        pass


_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler:
        return
    _scheduler = AsyncIOScheduler(timezone=str(ET))
    # Price updates: interval minutes from env (default 5). If SCHED_MINUTE_CRON provided, use cron instead.
    minute_cron = os.getenv("SCHED_MINUTE_CRON", "").strip()
    price_minutes = int(os.getenv("PRICE_UPDATE_MINUTES", "5"))
    if minute_cron:
        _scheduler.add_job(minute_job, CronTrigger.from_crontab(minute_cron))
    else:
        _scheduler.add_job(minute_job, IntervalTrigger(minutes=price_minutes))
    # News updates: interval minutes from env (default 60)
    news_minutes = int(os.getenv("NEWS_UPDATE_MINUTES", "60"))
    _scheduler.add_job(news_job, IntervalTrigger(minutes=news_minutes))
    # EOD at 16:10 ET on weekdays
    _scheduler.add_job(eod_job, CronTrigger(hour=16, minute=10, day_of_week="mon-fri", timezone=ET))
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


