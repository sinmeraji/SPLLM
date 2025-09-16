#!/usr/bin/env python
"""
Script: End-of-day updater for prices, indicators, and news metrics.
Purpose:
- For a given date (default: today ET), ingest daily price bars, recompute daily price indicators,
  fetch optional EOD news from providers, and compute news metrics rollups. Enforces data retention.

Usage examples:
- DATE=YYYY-MM-DD TICKERS=AAPL,MSFT python scripts/eod_update.py
- NEWS_PROVIDERS=gdelt,edgar_submissions MINUTE_RETENTION_DAYS=60 DAILY_RETENTION_DAYS=730 python scripts/eod_update.py

Env vars:
- DATE: ISO date (YYYY-MM-DD), defaults to today (ET)
- TICKERS: comma-separated tickers; else read from configs/universe/tickers.txt (defaults AAPL,MSFT,NVDA,QQQ)
- NEWS_PROVIDERS: gdelt,edgar,edgar_submissions (default: gdelt,edgar_submissions)
- MINUTE_RETENTION_DAYS: default 60
- DAILY_RETENTION_DAYS: default 730
"""
from __future__ import annotations

import os
from pathlib import Path
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
import logging

from dotenv import load_dotenv

# Ensure project imports resolve regardless of CWD
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.db import SessionLocal
from backend.app.utils.logging import setup_logging
from backend.app.services.prices_ingest import ingest_provider_bars, enforce_retention, synthesize_day_from_minutes
from backend.app.services.features import recompute_indicators_for_date
from backend.app.providers.news import GdeltProvider, EdgarProvider, EdgarSubmissionsProvider
from backend.app.services.news_db import upsert_news_items_to_db, compute_metrics_for_date


ET = ZoneInfo("America/New_York")


def _load_env() -> None:
    # Load explicit env file if present
    env_path = ROOT / "configs" / "env" / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path), override=False)


def _load_tickers() -> list[str]:
    raw = os.getenv("TICKERS")
    if raw:
        return [t.strip().upper() for t in raw.split(",") if t.strip()]
    fp = ROOT / "configs" / "universe" / "tickers.txt"
    defaults = ["AAPL", "MSFT", "NVDA", "QQQ"]
    if fp.exists():
        vals = [t.strip().upper() for t in fp.read_text().splitlines() if t.strip()]
        return vals or defaults
    return defaults


def _load_date() -> date:
    raw = os.getenv("DATE")
    if raw:
        return date.fromisoformat(raw)
    return datetime.now(tz=ET).date()


def _load_news_providers():
    names = [x.strip().lower() for x in os.getenv("NEWS_PROVIDERS", "gdelt,edgar_submissions").split(",") if x.strip()]
    out: list[tuple[object, str | None]] = []
    for name in names:
        if name == "gdelt":
            out.append((GdeltProvider(), None))
        elif name == "edgar":
            out.append((EdgarProvider(), "filings"))
        elif name in ("edgar_submissions", "edgar_json"):
            out.append((EdgarSubmissionsProvider(), "filings"))
    return out


def main() -> None:
    _load_env()
    setup_logging()
    log = logging.getLogger("scripts.eod_update")

    d_et = _load_date()
    tickers = _load_tickers()
    providers = _load_news_providers()
    log.info("EOD update start date=%s tickers=%s providers=%s", d_et.isoformat(), ",".join(tickers), ",".join([p.__class__.__name__ for p,_ in providers]))

    with SessionLocal() as db:
        # 1) Ingest daily bars for the date and recompute indicators
        for t in tickers:
            try:
                added = ingest_provider_bars(db, provider="alpaca", ticker=t, d=d_et, timeframe="day", skip_if_exists=False)
                if added == 0:
                    # Fallback: synthesize from minutes if provider returned nothing
                    synth = synthesize_day_from_minutes(db, ticker=t, d=d_et)
                    log.info("prices day added ticker=%s date=%s rows=%s synth=%s", t, d_et.isoformat(), added, synth)
                else:
                    log.info("prices day added ticker=%s date=%s rows=%s", t, d_et.isoformat(), added)
            except Exception as e:
                log.warning("prices day ingest failed ticker=%s date=%s err=%s", t, d_et.isoformat(), e)
            try:
                recompute_indicators_for_date(db, ticker=t, d=d_et)
                log.info("indicators recomputed ticker=%s date=%s", t, d_et.isoformat())
            except Exception as e:
                log.warning("indicators recompute failed ticker=%s date=%s err=%s", t, d_et.isoformat(), e)

        # 2) Optionally fetch news EOD and compute metrics
        for prov, explicit_type in providers:
            try:
                items = prov.get_time_gated(d_et, time(23, 59), tickers)
                upsert_news_items_to_db(db, items, explicit_type=explicit_type)
                log.info("news upserted provider=%s items=%d", prov.__class__.__name__, len(items))
            except Exception as e:
                log.warning("news ingest failed provider=%s err=%s", prov.__class__.__name__, e)
        try:
            compute_metrics_for_date(db, d_et, tickers)
            log.info("news metrics computed date=%s", d_et.isoformat())
        except Exception as e:
            log.warning("news metrics compute failed date=%s err=%s", d_et.isoformat(), e)

        # 3) Enforce retention
        try:
            minute_days = int(os.getenv("MINUTE_RETENTION_DAYS", "60"))
            day_days = int(os.getenv("DAILY_RETENTION_DAYS", "730"))
            stats = enforce_retention(db, minute_keep_days=minute_days, day_keep_days=day_days, tickers=tickers)
            log.info("retention applied deleted_minute=%s deleted_daily=%s", stats.get("deleted_minute"), stats.get("deleted_daily"))
        except Exception as e:
            log.warning("retention failed err=%s", e)

    log.info("EOD update done date=%s", d_et.isoformat())


if __name__ == "__main__":
    main()


