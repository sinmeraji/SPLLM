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
from ..engine.llm import propose_trades, Proposal
from ..services.context import build_news_context
from ..core.config import settings
from ..services.rules import evaluate_order
from ..services.sim import apply_order, ensure_initialized, get_cash


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


async def llm_job() -> None:
    d_et = datetime.now(tz=ET).date()
    ts = datetime.utcnow()
    tickers = _load_tickers()
    try:
        await bus.publish({"type": "job", "name": "llm", "status": "start", "date": d_et.isoformat()})
    except Exception:
        pass
    with SessionLocal() as db:
        try:
            ensure_initialized(db, settings.initial_cash_usd)
        except Exception:
            pass
        ctx = {
            "as_of": ts.isoformat(),
            "tickers": tickers,
            "portfolio_cash": get_cash(db),
            "news": build_news_context(d_et, time(16, 0), tickers),
        }
        try:
            props: list[Proposal] = propose_trades(ctx)
        except Exception:
            props = []
        cash = get_cash(db)
        day_orders_count = 0
        for p in props:
            ref_price = 100.0
            try:
                rule = evaluate_order(
                    db,
                    now_et=ts,
                    ticker=p.ticker,
                    side=p.action,
                    quantity=p.quantity,
                    reference_price=ref_price,
                    cash=cash,
                    day_turnover_notional=0.0,
                    day_orders_count=day_orders_count,
                    last_exit_time_by_ticker={},
                )
                if not rule.accepted:
                    await bus.publish({
                        "type": "decision",
                        "ts": ts.isoformat(),
                        "ticker": p.ticker,
                        "side": p.action,
                        "qty": 0.0,
                        "price": ref_price,
                        "accepted": False,
                        "reasons": rule.reasons,
                        "source": "llm",
                        "reason": "llm-decision",
                    })
                    continue
                order = apply_order(
                    db,
                    ts_et=ts,
                    ticker=p.ticker,
                    side=p.action,
                    quantity=rule.adjusted_quantity,
                    price=ref_price,
                    slippage_bps=settings.execution.slippage_bps,
                    commission_usd=settings.execution.commission_usd,
                    reason='llm',
                )
                day_orders_count += 1
                cash = get_cash(db)
                await bus.publish({
                    "type": "trade",
                    "ts": ts.isoformat(),
                    "ticker": p.ticker,
                    "side": p.action,
                    "qty": rule.adjusted_quantity,
                    "price": ref_price,
                    "order_id": order.id,
                    "source": "llm",
                    "reason": "llm-decision",
                    "accepted": True,
                })
            except Exception:
                continue
    try:
        await bus.publish({"type": "job", "name": "llm", "status": "end", "date": d_et.isoformat()})
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
    # LLM decisions: interval minutes from env (0 disables) and EOD run (16:15 ET)
    llm_minutes = int(os.getenv("LLM_UPDATE_MINUTES", "0"))
    if llm_minutes > 0:
        _scheduler.add_job(llm_job, IntervalTrigger(minutes=llm_minutes))
    if os.getenv("LLM_EOD", "1") == "1":
        _scheduler.add_job(llm_job, CronTrigger(hour=16, minute=15, day_of_week="mon-fri", timezone=ET))
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


