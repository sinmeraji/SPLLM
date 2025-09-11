"""
Service: APScheduler jobs for live updates.
- Every 1 minute (market hours ET): ingest Alpaca minute bars and update intraday indicators.
- End-of-day (16:10 ET): compute daily indicators snapshot.
Env:
  ENABLE_SCHEDULER=1|0, SCHED_TICKERS="AAPL,MSFT", SCHED_MINUTE_CRON="*/1 9-16 * * 1-5"
"""
from __future__ import annotations

import os
from datetime import datetime, date
from pathlib import Path
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..services.prices_ingest import ingest_provider_bars
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


_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler:
        return
    _scheduler = AsyncIOScheduler(timezone=str(ET))
    # Every minute on weekdays 9:30-16:00 ET (use 9-16 hours, every minute; job itself runs regardless of seconds)
    minute_cron = os.getenv("SCHED_MINUTE_CRON", "*/1 9-16 * * 1-5")
    _scheduler.add_job(minute_job, CronTrigger.from_crontab(minute_cron))
    # EOD at 16:10 ET on weekdays
    _scheduler.add_job(eod_job, CronTrigger(hour=16, minute=10, day_of_week="mon-fri", timezone=ET))
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


